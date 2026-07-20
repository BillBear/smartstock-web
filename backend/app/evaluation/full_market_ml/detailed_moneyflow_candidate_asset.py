"""Reference-only certification for a detailed-moneyflow research input asset."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .features import build_time_series_features
from .tushare_training_field_lineage_audit import (
    DETAILED_MONEYFLOW_AMOUNT_FIELDS,
    DERIVED_MONEYFLOW_FEATURE_DEPENDENCIES,
)


MONEYFLOW_COVERAGE_GATE = 0.95
_DERIVED_FEATURES = tuple(DERIVED_MONEYFLOW_FEATURE_DEPENDENCIES)
_PARITY_TIME_SERIES_FEATURES = (
    "medium_net_flow_persistence_20d",
    "large_net_flow_persistence_20d",
    "price_flow_divergence_5d",
    "price_flow_divergence_20d",
)
_PANEL_REQUIRED_COLUMNS = {
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
    *DETAILED_MONEYFLOW_AMOUNT_FIELDS,
}


class DetailedMoneyflowCandidateAssetError(ValueError):
    """Raised when an immutable source cannot be used as a research candidate."""


def inspect_detailed_moneyflow_candidate_asset(
    *,
    source_run_root: str | Path,
    code_commit: str,
    parity_dates: Iterable[str] = (),
) -> dict[str, object]:
    """Inspect an immutable full-market run without copying or mutating it."""
    source_root = _require_directory(source_run_root, "source run root")
    source = _load_verified_source(source_root)
    coverage = _stream_field_coverage(source["dataset_path"])
    parity = _verify_parity(
        dataset_path=source["dataset_path"],
        panel_paths=source["panel_paths"],
        sessions=source["quality"]["observed_trade_dates"],
        parity_dates=tuple(_normalise_date(value) for value in parity_dates),
    )
    observed_minimum = min(
        (float(value["all_rows"]["coverage"]) for name, value in coverage.items() if name in DETAILED_MONEYFLOW_AMOUNT_FIELDS),
        default=0.0,
    )
    reported = float(source["quality"]["moneyflow_coverage"])
    admission_blocked = reported < MONEYFLOW_COVERAGE_GATE or observed_minimum < MONEYFLOW_COVERAGE_GATE
    status = "complete_moneyflow_admission_blocked" if admission_blocked else "complete_candidate_only"
    return {
        "schema_version": 1,
        "candidate_asset_version": "detailed_moneyflow_candidate_v1",
        "status": status,
        "reference_only": True,
        "training_ready": False,
        "production_integration_allowed": False,
        "code_commit": str(code_commit),
        "source": {
            "run_root": str(source_root),
            "dataset_id": source["registry"].get("dataset_id"),
            "dataset_path": str(source["dataset_path"]),
            "dataset_sha256": source["hashes"]["dataset"],
            "quality_report_sha256": source["hashes"]["quality_report"],
            "collection_manifest_sha256": source["hashes"]["collection_manifest"],
            "raw_seed_source_manifest_sha256": source["hashes"]["raw_seed_source_manifest"],
            "panel_shard_count": len(source["panel_paths"]),
        },
        "quality_gate": {
            "required_moneyflow_coverage": MONEYFLOW_COVERAGE_GATE,
            "reported_moneyflow_coverage": reported,
            "observed_minimum_raw_detail_coverage": observed_minimum,
            "moneyflow_admission_blocked": admission_blocked,
            "source_quality_ready": True,
            "source_duplicate_key_count": int(source["quality"]["duplicate_key_count"]),
        },
        "field_coverage": coverage,
        "parity": parity,
        "interpretation": (
            "This artifact proves source integrity, retained columns, bounded coverage, and parity only. "
            "It neither trains nor admits a model and cannot change production decisions."
        ),
    }


def _load_verified_source(root: Path) -> dict[str, object]:
    registry_path = root / "artifacts" / "full-build" / "dataset_registry.json"
    quality_path = root / "artifacts" / "full-build" / "quality_report.json"
    manifest_path = root / "manifests" / "full-build.json"
    provenance_path = root / "raw_seed_provenance.json"
    dataset_path = root / "artifacts" / "full-build" / "dataset.parquet"
    for name, path in {
        "dataset registry": registry_path,
        "quality report": quality_path,
        "collection manifest": manifest_path,
        "raw seed provenance": provenance_path,
        "dataset parquet": dataset_path,
    }.items():
        if not path.is_file():
            raise DetailedMoneyflowCandidateAssetError(f"{name} is missing: {path}")
    registry = _read_json(registry_path)
    quality = _read_json(quality_path)
    manifest = _read_json(manifest_path)
    provenance = _read_json(provenance_path)
    assets = registry.get("assets")
    if not isinstance(assets, Mapping):
        raise DetailedMoneyflowCandidateAssetError("dataset registry has no assets map")
    hashes: dict[str, str] = {}
    for asset_name, expected_path in {
        "dataset": dataset_path,
        "quality_report": quality_path,
        "collection_manifest": manifest_path,
    }.items():
        record = assets.get(asset_name)
        if not isinstance(record, Mapping):
            raise DetailedMoneyflowCandidateAssetError(f"dataset registry has no {asset_name} record")
        recorded_path = Path(str(record.get("path", ""))).expanduser().resolve()
        if recorded_path != expected_path.resolve():
            raise DetailedMoneyflowCandidateAssetError(f"dataset registry {asset_name} path does not match source run")
        observed = _sha256_file(expected_path)
        expected = str(record.get("sha256", ""))
        if observed != expected:
            label = asset_name.replace("_", " ")
            raise DetailedMoneyflowCandidateAssetError(f"{label} SHA256 does not match dataset registry")
        hashes[asset_name] = observed
    if quality.get("ready") is not True or quality.get("blocking_codes"):
        raise DetailedMoneyflowCandidateAssetError("source quality report is not ready")
    if int(quality.get("duplicate_key_count", -1)) != 0:
        raise DetailedMoneyflowCandidateAssetError("source quality report has duplicate primary keys")
    if not isinstance(quality.get("observed_trade_dates"), list) or not quality["observed_trade_dates"]:
        raise DetailedMoneyflowCandidateAssetError("source quality report has no observed trade dates")
    if quality.get("moneyflow_coverage") is None:
        raise DetailedMoneyflowCandidateAssetError("source quality report has no moneyflow coverage")
    moneyflow_partitions = [item for item in manifest.get("partitions", []) if isinstance(item, Mapping) and item.get("endpoint") == "moneyflow"]
    if not moneyflow_partitions or any(item.get("status") == "failed" for item in moneyflow_partitions):
        raise DetailedMoneyflowCandidateAssetError("collection manifest has unavailable moneyflow partitions")
    raw_source = _require_directory(provenance.get("source_root", ""), "raw seed source root")
    raw_source_manifest = raw_source / "source_manifest.json"
    if not raw_source_manifest.is_file():
        raise DetailedMoneyflowCandidateAssetError("raw seed source manifest is missing")
    observed_raw_source_hash = _sha256_file(raw_source_manifest)
    if provenance.get("verification_status") != "verified" or provenance.get("source_manifest_sha256") != observed_raw_source_hash:
        raise DetailedMoneyflowCandidateAssetError("raw seed provenance does not match its source manifest")
    hashes["raw_seed_source_manifest"] = observed_raw_source_hash
    dataset = pq.ParquetFile(dataset_path)
    dataset_columns = set(dataset.schema_arrow.names)
    _require_columns(dataset_columns, DETAILED_MONEYFLOW_AMOUNT_FIELDS, "dataset raw detailed fields")
    _require_columns(dataset_columns, _DERIVED_FEATURES, "dataset derived detailed fields")
    panel_root = root / "panel" / "stage=full-build"
    panel_paths = tuple(sorted(panel_root.glob("shard=*/data.parquet")))
    if not panel_paths:
        raise DetailedMoneyflowCandidateAssetError("source panel has no parquet shards")
    for path in panel_paths:
        _require_columns(set(pq.ParquetFile(path).schema_arrow.names), _PANEL_REQUIRED_COLUMNS, "panel raw fields")
    return {
        "registry": registry,
        "quality": quality,
        "dataset_path": dataset_path,
        "panel_paths": panel_paths,
        "hashes": hashes,
    }


def _stream_field_coverage(dataset_path: Path) -> dict[str, object]:
    fields = (*DETAILED_MONEYFLOW_AMOUNT_FIELDS, *_DERIVED_FEATURES)
    columns = ["trade_date", "symbol", *fields]
    parquet = pq.ParquetFile(dataset_path)
    if "eligible_for_training" in parquet.schema_arrow.names:
        columns.append("eligible_for_training")
    counts = {field: {"all": [0, 0], "eligible": [0, 0], "by_date": {}} for field in fields}
    dates: set[str] = set()
    symbols: set[str] = set()
    row_count = 0
    for batch in parquet.iter_batches(batch_size=65_536, columns=columns):
        frame = batch.to_pandas()
        frame["trade_date"] = frame["trade_date"].map(_normalise_date)
        frame["symbol"] = frame["symbol"].astype(str).str.split(".", regex=False).str[0].str.zfill(6)
        eligible = frame.get("eligible_for_training", pd.Series(True, index=frame.index)).fillna(False).astype(bool)
        row_count += len(frame)
        dates.update(frame["trade_date"].tolist())
        symbols.update(frame["symbol"].tolist())
        for field in fields:
            valid = frame[field].notna()
            entry = counts[field]
            entry["all"][0] += int(valid.sum())
            entry["all"][1] += len(frame)
            entry["eligible"][0] += int((valid & eligible).sum())
            entry["eligible"][1] += int(eligible.sum())
            per_date = frame.assign(_valid=valid).groupby("trade_date", sort=False).agg(total=("_valid", "size"), present=("_valid", "sum"))
            for trade_date, values in per_date.iterrows():
                current = entry["by_date"].setdefault(str(trade_date), [0, 0])
                current[0] += int(values["present"])
                current[1] += int(values["total"])
    result: dict[str, object] = {}
    for field, value in counts.items():
        per_date_ratios = [present / total for present, total in value["by_date"].values() if total]
        result[field] = {
            "all_rows": _coverage(value["all"]),
            "eligible_rows": _coverage(value["eligible"]),
            "per_date_coverage": {
                "date_count": len(per_date_ratios),
                "minimum": min(per_date_ratios, default=0.0),
                "median": float(median(per_date_ratios)) if per_date_ratios else 0.0,
            },
            "warmup_or_derived_null_count": (
                value["all"][1] - value["all"][0] if field in _DERIVED_FEATURES else 0
            ),
        }
    result["_summary"] = {"row_count": row_count, "trade_date_count": len(dates), "symbol_count": len(symbols)}
    return result


def _verify_parity(
    *,
    dataset_path: Path,
    panel_paths: tuple[Path, ...],
    sessions: Iterable[object],
    parity_dates: tuple[str, ...],
) -> dict[str, object]:
    if not parity_dates:
        return {}
    session_dates = tuple(sorted({_normalise_date(value) for value in sessions}))
    reports: dict[str, object] = {}
    for trade_date in parity_dates:
        if trade_date not in set(session_dates):
            raise DetailedMoneyflowCandidateAssetError(f"parity date is absent from source sessions: {trade_date}")
        expected = _dataset_parity_rows(dataset_path, trade_date)
        if expected.empty:
            raise DetailedMoneyflowCandidateAssetError(f"parity date has no complete detailed feature rows: {trade_date}")
        symbols = tuple(sorted(expected["symbol"].unique())[:8])
        history, future_rows_discarded = _panel_symbol_history(panel_paths, symbols, trade_date)
        if history.empty:
            raise DetailedMoneyflowCandidateAssetError(f"panel has no parity history for {trade_date}")
        time_series = build_time_series_features(
            None,
            history,
            include_moneyflow=True,
            market_sessions=[date for date in session_dates if date <= trade_date],
        )
        actual_time_series = time_series.loc[time_series["trade_date"].eq(trade_date), ["symbol", *_PARITY_TIME_SERIES_FEATURES]]
        expected_time_series = expected.loc[:, ["symbol", *_PARITY_TIME_SERIES_FEATURES]]
        _assert_close(expected_time_series, actual_time_series, "time-series detailed moneyflow parity")
        expected_flow = expected.loc[:, ["symbol", "flow_minus_industry_median"]]
        actual_flow = _same_day_flow_minus_industry(panel_paths, trade_date, symbols)
        _assert_close(expected_flow, actual_flow, "industry-relative detailed moneyflow parity")
        reports[trade_date] = {
            "passed": True,
            "symbols": list(symbols),
            "max_feature_input_trade_date": str(history["trade_date"].max()),
            "future_rows_used": 0,
            "future_rows_discarded_before_calculation": future_rows_discarded,
        }
    return reports


def _dataset_parity_rows(dataset_path: Path, trade_date: str) -> pd.DataFrame:
    columns = ["trade_date", "symbol", *_PARITY_TIME_SERIES_FEATURES, "flow_minus_industry_median"]
    frames = []
    for batch in pq.ParquetFile(dataset_path).iter_batches(batch_size=65_536, columns=columns):
        frame = batch.to_pandas()
        frame["trade_date"] = frame["trade_date"].map(_normalise_date)
        frame = frame.loc[frame["trade_date"].eq(trade_date)].copy()
        if not frame.empty:
            frame["symbol"] = frame["symbol"].astype(str).str.split(".", regex=False).str[0].str.zfill(6)
            complete = frame.loc[:, [*_PARITY_TIME_SERIES_FEATURES, "flow_minus_industry_median"]].notna().all(axis=1)
            frames.append(frame.loc[complete])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def _panel_symbol_history(panel_paths: tuple[Path, ...], symbols: tuple[str, ...], trade_date: str) -> tuple[pd.DataFrame, int]:
    frames = []
    future_rows_discarded = 0
    wanted = set(symbols)
    for path in panel_paths:
        columns = sorted(_PANEL_REQUIRED_COLUMNS)
        for batch in pq.ParquetFile(path).iter_batches(batch_size=65_536, columns=columns):
            frame = batch.to_pandas()
            frame["trade_date"] = frame["trade_date"].map(_normalise_date)
            frame["symbol"] = frame["symbol"].astype(str).str.split(".", regex=False).str[0].str.zfill(6)
            selected = frame["symbol"].isin(wanted)
            future_rows_discarded += int((selected & frame["trade_date"].gt(trade_date)).sum())
            frame = frame.loc[selected & frame["trade_date"].le(trade_date)].copy()
            if not frame.empty:
                frames.append(frame)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), future_rows_discarded


def _same_day_flow_minus_industry(panel_paths: tuple[Path, ...], trade_date: str, symbols: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    columns = ["trade_date", "symbol", "industry_l1", "amount_cny", "buy_lg_amount", "sell_lg_amount", "buy_elg_amount", "sell_elg_amount"]
    for path in panel_paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=65_536, columns=columns):
            frame = batch.to_pandas()
            frame["trade_date"] = frame["trade_date"].map(_normalise_date)
            frame = frame.loc[frame["trade_date"].eq(trade_date)].copy()
            if not frame.empty:
                frame["symbol"] = frame["symbol"].astype(str).str.split(".", regex=False).str[0].str.zfill(6)
                rows.append(frame)
    market = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=columns)
    if market.empty:
        raise DetailedMoneyflowCandidateAssetError(f"panel has no rows on parity date: {trade_date}")
    amount = pd.to_numeric(market["amount_cny"], errors="coerce").where(lambda value: value.gt(0))
    aggregate = (
        pd.to_numeric(market["buy_lg_amount"], errors="coerce")
        - pd.to_numeric(market["sell_lg_amount"], errors="coerce")
        + pd.to_numeric(market["buy_elg_amount"], errors="coerce")
        - pd.to_numeric(market["sell_elg_amount"], errors="coerce")
    ) * 10_000.0 / amount
    market["flow_minus_industry_median"] = aggregate - aggregate.groupby(market["industry_l1"], dropna=True).transform("median")
    return market.loc[market["symbol"].isin(symbols), ["symbol", "flow_minus_industry_median"]].copy()


def _assert_close(expected: pd.DataFrame, actual: pd.DataFrame, label: str) -> None:
    columns = [column for column in expected.columns if column != "symbol"]
    left = expected.sort_values("symbol").reset_index(drop=True)
    right = actual.sort_values("symbol").reset_index(drop=True)
    if left["symbol"].tolist() != right["symbol"].tolist():
        raise DetailedMoneyflowCandidateAssetError(f"{label} symbols do not match")
    for column in columns:
        if not np.allclose(
            pd.to_numeric(left[column], errors="coerce").to_numpy(),
            pd.to_numeric(right[column], errors="coerce").to_numpy(),
            rtol=1e-6,
            atol=1e-8,
            equal_nan=True,
        ):
            raise DetailedMoneyflowCandidateAssetError(f"{label} mismatch: {column}")


def _coverage(pair: list[int]) -> dict[str, object]:
    non_null, total = pair
    return {"non_null_count": non_null, "row_count": total, "coverage": non_null / total if total else 0.0}


def _require_columns(columns: set[str], required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - columns)
    if missing:
        raise DetailedMoneyflowCandidateAssetError(f"{label} are missing: " + ", ".join(missing))


def _require_directory(value: object, label: str) -> Path:
    path = Path(str(value)).expanduser().resolve()
    if not path.is_dir():
        raise DetailedMoneyflowCandidateAssetError(f"{label} is missing: {path}")
    return path


def _normalise_date(value: object) -> str:
    if isinstance(value, (date, datetime, np.datetime64, pd.Timestamp)):
        parsed = pd.Timestamp(value)
        if pd.isna(parsed):
            raise DetailedMoneyflowCandidateAssetError(f"invalid trade date: {value}")
        return parsed.strftime("%Y-%m-%d")
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise DetailedMoneyflowCandidateAssetError(f"invalid trade date: {value}")
    try:
        return pd.to_datetime(text, format="%Y%m%d", errors="raise").strftime("%Y-%m-%d")
    except (TypeError, ValueError) as error:
        raise DetailedMoneyflowCandidateAssetError(f"invalid trade date: {value}") from error


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DetailedMoneyflowCandidateAssetError(f"JSON object required: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
