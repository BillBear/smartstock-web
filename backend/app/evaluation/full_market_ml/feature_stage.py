"""Contract-bound point-in-time feature evidence stage."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .feature_evidence import evaluate_feature_evidence
from .feature_contract import FeatureContract, FeatureContractError
from .interaction_features import build_interaction_features
from .market_industry_features import build_industry_state_features, build_market_state_features
from .research_contract import RankingResearchContract
from .splits import SplitPlan, WalkForwardFold


BASE_COLUMNS = (
    "trade_date",
    "symbol",
    "industry_l1",
    "total_mv",
    "amount_cny",
    "adjusted_return_1d",
    "adjusted_return_5d",
    "adjusted_return_20d",
    "adjusted_return_60d",
    "price_to_sma_20d",
    "price_to_sma_60d",
    "at_up_limit",
    "at_down_limit",
    "amount_ratio_5d",
    "turnover_rate",
    "turnover_rate_rank",
    "realized_volatility_20d",
    "adjusted_close_to_high",
    "atr_pct_14d",
    "amount_log_rank",
)
LABEL_COLUMNS = (
    "trade_date",
    "symbol",
    "alpha_target_10d",
    "alpha_relevance_grade_10d",
    "net_return_after_cost_10d",
    "severe_negative_10d",
    "mae_10d",
)


def run_feature_evidence_stage(
    contract: RankingResearchContract,
    run_root: Path,
    asset_root: Path,
) -> dict[str, Any]:
    dataset_root = asset_root / "datasets" / contract.dataset_id / "artifacts" / "full-build"
    shard_root = dataset_root / "dataset-v3"
    split_source = dataset_root / "split_plan_v3.json"
    label_root = run_root / "artifacts" / "label-audit"
    label_manifest_path = label_root / "label_manifest.json"
    _validate_label_artifacts(contract, label_manifest_path, label_root / "labels")
    source_split = json.loads(split_source.read_text(encoding="utf-8"))
    source_dev_dates = tuple(str(item) for item in source_split["development_dates"])

    feature_names = tuple(feature for _, block in contract.feature_blocks for feature in block)
    input_shards = sorted(shard_root.glob("shard=*/data.parquet"))
    label_shards = sorted((label_root / "labels").glob("shard=*/data.parquet"))
    if not input_shards or not label_shards:
        raise FileNotFoundError("feature stage requires immutable dataset and completed label shards")
    progress = run_root / "stages" / "feature-evidence" / "progress.json"

    _write_progress(progress, "loading-signal-rows", 0, len(input_shards))
    frames = []
    required = set(BASE_COLUMNS) | {name for name in feature_names if name in _all_schema_columns(input_shards[0])}
    for offset, path in enumerate(input_shards, start=1):
        available = _all_schema_columns(path)
        missing_base = sorted(set(BASE_COLUMNS) - available)
        if missing_base:
            raise ValueError(f"dataset shard {path.parent.name} missing feature bases: {', '.join(missing_base)}")
        columns = sorted(required & available)
        frame = pq.read_table(path, columns=columns).to_pandas()
        frame = frame.loc[frame["trade_date"].isin(source_dev_dates)].copy()
        frame["_source_shard"] = path.parent.name
        frames.append(frame)
        _write_progress(progress, "loading-signal-rows", offset, len(input_shards))
    signal_rows = pd.concat(frames, ignore_index=True)
    del frames

    _write_progress(progress, "deriving-point-in-time-features", 0, 1)
    feature_rows = build_registered_feature_matrix(signal_rows, feature_names)
    del signal_rows

    _write_progress(progress, "loading-labels", 0, len(label_shards))
    labels = []
    for offset, path in enumerate(label_shards, start=1):
        frame = pq.read_table(path, columns=list(LABEL_COLUMNS)).to_pandas()
        frame["_source_shard"] = path.parent.name
        labels.append(frame)
        _write_progress(progress, "loading-labels", offset, len(label_shards))
    label_rows = pd.concat(labels, ignore_index=True)
    del labels
    label_rows = label_rows.loc[label_rows["trade_date"].isin(source_dev_dates)].copy()
    matrix = feature_rows.merge(
        label_rows,
        on=["trade_date", "symbol", "_source_shard"],
        how="inner",
        validate="one_to_one",
    )
    matrix["eligible_for_training"] = True
    matrix = _add_context_buckets(matrix)
    del feature_rows, label_rows
    if matrix.empty:
        raise ValueError("feature stage produced no eligible development rows")

    split_plan = build_ranking_development_split(matrix, source_split, contract)
    _write_progress(progress, "evaluating-features", 0, len(feature_names))
    evidence_rows = matrix.loc[
        matrix["trade_date"].isin(split_plan.development_dates)
        & matrix["symbol"].isin(split_plan.A_dev_train_symbols)
    ].copy()
    evidence = evaluate_feature_evidence(evidence_rows, feature_names, split_plan)
    _write_progress(progress, "writing", 0, 1)

    artifact_root = run_root / "artifacts" / "feature-evidence"
    artifact_root.mkdir(parents=True, exist_ok=True)
    matrix_root = artifact_root / "matrix"
    if matrix_root.exists():
        raise FileExistsError(f"feature matrix already exists: {matrix_root}")
    temporary = Path(tempfile.mkdtemp(prefix=".matrix-", dir=artifact_root))
    files = []
    try:
        output_columns = [
            "trade_date",
            "symbol",
            "industry_l1",
            "total_mv",
            "amount_cny",
            "market_state",
            "size_bucket",
            "liquidity_bucket",
            *feature_names,
            *[name for name in LABEL_COLUMNS if name not in {"trade_date", "symbol"}],
        ]
        groups = matrix.groupby("_source_shard", sort=True)
        for shard_name, shard in groups:
            path = temporary / str(shard_name) / "data.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.Table.from_pandas(shard[output_columns], preserve_index=False),
                path,
                compression="zstd",
            )
            files.append(
                {
                    "path": str(path.relative_to(temporary)),
                    "row_count": int(len(shard)),
                    "bytes": int(path.stat().st_size),
                    "sha256": _sha256(path),
                }
            )
        os.replace(temporary, matrix_root)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    evidence_path = artifact_root / "feature_evidence.csv"
    evidence.to_csv(evidence_path, index=False)
    split_path = artifact_root / "development_split.json"
    manifest_path = artifact_root / "feature_matrix_manifest.json"
    report_path = artifact_root / "feature_evidence_report.json"
    _write_json(split_path, split_plan.to_dict())
    _write_json(
        manifest_path,
        {
            "contract_sha256": contract.sha256(),
            "split_sha256": split_plan.split_sha256,
            "feature_names": list(feature_names),
            "compression": "zstd",
            "row_count": int(len(matrix)),
            "files": files,
        },
    )
    summaries = evidence.loc[evidence["record_type"].eq("summary")]
    role_counts = {str(key): int(value) for key, value in summaries["role"].value_counts().items()}
    report = {
        "contract_sha256": contract.sha256(),
        "split_sha256": split_plan.split_sha256,
        "row_count": int(len(matrix)),
        "development_date_count": len(split_plan.development_dates),
        "training_symbol_count": len(split_plan.A_dev_train_symbols),
        "unseen_symbol_count": len(split_plan.C_dev_unseen_symbols),
        "feature_count": len(feature_names),
        "role_counts": role_counts,
        "alpha_candidates": sorted(summaries.loc[summaries["role"].eq("alpha_candidate"), "feature"].tolist()),
        "risk_only": sorted(summaries.loc[summaries["role"].eq("risk_only"), "feature"].tolist()),
        "passed": bool(role_counts.get("alpha_candidate", 0) > 0),
    }
    _write_json(report_path, report)
    _write_progress(progress, "complete", len(feature_names), len(feature_names))
    return {
        "feature_evidence": str(evidence_path),
        "feature_report": str(report_path),
        "feature_matrix_manifest": str(manifest_path),
        "development_split": str(split_path),
        "_status": {"research_design_valid": True, "model_gate_passed": False},
    }


def build_registered_feature_matrix(
    rows: pd.DataFrame,
    feature_names: tuple[str, ...],
    *,
    contract: FeatureContract | None = None,
) -> pd.DataFrame:
    """Derive only signal-time registered features; unavailable sources stay null."""
    if contract is not None:
        unregistered = sorted(set(feature_names) - set(contract.feature_names))
        if unregistered:
            raise FeatureContractError(
                "feature stage requested unregistered contract features: " + ", ".join(unregistered)
            )
    result = build_market_state_features(rows)
    result = build_industry_state_features(result)
    result = build_interaction_features(result)
    for feature in feature_names:
        if feature not in result:
            result[feature] = np.nan
        result[feature] = pd.to_numeric(result[feature], errors="coerce").astype("float32")
    breadth = pd.to_numeric(result["market_positive_breadth_1d"], errors="coerce")
    market_return = pd.to_numeric(result["market_cross_section_return_median_20d"], errors="coerce")
    result["market_state"] = np.select(
        [breadth.ge(0.55) & market_return.gt(0), breadth.le(0.45) | market_return.lt(-0.03)],
        ["attack", "defense"],
        default="balanced",
    )
    return result


def build_ranking_development_split(
    matrix: pd.DataFrame,
    source_split: dict[str, Any],
    contract: RankingResearchContract,
) -> SplitPlan:
    allowed_dates = set(str(item) for item in source_split["development_dates"])
    dates = tuple(sorted(set(matrix.loc[matrix["trade_date"].isin(allowed_dates), "trade_date"])))
    minimum_prefix = (
        contract.minimum_inner_fit_dates
        + contract.minimum_inner_early_stop_dates
        + contract.minimum_inner_selection_dates
        + contract.embargo_sessions
    )
    if len(dates) < minimum_prefix + contract.outer_folds * 20:
        raise ValueError("development dates cannot support five nested outer folds")
    validation_dates = dates[minimum_prefix:]
    partitions = tuple(tuple(part.tolist()) for part in np.array_split(np.asarray(validation_dates), contract.outer_folds))
    holdout = set(str(item) for item in source_split.get("stock_holdout_symbols", ()))
    all_symbols = set(matrix.loc[matrix["trade_date"].isin(dates), "symbol"].astype(str))
    unseen = tuple(sorted(all_symbols & holdout))
    training = tuple(sorted(all_symbols - set(unseen)))
    folds = []
    for index, validation in enumerate(partitions, start=1):
        start = dates.index(validation[0])
        train = dates[: start - contract.embargo_sessions]
        if len(train) < (
            contract.minimum_inner_fit_dates
            + contract.minimum_inner_early_stop_dates
            + contract.minimum_inner_selection_dates
        ):
            raise ValueError(f"outer fold {index} has insufficient nested training dates")
        folds.append(
            WalkForwardFold(
                fold=index,
                training_dates=train,
                validation_dates=validation,
                training_symbols=training,
                train_start=train[0],
                train_end=train[-1],
                validation_start=validation[0],
                validation_end=validation[-1],
            )
        )
    payload = {
        "dates": dates,
        "training": training,
        "unseen": unseen,
        "folds": [fold.to_dict() for fold in folds],
        "contract_sha256": contract.sha256(),
    }
    split_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return SplitPlan(
        development_dates=dates,
        final_dates=tuple(str(item) for item in source_split.get("final_dates", ())),
        stock_holdout_symbols=unseen,
        A_dev_train_symbols=training,
        B_final_train_symbols=training,
        C_dev_unseen_symbols=unseen,
        D_final_unseen_symbols=unseen,
        walk_forward=tuple(folds),
        stratum_counts_before=dict(source_split.get("stratum_counts_before", {})),
        stratum_counts_after=dict(source_split.get("stratum_counts_after", {})),
        split_sha256=split_sha,
    )


def _add_context_buckets(rows: pd.DataFrame) -> pd.DataFrame:
    result = rows.copy()
    for source, output in (("total_mv", "size_bucket"), ("amount_cny", "liquidity_bucket")):
        ranks = result.groupby("trade_date", sort=False)[source].rank(method="first", pct=True)
        result[output] = pd.cut(
            ranks,
            bins=[-np.inf, 1 / 3, 2 / 3, np.inf],
            labels=["low", "medium", "high"],
        ).astype("string")
    return result


def _validate_label_artifacts(contract: RankingResearchContract, manifest_path: Path, labels_root: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_sha256") != contract.sha256():
        raise ValueError("label manifest contract hash does not match feature stage")
    for item in manifest.get("files", []):
        path = labels_root / str(item["path"])
        if not path.is_file() or _sha256(path) != item.get("sha256"):
            raise ValueError(f"label shard changed: {path}")


def _all_schema_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema.names)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _write_progress(path: Path, step: str, completed: int, total: int) -> None:
    _write_json(
        path,
        {
            "stage": "feature-evidence",
            "step": step,
            "completed": int(completed),
            "total": int(total),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        },
    )
