"""Resumable V2 feature-asset materialization from an immutable raw panel.

The source full-market parquet may contain historical feature columns, but this
module deliberately treats them as untrusted.  It reads only raw/label columns
and rebuilds the registered feature contract from the signal-date panel.
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from app.services.ml_online_feature_provider import OnlineFeatureProvider

from .feature_contract import FeatureContract, build_full_market_feature_contract
from .features import ALL_FEATURE_NAMES, build_time_series_features, build_cross_section_features


FEATURE_ASSET_VERSION = "full_market_feature_asset_v2"
MINIMUM_ONLINE_PARITY_HISTORY_SESSIONS = 84
_RAW_REQUIRED = {
    "trade_date",
    "symbol",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "volume_shares",
    "amount_cny",
}
_RAW_FEATURE_INPUT_COLUMNS = _RAW_REQUIRED | {
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


class FeatureMaterializationError(ValueError):
    """Raised when a feature asset cannot be safely resumed or published."""


def materialize_feature_asset(
    *,
    source_dataset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
    shard_count: int = 16,
) -> dict[str, Any]:
    """Build a resumable, immutable V2 contract matrix from a certified panel."""
    if shard_count < 2:
        raise ValueError("feature materialization requires at least two symbol shards")
    source_root = Path(source_dataset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    source = _load_source(source_root)
    contract = build_full_market_feature_contract(
        moneyflow_coverage=float(source["quality"]["moneyflow_coverage"]),
        include_moneyflow=False,
    )
    run_contract = _run_contract(source, contract, code_commit, shard_count)
    _prepare_destination(destination, run_contract)
    _write_progress(destination, "data-verify", status="running")
    _append_stage_log(destination, "data-verify", "started")
    try:
        source_columns = _source_columns(source["parquet"], contract)
        sessions = _sessions(source["quality"])
        _validate_source(source, source_columns, sessions)
        _write_json(destination / "data_quality_report.json", _data_quality_report(source, source_columns, sessions))
        _append_stage_log(destination, "data-verify", "complete", sessions=len(sessions))

        input_root = _partition_source_by_symbol(
            source["parquet"],
            source_columns,
            destination,
            shard_count,
        )
        time_series_root = _materialize_time_series(
            input_root,
            destination,
            sessions,
            contract,
            shard_count,
        )
        matrix_root, coverage = _materialize_cross_section(
            time_series_root,
            destination,
            source_columns,
            sessions,
            contract,
            source["split"],
            shard_count,
        )
        parity = _verify_last_date_parity(
            source["parquet"],
            source_columns,
            sessions,
            matrix_root,
            contract,
        )
        files = _matrix_file_manifest(matrix_root)
        coverage_passed = bool(coverage["passed"])
        status = "complete" if coverage_passed else "blocked_core_coverage"
        manifest = {
            **run_contract,
            "status": status,
            "completed_at": _now(),
            "row_count": sum(int(item["row_count"]) for item in files),
            "trade_date_count": len(sessions),
            "matrix_path": str(matrix_root),
            "matrix_files": files,
            "coverage": coverage,
            "online_offline_parity": parity,
            "training_eligible": coverage_passed,
            "production_integration_allowed": False,
            "intermediate_paths": {
                "input_shards": str(input_root),
                "time_series": str(time_series_root),
            },
        }
        manifest["sha256"] = _payload_sha256(manifest)
        _write_json(destination / "feature_asset_manifest.json", manifest)
        _write_progress(destination, "complete", status=status, completed_dates=len(sessions), total_dates=len(sessions))
        _append_stage_log(destination, "complete", status, rows=manifest["row_count"])
        return manifest
    except Exception as error:
        _write_progress(
            destination,
            "failed",
            status="failed",
            error_type=type(error).__name__,
            error=str(error),
        )
        _append_stage_log(destination, "failed", type(error).__name__, error=str(error))
        raise


def _load_source(source_root: Path) -> dict[str, Any]:
    registry_path = source_root / "dataset_registry_v2.json"
    quality_path = source_root / "artifacts" / "full-build" / "quality_report.json"
    split_path = source_root / "artifacts" / "full-build" / "split_plan_v2.json"
    data_path = source_root / "artifacts" / "full-build" / "dataset.parquet"
    for path in (registry_path, quality_path, split_path, data_path):
        if not path.is_file():
            raise FileNotFoundError(f"immutable source input is missing: {path}")
    registry = _read_json(registry_path)
    quality = _read_json(quality_path)
    if registry.get("certification_status") != "certified_research_sample":
        raise FeatureMaterializationError("source dataset is not a certified research sample")
    if quality.get("ready") is not True:
        raise FeatureMaterializationError("source data quality report is not ready")
    return {
        "root": source_root,
        "registry": registry,
        "quality": quality,
        "split": _read_json(split_path),
        "data_path": data_path,
        "parquet": pq.ParquetFile(data_path),
    }


def _run_contract(source: Mapping[str, Any], contract: FeatureContract, code_commit: str, shard_count: int) -> dict[str, Any]:
    source_sha = _sha256_file(source["data_path"])
    expected_sha = str(source["registry"].get("source_hashes", {}).get("dataset", ""))
    if source_sha != expected_sha:
        raise FeatureMaterializationError("source dataset SHA256 does not match its immutable registry")
    return {
        "feature_asset_version": FEATURE_ASSET_VERSION,
        "source_dataset_id": str(source["registry"]["dataset_id"]),
        "source_dataset_sha256": source_sha,
        "source_registry_sha256": str(source["registry"]["sha256"]),
        "feature_contract": contract.to_dict(),
        "feature_contract_sha256": contract.sha256(),
        "code_commit": str(code_commit),
        "shard_count": int(shard_count),
        "moneyflow_coverage": float(source["quality"]["moneyflow_coverage"]),
        "moneyflow_included": False,
        "formal_future_holdout_status": str(source["registry"].get("formal_future_holdout_status", "unknown")),
        "production_integration_allowed": False,
    }


def _prepare_destination(destination: Path, run_contract: Mapping[str, Any]) -> None:
    contract_path = destination / "materialization_contract.json"
    if destination.exists():
        if not contract_path.is_file():
            raise FeatureMaterializationError(f"output root exists without a materialization contract: {destination}")
        existing = _read_json(contract_path)
        if existing != dict(run_contract):
            raise FeatureMaterializationError("existing output root belongs to a different source, contract, code, or shard plan")
        return
    destination.mkdir(parents=True, exist_ok=False)
    _write_json(contract_path, dict(run_contract))


def _source_columns(parquet: pq.ParquetFile, contract: FeatureContract) -> tuple[str, ...]:
    available = tuple(parquet.schema_arrow.names)
    missing = sorted(_RAW_REQUIRED - set(available))
    if missing:
        raise FeatureMaterializationError("source parquet misses raw inputs: " + ", ".join(missing))
    # Existing V1 feature values are intentionally excluded.  Labels, execution
    # outcomes and raw source fields remain as auditable pass-through columns.
    stale_features = set(ALL_FEATURE_NAMES) | set(contract.feature_names)
    return tuple(
        name
        for name in available
        if name in _RAW_FEATURE_INPUT_COLUMNS or name not in stale_features
    )


def _sessions(quality: Mapping[str, Any]) -> tuple[str, ...]:
    values = tuple(sorted({str(value) for value in quality.get("observed_trade_dates", ())}))
    if len(values) < MINIMUM_ONLINE_PARITY_HISTORY_SESSIONS:
        raise FeatureMaterializationError("source panel has insufficient sessions for V2 feature parity")
    return values


def _validate_source(source: Mapping[str, Any], source_columns: Iterable[str], sessions: tuple[str, ...]) -> None:
    parquet = source["parquet"]
    if parquet.metadata.num_rows != int(source["registry"]["row_count"]):
        raise FeatureMaterializationError("source registry row count does not match parquet metadata")
    if len(sessions) != int(source["registry"]["trade_date_count"]):
        raise FeatureMaterializationError("source registry trade-date count does not match quality report")
    if "trade_date" not in source_columns or "symbol" not in source_columns:
        raise FeatureMaterializationError("source pass-through schema lacks trade_date or symbol")


def _data_quality_report(source: Mapping[str, Any], source_columns: Iterable[str], sessions: tuple[str, ...]) -> dict[str, Any]:
    return {
        "status": "ready_for_v2_feature_materialization",
        "source_dataset_id": source["registry"]["dataset_id"],
        "source_row_count": int(source["parquet"].metadata.num_rows),
        "source_trade_date_count": len(sessions),
        "source_start": sessions[0],
        "source_end": sessions[-1],
        "source_pass_through_column_count": len(tuple(source_columns)),
        "moneyflow_coverage": float(source["quality"]["moneyflow_coverage"]),
        "moneyflow_status": "disabled_below_95pct_observed_coverage",
        "old_feature_values_used_as_input": False,
        "production_integration_allowed": False,
    }


def _partition_source_by_symbol(
    parquet: pq.ParquetFile,
    columns: tuple[str, ...],
    destination: Path,
    shard_count: int,
) -> Path:
    stage = destination / "stages" / "input-shards"
    success = stage / "_SUCCESS.json"
    if success.is_file():
        return stage
    temporary = stage.with_name(".input-shards.tmp")
    if temporary.exists():
        raise FeatureMaterializationError(f"incomplete input-shard temporary directory requires inspection: {temporary}")
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for row_group in range(parquet.num_row_groups):
            frame = parquet.read_row_group(row_group, columns=list(columns)).to_pandas()
            frame["symbol"] = frame["symbol"].astype("string").str.split(".", regex=False).str[0].str.zfill(6)
            frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            # The certified source can be emitted by upstream hash shards, so
            # row-group order is not a symbol-order contract. Every occurrence
            # of a symbol maps to the same deterministic output shard; that
            # shard is sorted once before time-series features are calculated.
            _write_input_parts(frame, temporary, row_group, shard_count)
            _write_progress(destination, "input-shards", status="running", completed_row_groups=row_group + 1, total_row_groups=parquet.num_row_groups)
        _write_json(temporary / "_SUCCESS.json", {"row_groups": parquet.num_row_groups, "completed_at": _now()})
        stage.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, stage)
        _append_stage_log(destination, "input-shards", "complete")
        return stage
    except Exception:
        raise


def _write_input_parts(frame: pd.DataFrame, root: Path, part_number: int, shard_count: int) -> None:
    if frame.empty:
        return
    shard_ids = frame["symbol"].map(lambda value: _symbol_shard(str(value), shard_count))
    for shard in sorted(shard_ids.unique()):
        selected = frame.loc[shard_ids.eq(shard)].copy()
        path = root / f"shard={shard:03d}" / f"part={part_number:03d}.parquet"
        _write_parquet_atomic(selected, path)


def _materialize_time_series(
    input_root: Path,
    destination: Path,
    sessions: tuple[str, ...],
    contract: FeatureContract,
    shard_count: int,
) -> Path:
    stage = destination / "stages" / "time-series"
    stage.mkdir(parents=True, exist_ok=True)
    for shard in range(shard_count):
        output = stage / f"shard={shard:03d}"
        success = output / "_SUCCESS.json"
        if success.is_file():
            continue
        source_parts = sorted((input_root / f"shard={shard:03d}").glob("part=*.parquet"))
        if not source_parts:
            raise FeatureMaterializationError(f"symbol shard has no source rows: {shard}")
        temporary = output.with_name(output.name + ".tmp")
        if temporary.exists():
            raise FeatureMaterializationError(f"incomplete time-series temporary directory requires inspection: {temporary}")
        frame = pd.concat((pq.read_table(path).to_pandas() for path in source_parts), ignore_index=True)
        featured = build_time_series_features(
            None,
            frame,
            include_moneyflow=False,
            market_sessions=sessions,
        )
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            for trade_date, rows in featured.groupby("trade_date", sort=True):
                _write_parquet_atomic(rows, temporary / f"trade_date={trade_date}" / "data.parquet")
            _write_json(temporary / "_SUCCESS.json", {"row_count": int(len(featured)), "completed_at": _now()})
            os.replace(temporary, output)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        _write_progress(destination, "time-series", status="running", completed_shards=shard + 1, total_shards=shard_count)
        _append_stage_log(destination, "time-series", "shard-complete", shard=shard, rows=int(len(featured)))
    _append_stage_log(destination, "time-series", "complete", shards=shard_count)
    return stage


def _materialize_cross_section(
    time_series_root: Path,
    destination: Path,
    source_columns: tuple[str, ...],
    sessions: tuple[str, ...],
    contract: FeatureContract,
    split: Mapping[str, Any],
    shard_count: int,
) -> tuple[Path, dict[str, Any]]:
    stage = destination / "matrix"
    stage.mkdir(parents=True, exist_ok=True)
    counts, fold_dates = _coverage_counts(contract, split)
    for index, trade_date in enumerate(sessions, start=1):
        output = stage / f"trade_date={trade_date}" / "data.parquet"
        if output.is_file():
            _add_coverage_from_file(output, contract, counts, fold_dates)
            continue
        rows = []
        for shard in range(shard_count):
            path = time_series_root / f"shard={shard:03d}" / f"trade_date={trade_date}" / "data.parquet"
            if path.is_file():
                rows.append(pq.read_table(path).to_pandas())
        if not rows:
            raise FeatureMaterializationError(f"no time-series rows for market session {trade_date}")
        market = pd.concat(rows, ignore_index=True)
        featured = build_cross_section_features(None, {"market": market}, include_moneyflow=False)["market"]
        output_columns = list(dict.fromkeys([*source_columns, *contract.feature_names]))
        missing = sorted(set(output_columns) - set(featured.columns))
        if missing:
            raise FeatureMaterializationError("V2 matrix misses expected columns: " + ", ".join(missing))
        _write_parquet_atomic(featured.loc[:, output_columns], output)
        _add_coverage(featured, contract, counts, fold_dates)
        _write_progress(destination, "cross-section", status="running", completed_dates=index, total_dates=len(sessions))
        _append_stage_log(destination, "cross-section", "date-complete", trade_date=trade_date, rows=int(len(featured)))
    coverage = _coverage_report(contract, counts)
    _write_json(destination / "coverage_report.json", coverage)
    _append_stage_log(destination, "cross-section", "complete", passed=coverage["passed"])
    return stage, coverage


def _coverage_counts(
    contract: FeatureContract,
    split: Mapping[str, Any],
) -> tuple[dict[str, dict[str, list[int]]], dict[str, set[str]]]:
    fold_dates = {
        f"fold-{item['fold']}": {str(value) for value in item.get("test_dates", ())}
        for item in split.get("outer_folds", ())
    }
    counts = {
        f"fold-{item['fold']}": {feature: [0, 0] for feature in contract.required_feature_names}
        for item in split.get("outer_folds", ())
    }
    return counts, fold_dates


def _add_coverage(
    frame: pd.DataFrame,
    contract: FeatureContract,
    counts: dict[str, dict[str, list[int]]],
    fold_dates: Mapping[str, set[str]],
) -> None:
    if not counts:
        return
    trade_date = str(frame["trade_date"].iloc[0])
    for fold, feature_counts in counts.items():
        if trade_date not in fold_dates.get(fold, set()):
            continue
        for feature, record in feature_counts.items():
            values = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=float, copy=False)
            record[0] += int(np.isfinite(values).sum())
            record[1] += int(len(values))


def _add_coverage_from_file(
    path: Path,
    contract: FeatureContract,
    counts: dict[str, dict[str, list[int]]],
    fold_dates: Mapping[str, set[str]],
) -> None:
    if not counts:
        return
    frame = pq.read_table(path, columns=["trade_date", *contract.required_feature_names]).to_pandas()
    _add_coverage(frame, contract, counts, fold_dates)


def _coverage_report(contract: FeatureContract, counts: dict[str, dict[str, list[int]]]) -> dict[str, Any]:
    coverage = {
        fold: {feature: finite / total if total else 0.0 for feature, (finite, total) in values.items()}
        for fold, values in counts.items()
    }
    failures = [
        f"{fold}:{feature}={value:.4f}"
        for fold, features in coverage.items()
        for feature, value in features.items()
        if value < contract.minimum_fold_coverage
    ]
    return {
        "minimum_required_coverage": contract.minimum_fold_coverage,
        "coverage_by_outer_test_fold": coverage,
        "passed": not failures,
        "failures": failures,
    }


def _verify_last_date_parity(
    parquet: pq.ParquetFile,
    source_columns: tuple[str, ...],
    sessions: tuple[str, ...],
    matrix_root: Path,
    contract: FeatureContract,
) -> dict[str, Any]:
    as_of_date = sessions[-1]
    history = set(sessions[-MINIMUM_ONLINE_PARITY_HISTORY_SESSIONS:])
    rows = []
    for batch in parquet.iter_batches(batch_size=65_536, columns=list(source_columns)):
        frame = batch.to_pandas()
        selected = frame.loc[frame["trade_date"].astype(str).isin(history)]
        if not selected.empty:
            rows.append(selected)
    online_input = pd.concat(rows, ignore_index=True)
    source_as_of_dates = {source: as_of_date for source in contract.registered_sources}
    source_qualities = {source: "valid-with-rows" for source in contract.registered_sources}
    online = OnlineFeatureProvider(contract).build_features_as_of(
        online_input,
        as_of_date=as_of_date,
        source_as_of_dates=source_as_of_dates,
        source_qualities=source_qualities,
    ).sort_values("symbol").reset_index(drop=True)
    offline = pq.read_table(matrix_root / f"trade_date={as_of_date}" / "data.parquet", columns=["trade_date", "symbol", *contract.feature_names]).to_pandas()
    offline = offline.sort_values("symbol").reset_index(drop=True)
    if online[["trade_date", "symbol"]].to_dict("records") != offline[["trade_date", "symbol"]].to_dict("records"):
        raise FeatureMaterializationError("latest V2 online/offline parity identity rows differ")
    np.testing.assert_allclose(
        online[list(contract.feature_names)].to_numpy(dtype=float),
        offline[list(contract.feature_names)].to_numpy(dtype=float),
        rtol=0.0,
        atol=contract.parity_tolerance,
        equal_nan=True,
    )
    return {
        "passed": True,
        "as_of_date": as_of_date,
        "history_sessions": MINIMUM_ONLINE_PARITY_HISTORY_SESSIONS,
        "symbol_count": int(len(online)),
        "tolerance": contract.parity_tolerance,
    }


def _matrix_file_manifest(matrix_root: Path) -> list[dict[str, Any]]:
    files = []
    for path in sorted(matrix_root.glob("trade_date=*/data.parquet")):
        table = pq.ParquetFile(path)
        files.append(
            {
                "path": str(path.relative_to(matrix_root.parent)),
                "trade_date": path.parent.name.removeprefix("trade_date="),
                "row_count": int(table.metadata.num_rows),
                "bytes": int(path.stat().st_size),
                "sha256": _sha256_file(path),
            }
        )
    if not files:
        raise FeatureMaterializationError("feature matrix has no published date partitions")
    return files


def _symbol_shard(symbol: str, shard_count: int) -> int:
    return int(hashlib.sha256(symbol.encode("ascii", "ignore")).hexdigest()[:8], 16) % shard_count


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".parquet", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_progress(destination: Path, stage: str, *, status: str, **details: Any) -> None:
    _write_json(
        destination / "progress.json",
        {
            "status": status,
            "stage": stage,
            "updated_at": _now(),
            "peak_rss_bytes": _peak_rss_bytes(),
            **details,
        },
    )


def _append_stage_log(destination: Path, stage: str, event: str, **details: Any) -> None:
    path = destination / "stage.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": _now(), "stage": stage, "event": event, **details}, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
