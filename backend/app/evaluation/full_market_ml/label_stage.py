"""Contract-bound full-data label-audit stage."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .ranking_labels import add_cross_sectional_alpha_labels, audit_label_objective
from .research_contract import RankingResearchContract


INPUT_COLUMNS = (
    "trade_date",
    "symbol",
    "industry_l1",
    "listing_age_trade_days",
    "valid_ohlc",
    "is_st",
    "is_suspended",
    "median_amount_20d",
    "entry_tradeable",
    "horizon_available_10d",
    "entry_price",
    "exit_price",
    "mae_10d",
    "sl_before_tp_10d",
    "future_limit_down_count_10d",
)
OUTPUT_COLUMNS = (
    "trade_date",
    "symbol",
    "industry_l1",
    "net_return_after_cost_10d",
    "mae_10d",
    "sl_before_tp_10d",
    "future_limit_down_count_10d",
    "market_median_net_return_10d",
    "industry_median_net_return_10d",
    "market_excess_10d",
    "industry_excess_10d",
    "alpha_target_10d",
    "alpha_percentile_10d",
    "alpha_top10_10d",
    "alpha_relevance_grade_10d",
    "positive_net_return_10d",
    "severe_negative_10d",
    "industry_fallback_to_market_10d",
)


def build_ranking_label_input(rows: pd.DataFrame, contract: RankingResearchContract) -> pd.DataFrame:
    missing = sorted(set(INPUT_COLUMNS) - set(rows.columns))
    if missing:
        raise ValueError("label stage rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    entry = pd.to_numeric(result["entry_price"], errors="coerce")
    exit_price = pd.to_numeric(result["exit_price"], errors="coerce")
    result["net_return_after_cost_10d"] = (
        (exit_price * (1.0 - contract.slippage_per_side))
        / (entry * (1.0 + contract.slippage_per_side))
        * (1.0 - contract.commission_per_side) ** 2
        - 1.0
    )
    result.loc[~entry.gt(0) | ~exit_price.gt(0), "net_return_after_cost_10d"] = np.nan
    result["eligible_for_training"] = (
        pd.to_numeric(result["listing_age_trade_days"], errors="coerce").ge(contract.minimum_listing_sessions)
        & result["valid_ohlc"].eq(True)
        & ~result["is_st"].eq(True)
        & ~result["is_suspended"].eq(True)
        & pd.to_numeric(result["median_amount_20d"], errors="coerce").gt(0)
        & result["entry_tradeable"].eq(True)
        & result["horizon_available_10d"].eq(True)
        & result["net_return_after_cost_10d"].notna()
    )
    return result


def run_label_audit_stage(
    contract: RankingResearchContract,
    run_root: Path,
    asset_root: Path,
) -> dict[str, Any]:
    dataset_registry_sha256 = validate_dataset_registry(asset_root, contract)
    dataset_root = asset_root / "datasets" / contract.dataset_id / "artifacts" / "full-build" / "dataset-v3"
    input_shards = sorted(dataset_root.glob("shard=*/data.parquet"))
    if not input_shards:
        raise FileNotFoundError(f"no immutable dataset shards under {dataset_root}")
    progress_path = run_root / "stages" / "label-audit" / "progress.json"
    _write_progress(progress_path, "loading", 0, len(input_shards))
    frames = []
    for offset, path in enumerate(input_shards, start=1):
        schema = set(pq.ParquetFile(path).schema.names)
        missing = sorted(set(INPUT_COLUMNS) - schema)
        if missing:
            raise ValueError(f"dataset shard {path.parent.name} missing label columns: {', '.join(missing)}")
        frame = pq.read_table(path, columns=list(INPUT_COLUMNS)).to_pandas()
        frame["_source_shard"] = path.parent.name
        frames.append(frame)
        _write_progress(progress_path, "loading", offset, len(input_shards))
    _write_progress(progress_path, "labeling", len(input_shards), len(input_shards))
    prepared = build_ranking_label_input(pd.concat(frames, ignore_index=True), contract)
    labeled = add_cross_sectional_alpha_labels(prepared)
    report = audit_label_objective(labeled)
    report.update(
        {
            "contract_sha256": contract.sha256(),
            "dataset_id": contract.dataset_id,
            "dataset_registry_sha256": dataset_registry_sha256,
            "row_count": int(len(labeled)),
            "eligible_row_count": int(labeled["eligible_for_training"].sum()),
            "ineligible_row_count": int((~labeled["eligible_for_training"]).sum()),
        }
    )

    artifact_root = run_root / "artifacts" / "label-audit"
    final_labels = artifact_root / "labels"
    if final_labels.exists():
        raise FileExistsError(f"label artifact already exists: {final_labels}")
    artifact_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".labels-", dir=artifact_root))
    try:
        files = []
        eligible = labeled[labeled["eligible_for_training"]].copy()
        groups = eligible.groupby("_source_shard", sort=True)
        group_count = groups.ngroups
        _write_progress(progress_path, "writing", 0, group_count)
        for offset, (shard_name, shard) in enumerate(groups, start=1):
            path = temporary / str(shard_name) / "data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pandas(shard[list(OUTPUT_COLUMNS)], preserve_index=False)
            pq.write_table(table, path, compression="zstd")
            files.append(
                {
                    "path": str(path.relative_to(temporary)),
                    "row_count": int(len(shard)),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
            _write_progress(progress_path, "writing", offset, group_count)
        os.replace(temporary, final_labels)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    manifest_path = artifact_root / "label_manifest.json"
    report_path = artifact_root / "label_objective_report.json"
    _write_json_atomic(
        manifest_path,
        {
            "contract_sha256": contract.sha256(),
            "dataset_id": contract.dataset_id,
            "dataset_registry_sha256": dataset_registry_sha256,
            "compression": "zstd",
            "row_count": int(report["eligible_row_count"]),
            "files": files,
        },
    )
    _write_json_atomic(report_path, report)
    _write_progress(progress_path, "complete", len(files), len(files))
    return {
        "label_manifest": str(manifest_path),
        "label_report": str(report_path),
        "_status": {"research_design_valid": bool(report["passed"]), "model_gate_passed": False},
    }


def validate_dataset_registry(asset_root: Path, contract: RankingResearchContract) -> str:
    registry = (
        asset_root
        / "datasets"
        / contract.dataset_id
        / "artifacts"
        / "full-build"
        / "dataset_registry_v3.json"
    )
    if not registry.is_file():
        raise FileNotFoundError(f"dataset registry is unavailable: {registry}")
    observed = _sha256(registry)
    if contract.dataset_registry_sha256 and observed != contract.dataset_registry_sha256:
        raise ValueError(
            f"dataset registry hash does not match frozen contract: {observed}"
        )
    return observed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _write_progress(path: Path, step: str, completed: int, total: int) -> None:
    _write_json_atomic(
        path,
        {
            "stage": "label-audit",
            "step": step,
            "completed": int(completed),
            "total": int(total),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        },
    )
