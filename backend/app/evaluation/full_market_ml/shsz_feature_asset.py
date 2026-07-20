"""Materialize a new SH/SZ feature asset from the certified R1 raw panel."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.services.ml_online_feature_provider import OnlineFeatureProvider

from .feature_contract import FeatureContract, RegisteredFeature, build_full_market_feature_contract
from .features import assert_leak_free_schema, build_cross_section_features, build_time_series_features
from .moneyflow_features import MONEYFLOW_FEATURE_NAMES


UNIVERSE_ID = "shsz_a_share_v1"
ALLOWED_EXCHANGES = ("SH", "SZ")
FEATURE_ASSET_VERSION = "shsz_r1_feature_asset_v1"
MIN_MONEYFLOW_COVERAGE = 0.95
MIN_PARITY_HISTORY_SESSIONS = 84
MAX_PARITY_SYMBOLS = 128
FUTURE_EXECUTION_INPUT_COLUMNS = frozenset(
    {
        "next_open_date",
        "next_adjusted_open",
        "next_valid_ohlc",
        "next_is_suspended",
        "next_at_up_limit_open",
        "entry_tradeable",
        "eligible_signal_day",
    }
)
RAW_INPUT_COLUMNS = frozenset(
    {
        "trade_date",
        "symbol",
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "volume_shares",
        "amount_cny",
        "turnover_rate",
        "total_mv",
        "circ_mv",
        "pe",
        "pb",
        "ps",
        "net_mf_amount",
        "listing_age_trade_days",
        "valid_ohlc",
        "industry_l1",
        "at_up_limit",
        "at_down_limit",
        "market_index_close",
        "market_index_amount",
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    }
)
REQUIRED_RAW_COLUMNS = frozenset(
    {
        "trade_date",
        "symbol",
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "volume_shares",
        "amount_cny",
        "turnover_rate",
        "total_mv",
        "circ_mv",
        "pe",
        "pb",
        "net_mf_amount",
        "listing_age_trade_days",
        "valid_ohlc",
        "industry_l1",
        "at_up_limit",
        "at_down_limit",
        "market_index_close",
        "market_index_amount",
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
    }
)
MONEYFLOW_RAW_COLUMNS = tuple(
    f"{side}_{size}_amount" for side in ("buy", "sell") for size in ("sm", "md", "lg", "elg")
)


class SHSZFeatureAssetError(ValueError):
    """Raised when a certified R1 asset cannot safely produce an R2 matrix."""


def materialize_shsz_feature_asset(
    *,
    panel_root: str | Path,
    label_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
    parity_dates: Iterable[str],
    materialized_shard_count: int = 16,
) -> dict[str, Any]:
    """Build a new research-only feature matrix from R1 raw panel fields.

    The function deliberately never reads historical feature/dataset parquet.
    It consumes only the R1 raw panel, while the label asset supplies the sealed
    development dates and registered validation folds.
    """
    if materialized_shard_count < 2:
        raise SHSZFeatureAssetError("materialized_shard_count must be at least two")
    panel = _load_panel_source(Path(panel_root).expanduser().resolve())
    labels = _load_label_source(Path(label_root).expanduser().resolve(), panel)
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"output directory already exists: {destination}")
    normalized_parity_dates = tuple(_date_text(value) for value in parity_dates)
    if len(normalized_parity_dates) != 3 or len(set(normalized_parity_dates)) != 3:
        raise SHSZFeatureAssetError("exactly three distinct ISO parity dates are required")
    if not set(normalized_parity_dates).issubset(labels["development_dates"]):
        raise SHSZFeatureAssetError("parity dates must belong to the sealed development dates")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete feature asset requires inspection: {temporary}")
    temporary.mkdir(parents=True)
    try:
        _write_progress(temporary, "data-verify", status="running")
        source_columns = _source_columns(panel["paths"])
        _assert_safe_raw_input(source_columns)
        all_sessions = _source_sessions(panel["paths"])
        cutoff = max(labels["development_dates"])
        sessions = tuple(date for date in all_sessions if date <= cutoff)
        if len(sessions) < MIN_PARITY_HISTORY_SESSIONS:
            raise SHSZFeatureAssetError("development history is too short for online/offline feature parity")
        moneyflow = _moneyflow_coverage(panel["paths"], source_columns, cutoff)
        if moneyflow["admission_minimum_coverage"] < MIN_MONEYFLOW_COVERAGE:
            raise SHSZFeatureAssetError(
                "detailed SH/SZ moneyflow coverage is below the fixed 95% gate: "
                f"{moneyflow['admission_minimum_coverage']:.4f}"
            )
        contract = _shsz_r2_feature_contract(
            moneyflow_coverage=float(moneyflow["admission_minimum_coverage"]),
        )
        assert_leak_free_schema(contract.feature_names)
        run_contract = _run_contract(panel, labels, contract, source_columns, sessions, moneyflow, code_commit, materialized_shard_count)
        _write_json(temporary / "materialization_contract.json", run_contract)
        quality = {
            "status": "ready_for_shsz_r2_feature_materialization",
            "panel_row_count": panel["manifest"]["output"]["panel_row_count"],
            "panel_symbol_count": panel["manifest"]["output"]["panel_symbol_count"],
            "source_session_count": len(all_sessions),
            "development_feature_session_count": len(sessions),
            "development_start": sessions[0],
            "development_end": sessions[-1],
            "moneyflow": moneyflow,
            "future_execution_input_columns": sorted(FUTURE_EXECUTION_INPUT_COLUMNS & set(source_columns)),
            "old_feature_values_used_as_input": False,
            "production_integration_allowed": False,
        }
        _write_json(temporary / "data_quality_report.json", quality)

        input_root = _partition_input(panel["paths"], source_columns, cutoff, temporary, materialized_shard_count)
        time_series_root = _materialize_time_series(input_root, temporary, sessions, materialized_shard_count)
        matrix_root = _materialize_cross_sections(
            time_series_root,
            temporary,
            sessions,
            contract,
            materialized_shard_count,
        )
        coverage = _coverage_report(matrix_root, contract, labels["validation_folds"])
        _write_json(temporary / "feature_coverage_report.json", coverage)
        if not coverage["passed"]:
            raise SHSZFeatureAssetError("registered core feature coverage is below the fixed gate")
        parity = _parity_report(
            panel["paths"],
            source_columns,
            all_sessions,
            matrix_root,
            contract,
            normalized_parity_dates,
        )
        if not all(item["passed"] for item in parity.values()):
            raise SHSZFeatureAssetError("offline/online feature parity failed")
        files = _matrix_file_manifest(matrix_root)
        leakage_audit = {
            "future_execution_input_column_count": 0,
            "future_execution_input_columns": [],
            "denied_feature_schema_columns": [],
            "future_panel_dates_used": 0,
            "input_cutoff": cutoff,
        }
        manifest = {
            **run_contract,
            "status": "complete",
            "research_ready": True,
            "production_integration_allowed": False,
            "completed_at": _now(),
            "matrix_path": str(matrix_root),
            "matrix_files": files,
            "row_count": sum(int(item["row_count"]) for item in files),
            "trade_date_count": len(files),
            "coverage": coverage,
            "parity": parity,
            "leakage_audit": leakage_audit,
            "interpretation": (
                "This is a SH/SZ R2 feature-quality asset only. It contains no labels, does not train a model, "
                "does not open a final time holdout, and cannot change production decisions."
            ),
        }
        manifest["sha256"] = _sha256_json({key: value for key, value in manifest.items() if key != "sha256"})
        _write_json(temporary / "feature_asset_manifest.json", manifest)
        _write_progress(temporary, "complete", status="complete", completed_dates=len(sessions), total_dates=len(sessions))
        os.replace(temporary, destination)
        return manifest
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _load_panel_source(root: Path) -> dict[str, Any]:
    manifest_path = root / "panel_rebuild_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"R1 panel manifest is missing: {manifest_path}")
    manifest = _read_json(manifest_path)
    if manifest.get("status") != "complete_shsz_panel_rebuilt" or manifest.get("research_ready") is not True:
        raise SHSZFeatureAssetError("R1 panel is not certified for feature materialization")
    if manifest.get("universe_id") != UNIVERSE_ID or tuple(manifest.get("allowed_exchanges", ())) != ALLOWED_EXCHANGES:
        raise SHSZFeatureAssetError("R1 panel does not declare the SH/SZ research universe")
    paths = tuple(sorted((root / "panel" / "stage=full-build").glob("shard=*/data.parquet")))
    if not paths:
        raise FileNotFoundError("R1 panel has no parquet shards")
    return {"root": root, "manifest": manifest, "manifest_path": manifest_path, "paths": paths}


def _load_label_source(root: Path, panel: Mapping[str, Any]) -> dict[str, Any]:
    registry_path = root / "dataset_registry.json"
    split_path = root / "development_split_plan.json"
    manifest_path = root / "label_split_manifest.json"
    for path in (registry_path, split_path, manifest_path):
        if not path.is_file():
            raise FileNotFoundError(f"R1 label asset input is missing: {path}")
    registry = _read_json(registry_path)
    manifest = _read_json(manifest_path)
    split = _read_json(split_path)
    if registry.get("source_panel_manifest_sha256") != _sha256_file(panel["manifest_path"]):
        raise SHSZFeatureAssetError("label asset is not bound to the supplied panel manifest")
    if registry.get("label_quality_passed") is not True:
        raise SHSZFeatureAssetError("label asset failed its quality gate")
    if manifest.get("status") != "complete_development_labels_ready" or manifest.get("research_ready") is not True:
        raise SHSZFeatureAssetError("label asset is not research-ready")
    if manifest.get("universe_id") != UNIVERSE_ID or tuple(manifest.get("allowed_exchanges", ())) != ALLOWED_EXCHANGES:
        raise SHSZFeatureAssetError("label asset does not declare the SH/SZ research universe")
    future = split.get("future_holdout")
    if not isinstance(future, Mapping) or future.get("formal_evaluation_allowed") is not False:
        raise SHSZFeatureAssetError("label split has opened the formal future holdout")
    development_dates = tuple(sorted({_date_text(value) for value in split.get("development_dates", ())}))
    if not development_dates:
        raise SHSZFeatureAssetError("label split has no development dates")
    folds = {
        f"fold-{item['fold']}": tuple(_date_text(value) for value in item.get("validation_dates", ()))
        for item in split.get("walk_forward", ())
    }
    if len(folds) != 5 or any(not dates for dates in folds.values()):
        raise SHSZFeatureAssetError("label split must contain five non-empty validation folds")
    return {
        "registry": registry,
        "manifest": manifest,
        "registry_path": registry_path,
        "split_path": split_path,
        "development_dates": development_dates,
        "validation_folds": folds,
    }


def _source_columns(paths: Iterable[Path]) -> tuple[str, ...]:
    schemas = [set(pq.ParquetFile(path).schema_arrow.names) for path in paths]
    common = set.intersection(*schemas)
    missing = sorted(REQUIRED_RAW_COLUMNS - common)
    if missing:
        raise SHSZFeatureAssetError("R1 panel misses required raw feature inputs: " + ", ".join(missing))
    return tuple(sorted(common & RAW_INPUT_COLUMNS))


def _assert_safe_raw_input(columns: Iterable[str]) -> None:
    columns = tuple(columns)
    future = sorted(FUTURE_EXECUTION_INPUT_COLUMNS & set(columns))
    if future:
        raise SHSZFeatureAssetError("feature input includes future execution fields: " + ", ".join(future))
    forbidden = sorted(
        column
        for column in columns
        if column.startswith(("future_", "label_", "horizon_available_", "eligible_for_training_", "entry_", "exit_"))
    )
    if forbidden:
        raise SHSZFeatureAssetError("feature input includes label or execution fields: " + ", ".join(forbidden))


def _source_sessions(paths: Iterable[Path]) -> tuple[str, ...]:
    dates: set[str] = set()
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=65_536, columns=["trade_date"]):
            dates.update(_normalize_trade_dates(batch.to_pandas()["trade_date"]).dropna().tolist())
    if not dates:
        raise SHSZFeatureAssetError("R1 panel has no signal-date rows")
    return tuple(sorted(dates))


def _moneyflow_coverage(paths: Iterable[Path], columns: Iterable[str], cutoff: str) -> dict[str, Any]:
    available = set(columns)
    missing = sorted(set(MONEYFLOW_RAW_COLUMNS) - available)
    if missing:
        raise SHSZFeatureAssetError("R1 panel misses detailed moneyflow fields: " + ", ".join(missing))
    counts = {name: [0, 0] for name in MONEYFLOW_RAW_COLUMNS}
    daily: dict[str, dict[str, list[int]]] = {}
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=65_536, columns=["trade_date", *MONEYFLOW_RAW_COLUMNS]):
            frame = batch.to_pandas()
            frame["trade_date"] = _normalize_trade_dates(frame["trade_date"])
            frame = frame.loc[frame["trade_date"].le(cutoff)].copy()
            valid = frame.loc[:, MONEYFLOW_RAW_COLUMNS].apply(pd.to_numeric, errors="coerce").notna()
            totals = frame.groupby("trade_date", sort=False).size()
            present = valid.groupby(frame["trade_date"], sort=False).sum()
            for name in MONEYFLOW_RAW_COLUMNS:
                counts[name][0] += int(valid[name].sum())
                counts[name][1] += len(frame)
            for trade_date, total in totals.items():
                for name in MONEYFLOW_RAW_COLUMNS:
                    current = daily.setdefault(str(trade_date), {}).setdefault(name, [0, 0])
                    current[0] += int(present.loc[trade_date, name])
                    current[1] += int(total)
    coverage = {name: present / total if total else 0.0 for name, (present, total) in counts.items()}
    daily_minimum = min(
        (present / total for features in daily.values() for present, total in features.values() if total),
        default=0.0,
    )
    return {
        "field_coverage": coverage,
        "minimum_coverage": min(coverage.values(), default=0.0),
        "minimum_daily_coverage": daily_minimum,
        "admission_minimum_coverage": min(min(coverage.values(), default=0.0), daily_minimum),
        "date_count": len(daily),
    }


def _run_contract(
    panel: Mapping[str, Any],
    labels: Mapping[str, Any],
    contract: FeatureContract,
    source_columns: tuple[str, ...],
    sessions: tuple[str, ...],
    moneyflow: Mapping[str, Any],
    code_commit: str,
    shard_count: int,
) -> dict[str, Any]:
    return {
        "feature_asset_version": FEATURE_ASSET_VERSION,
        "universe_id": UNIVERSE_ID,
        "allowed_exchanges": list(ALLOWED_EXCHANGES),
        "panel_manifest_sha256": _sha256_file(panel["manifest_path"]),
        "label_registry_sha256": _sha256_file(labels["registry_path"]),
        "label_split_sha256": _sha256_file(labels["split_path"]),
        "feature_contract": contract.to_dict(),
        "feature_contract_sha256": contract.sha256(),
        "raw_input_columns": list(source_columns),
        "raw_input_schema_sha256": _sha256_json({"columns": source_columns}),
        "development_sessions": list(sessions),
        "moneyflow_coverage": dict(moneyflow),
        "code_commit": str(code_commit),
        "materialized_shard_count": int(shard_count),
        "formal_future_holdout_status": "awaiting_model_freeze_and_future_labels",
        "production_integration_allowed": False,
    }


def _shsz_r2_feature_contract(*, moneyflow_coverage: float) -> FeatureContract:
    """Register detailed flow fields only for this new, coverage-certified asset."""
    base = build_full_market_feature_contract(
        moneyflow_coverage=moneyflow_coverage,
        include_moneyflow=True,
    )
    detailed = tuple(
        RegisteredFeature(
            name=name,
            group="detailed_moneyflow",
            source="moneyflow+daily",
            formula=_detailed_moneyflow_formula(name),
            lookback_sessions=_detailed_moneyflow_lookback(name),
            availability="required",
            allowed_quality=("valid-with-rows",),
            adjusted_status="raw",
            missing_policy="observed-null-with-explicit-missing-flag",
        )
        for name in MONEYFLOW_FEATURE_NAMES
    )
    return replace(
        base,
        version="shsz_r1_detailed_moneyflow_parity_v1",
        features=(*base.features, *detailed),
    )


def _detailed_moneyflow_formula(name: str) -> str:
    if name == "flow_minus_industry_median":
        return "large_net_flow_ratio + extra_large_net_flow_ratio minus median by trade_date and industry_l1"
    if name.startswith("price_flow_divergence_"):
        return "rolling large_plus_extra_large net-flow ratio minus adjusted return"
    if name == "large_minus_small_flow_ratio":
        return "large_net_flow_ratio minus small_net_flow_ratio"
    if name.endswith("_missing"):
        return "observed detailed order-size moneyflow is missing"
    if "persistence" in name:
        return "rolling observed order-size net-flow ratio"
    return "observed order-size net-flow amount times 10000 divided by daily amount_cny"


def _detailed_moneyflow_lookback(name: str) -> int:
    if name.endswith("_20d"):
        return 20
    if name.endswith("_5d"):
        return 5
    return 0


def _partition_input(
    paths: Iterable[Path],
    columns: tuple[str, ...],
    cutoff: str,
    root: Path,
    shard_count: int,
) -> Path:
    output = root / "stages" / "input-shards"
    output.mkdir(parents=True, exist_ok=False)
    path_list = tuple(paths)
    for index, path in enumerate(path_list, start=1):
        frame = pq.read_table(path, columns=list(columns)).to_pandas()
        frame["trade_date"] = _normalize_trade_dates(frame["trade_date"])
        frame["symbol"] = frame["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
        frame = frame.loc[frame["trade_date"].le(cutoff)].copy()
        frame["_materialized_shard"] = frame["symbol"].map(lambda value: _symbol_shard(str(value), shard_count))
        for shard in sorted(frame["_materialized_shard"].unique()):
            selected = frame.loc[frame["_materialized_shard"].eq(shard)].drop(columns="_materialized_shard")
            _write_parquet(selected, output / f"shard={shard:02d}" / f"part={index:03d}.parquet")
        _write_progress(root, "input-shards", status="running", completed_source_shards=index, total_source_shards=len(path_list))
    return output


def _materialize_time_series(input_root: Path, root: Path, sessions: tuple[str, ...], shard_count: int) -> Path:
    output = root / "stages" / "time-series"
    output.mkdir(parents=True, exist_ok=False)
    for shard in range(shard_count):
        parts = sorted((input_root / f"shard={shard:02d}").glob("part=*.parquet"))
        if not parts:
            raise SHSZFeatureAssetError(f"materialized symbol shard has no inputs: {shard}")
        rows = pd.concat([pq.read_table(path).to_pandas() for path in parts], ignore_index=True)
        featured = build_time_series_features(None, rows, include_moneyflow=True, market_sessions=sessions)
        for trade_date, daily in featured.groupby("trade_date", sort=True):
            _write_parquet(daily, output / f"shard={shard:02d}" / f"trade_date={trade_date}" / "data.parquet")
        _write_progress(root, "time-series", status="running", completed_shards=shard + 1, total_shards=shard_count)
    return output


def _materialize_cross_sections(
    time_series_root: Path,
    root: Path,
    sessions: tuple[str, ...],
    contract: FeatureContract,
    shard_count: int,
) -> Path:
    output = root / "matrix"
    output.mkdir(parents=True, exist_ok=False)
    columns = ["trade_date", "symbol", *contract.feature_names]
    for index, trade_date in enumerate(sessions, start=1):
        rows = []
        for shard in range(shard_count):
            path = time_series_root / f"shard={shard:02d}" / f"trade_date={trade_date}" / "data.parquet"
            if path.is_file():
                rows.append(pq.read_table(path).to_pandas())
        if not rows:
            raise SHSZFeatureAssetError(f"time-series stage has no rows for {trade_date}")
        market = pd.concat(rows, ignore_index=True)
        featured = build_cross_section_features(None, {"market": market}, include_moneyflow=True)["market"]
        missing = sorted(set(columns) - set(featured.columns))
        if missing:
            raise SHSZFeatureAssetError("feature matrix misses registered columns: " + ", ".join(missing))
        _write_parquet(featured.loc[:, columns], output / f"trade_date={trade_date}" / "data.parquet")
        _write_progress(root, "cross-section", status="running", completed_dates=index, total_dates=len(sessions))
    return output


def _coverage_report(matrix_root: Path, contract: FeatureContract, validation_folds: Mapping[str, tuple[str, ...]]) -> dict[str, Any]:
    coverage_by_fold: dict[str, dict[str, float]] = {}
    failures: list[str] = []
    for fold, dates in validation_folds.items():
        frames = []
        for trade_date in dates:
            path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
            if not path.is_file():
                raise SHSZFeatureAssetError(f"feature matrix has no validation-date partition: {trade_date}")
            frames.append(pq.read_table(path, columns=list(contract.required_feature_names)).to_pandas())
        matrix = pd.concat(frames, ignore_index=True)
        values = {
            feature: float(np.isfinite(pd.to_numeric(matrix[feature], errors="coerce")).mean())
            for feature in contract.required_feature_names
        }
        coverage_by_fold[fold] = values
        failures.extend(
            f"{fold}:{feature}={coverage:.4f}"
            for feature, coverage in values.items()
            if coverage < contract.minimum_fold_coverage
        )
    return {
        "passed": not failures,
        "minimum_required_coverage": contract.minimum_fold_coverage,
        "coverage_by_fold": coverage_by_fold,
        "failures": failures,
    }


def _parity_report(
    paths: Iterable[Path],
    columns: tuple[str, ...],
    all_sessions: tuple[str, ...],
    matrix_root: Path,
    contract: FeatureContract,
    parity_dates: tuple[str, ...],
) -> dict[str, Any]:
    report = {}
    for trade_date in parity_dates:
        offline = pq.read_table(matrix_root / f"trade_date={trade_date}" / "data.parquet").to_pandas()
        symbols = tuple(
            sorted(offline["symbol"].astype(str).unique(), key=lambda value: hashlib.sha256(value.encode()).hexdigest())[:MAX_PARITY_SYMBOLS]
        )
        history_start = all_sessions[max(0, all_sessions.index(trade_date) - MIN_PARITY_HISTORY_SESSIONS + 1)]
        online_input, future_rows_discarded = _parity_input(paths, columns, symbols, trade_date, history_start)
        source_dates = {source: trade_date for source in contract.registered_sources}
        source_quality = {source: "valid-with-rows" for source in contract.registered_sources}
        online = OnlineFeatureProvider(contract).build_features_as_of(
            online_input,
            as_of_date=trade_date,
            source_as_of_dates=source_dates,
            source_qualities=source_quality,
        )
        online = online.loc[online["symbol"].astype(str).isin(symbols)].sort_values("symbol").reset_index(drop=True)
        expected = offline.loc[offline["symbol"].astype(str).isin(symbols)].sort_values("symbol").reset_index(drop=True)
        if online[["trade_date", "symbol"]].to_dict("records") != expected[["trade_date", "symbol"]].to_dict("records"):
            raise SHSZFeatureAssetError(f"online/offline parity identity differs for {trade_date}")
        np.testing.assert_allclose(
            online[list(contract.feature_names)].to_numpy(dtype=float),
            expected[list(contract.feature_names)].to_numpy(dtype=float),
            rtol=0.0,
            atol=contract.parity_tolerance,
            equal_nan=True,
        )
        report[trade_date] = {
            "passed": True,
            "sampled_symbol_count": len(symbols),
            "history_start": history_start,
            "future_rows_used": 0,
            "future_rows_discarded_before_calculation": future_rows_discarded,
            "tolerance": contract.parity_tolerance,
        }
    return report


def _parity_input(
    paths: Iterable[Path],
    columns: tuple[str, ...],
    symbols: tuple[str, ...],
    trade_date: str,
    history_start: str,
) -> tuple[pd.DataFrame, int]:
    frames = []
    future_rows_discarded = 0
    selected_symbols = set(symbols)
    for path in paths:
        frame = pq.read_table(path, columns=list(columns)).to_pandas()
        frame["trade_date"] = _normalize_trade_dates(frame["trade_date"])
        frame["symbol"] = frame["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
        future_rows_discarded += int(frame["trade_date"].gt(trade_date).sum())
        current_history = frame["trade_date"].between(history_start, trade_date)
        sampled_history = frame["symbol"].isin(selected_symbols) & frame["trade_date"].le(trade_date)
        rows = frame.loc[current_history | sampled_history].copy()
        if not rows.empty:
            frames.append(rows)
    if not frames:
        raise SHSZFeatureAssetError(f"no input rows for parity date {trade_date}")
    return pd.concat(frames, ignore_index=True), future_rows_discarded


def _matrix_file_manifest(root: Path) -> list[dict[str, Any]]:
    files = []
    for path in sorted(root.glob("trade_date=*/data.parquet")):
        files.append(
            {
                "path": str(path.relative_to(root.parent)),
                "trade_date": path.parent.name.removeprefix("trade_date="),
                "row_count": int(pq.ParquetFile(path).metadata.num_rows),
                "bytes": int(path.stat().st_size),
                "sha256": _sha256_file(path),
            }
        )
    if not files:
        raise SHSZFeatureAssetError("feature matrix has no date partitions")
    return files


def _symbol_shard(symbol: str, shard_count: int) -> int:
    return int(hashlib.sha256(symbol.encode("ascii", "ignore")).hexdigest()[:8], 16) % shard_count


def _write_parquet(rows: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".parquet", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        table = pa.Table.from_pandas(rows, preserve_index=False)
        # ``trade_date=...`` is a Hive partition key.  Its in-file Arrow type must
        # match the partition parser's string type so a standard dataset scan does
        # not fail while merging schemas.
        for column in ("trade_date", "symbol"):
            if column not in table.column_names:
                continue
            index = table.schema.get_field_index(column)
            values = [None if pd.isna(value) else str(value) for value in rows[column]]
            table = table.set_column(index, column, pa.array(values, type=pa.string()))
        pq.write_table(table, temporary, compression="zstd")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_progress(root: Path, stage: str, *, status: str, **details: Any) -> None:
    _write_json(
        root / "progress.json",
        {
            "status": status,
            "stage": stage,
            "pid": os.getpid(),
            "peak_rss_bytes": _peak_rss_bytes(),
            "updated_at": _now(),
            **details,
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SHSZFeatureAssetError(f"JSON must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _date_text(value: object) -> str:
    parsed = pd.to_datetime(value, errors="raise")
    return parsed.strftime("%Y-%m-%d")


def _normalize_trade_dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="raise").dt.strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _peak_rss_bytes() -> int:
    import resource

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024
