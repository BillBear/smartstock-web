"""File-backed execution for development-only context feature evidence."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyarrow.parquet as pq

from .context_feature_audit import (
    CONTEXT_FEATURE_NAMES,
    CONTEXT_OUTCOME_COLUMNS,
    CONTEXT_SOURCE_COLUMNS,
    build_context_feature_audit,
)
from .feature_audit import FeatureAuditResult
from .splits import SplitPlan, WalkForwardFold
from .v3_feature_evidence import FeatureEvidenceError, _development_only_split, _load_eligible_feature_asset, _read_json


def run_context_feature_audit(
    *,
    source_dataset_root: str | Path,
    feature_asset_root: str | Path,
    output_root: str | Path,
    code_commit: str,
    smoke: bool = False,
) -> dict[str, Any]:
    """Create context-feature evidence without training a model or reading final dates."""
    source_root = Path(source_dataset_root).expanduser().resolve()
    asset_root = Path(feature_asset_root).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    manifest = _load_eligible_feature_asset(asset_root, source_root)
    split_payload = _read_json(source_root / "artifacts" / "full-build" / "split_plan_v2.json")
    split_plan = _development_only_split(split_payload)
    if smoke:
        split_plan = _smoke_split(split_plan)
    matrix_root = Path(str(manifest["matrix_path"])).expanduser().resolve()
    _prepare_output(destination)
    dates = _validation_dates(split_plan)
    _write_json(destination / "progress.json", _progress("running", "load-context-input", total_dates=len(dates)))
    try:
        rows = _load_validation_rows(matrix_root, dates, destination)
        _write_json(destination / "progress.json", _progress("running", "audit-context-features", row_count=len(rows)))
        result = build_context_feature_audit(rows, split_plan)
        _write_artifacts(destination, result.audit)
        report = _report(
            manifest=manifest,
            split_payload=split_payload,
            split_plan=split_plan,
            audit=result.audit,
            row_count=len(rows),
            code_commit=code_commit,
            smoke=smoke,
        )
        _write_json(destination / "input_summary.json", report["input_summary"])
        _write_json(destination / "context_feature_evidence.json", report)
        _write_json(destination / "progress.json", _progress("complete", "complete", row_count=len(rows), date_count=len(dates)))
        return report
    except BaseException as error:
        _write_json(
            destination / "progress.json",
            _progress(
                "aborted" if isinstance(error, KeyboardInterrupt) else "failed",
                "failed",
                error_type=type(error).__name__,
                error=str(error),
            ),
        )
        raise


def _smoke_split(split_plan: SplitPlan) -> SplitPlan:
    folds = tuple(
        WalkForwardFold(
            fold=fold.fold,
            training_dates=fold.training_dates,
            validation_dates=(fold.validation_dates[0],),
            training_symbols=fold.training_symbols,
            train_start=fold.train_start,
            train_end=fold.train_end,
            validation_start=fold.validation_dates[0],
            validation_end=fold.validation_dates[0],
        )
        for fold in split_plan.walk_forward
    )
    return SplitPlan(
        development_dates=split_plan.development_dates,
        final_dates=split_plan.final_dates,
        stock_holdout_symbols=split_plan.stock_holdout_symbols,
        A_dev_train_symbols=split_plan.A_dev_train_symbols,
        B_final_train_symbols=split_plan.B_final_train_symbols,
        C_dev_unseen_symbols=split_plan.C_dev_unseen_symbols,
        D_final_unseen_symbols=split_plan.D_final_unseen_symbols,
        walk_forward=folds,
        stratum_counts_before=split_plan.stratum_counts_before,
        stratum_counts_after=split_plan.stratum_counts_after,
        split_sha256=split_plan.split_sha256,
    )


def _validation_dates(split_plan: SplitPlan) -> tuple[str, ...]:
    dates = tuple(sorted({date for fold in split_plan.walk_forward for date in fold.validation_dates}))
    if not dates:
        raise FeatureEvidenceError("context feature audit has no registered walk-forward validation dates")
    if not set(dates).issubset(set(split_plan.development_dates)):
        raise FeatureEvidenceError("context feature audit validation dates escape the development period")
    return dates


def _load_validation_rows(matrix_root: Path, dates: tuple[str, ...], destination: Path) -> pd.DataFrame:
    columns = tuple(dict.fromkeys((*CONTEXT_SOURCE_COLUMNS, *CONTEXT_OUTCOME_COLUMNS)))
    frames = []
    for position, trade_date in enumerate(dates, start=1):
        path = matrix_root / f"trade_date={trade_date}" / "data.parquet"
        if not path.is_file():
            raise FeatureEvidenceError(f"feature matrix misses registered validation date: {trade_date}")
        available = set(pq.ParquetFile(path).schema_arrow.names)
        missing = sorted(set(columns) - available)
        if missing:
            raise FeatureEvidenceError(f"feature matrix {trade_date} misses context columns: " + ", ".join(missing))
        frames.append(pq.read_table(path, columns=list(columns)).to_pandas())
        _write_json(destination / "progress.json", _progress("running", "load-context-input", completed_dates=position, total_dates=len(dates), trade_date=trade_date))
    if not frames:
        raise FeatureEvidenceError("context feature audit has no input partitions")
    return pd.concat(frames, ignore_index=True)


def _write_artifacts(destination: Path, audit: FeatureAuditResult) -> None:
    audit.coverage.to_csv(destination / "context_feature_coverage.csv", index=False)
    audit.ic.to_csv(destination / "context_feature_ic.csv", index=False)
    audit.bucket_returns.to_csv(destination / "context_feature_bucket_returns.csv", index=False)
    audit.correlation.to_csv(destination / "context_feature_correlation.csv", index=False)
    audit.drift.to_csv(destination / "context_feature_drift.csv", index=False)
    audit.group_eligibility.to_csv(destination / "context_feature_group_eligibility.csv", index=False)


def _report(
    *,
    manifest: Mapping[str, Any],
    split_payload: Mapping[str, Any],
    split_plan: SplitPlan,
    audit: FeatureAuditResult,
    row_count: int,
    code_commit: str,
    smoke: bool,
) -> dict[str, Any]:
    statuses = _feature_statuses(audit)
    return {
        "status": "complete",
        "research_only": True,
        "model_selection_allowed": False,
        "production_integration_allowed": False,
        "final_holdout_used": False,
        "smoke": bool(smoke),
        "code_commit": str(code_commit),
        "source_dataset_id": str(manifest.get("source_dataset_id", "")),
        "source_dataset_sha256": str(manifest.get("source_dataset_sha256", "")),
        "feature_asset_manifest_sha256": str(manifest.get("sha256", "")),
        "feature_contract_sha256": str(manifest.get("feature_contract_sha256", "")),
        "split_sha256": str(split_payload.get("sha256", split_plan.split_sha256)),
        "feature_names": list(CONTEXT_FEATURE_NAMES),
        "feature_statuses": statuses,
        "input_summary": {
            "row_count": int(row_count),
            "validation_date_count": len(_validation_dates(split_plan)),
            "walk_forward_fold_count": len(split_plan.walk_forward),
            "source_columns": list(CONTEXT_SOURCE_COLUMNS),
            "outcome_columns": list(CONTEXT_OUTCOME_COLUMNS),
            "final_holdout_used": False,
        },
        "limitations": [
            "This is univariate development-period feature evidence, not a model result.",
            "Context aggregates use same-date valid OHLC rows and must not be interpreted as an executable strategy.",
            "No final future holdout exists for this research asset; this audit cannot authorize production integration.",
        ],
        "generated_at": _now(),
    }


def _feature_statuses(audit: FeatureAuditResult) -> list[dict[str, Any]]:
    rows = []
    for feature in CONTEXT_FEATURE_NAMES:
        coverage = pd.to_numeric(audit.coverage.loc[audit.coverage["feature"].eq(feature), "coverage"], errors="coerce")
        evidence = audit.ic.loc[
            audit.ic["feature"].eq(feature) & audit.ic["target"].eq("net_return_after_cost_10d")
        ].copy()
        if evidence.empty:
            status = "insufficient_evidence"
            selection = "not_audited_constant_or_missing"
            median_ic = None
            direction_consistency = None
            reason = "missing_or_constant_across_all_validation_rows"
        else:
            selection = str(evidence["selection"].iloc[0])
            median_ic = _finite_median(evidence["median_ic"])
            direction_consistency = _finite_median(evidence["direction_consistency"])
            minimum_coverage = float(coverage.min()) if not coverage.empty else 0.0
            date_count = int(pd.to_numeric(evidence["date_count"], errors="coerce").fillna(0).sum())
            if date_count == 0:
                status = "insufficient_evidence"
                reason = "constant_within_daily_cross_section"
            elif selection == "core_candidate" and minimum_coverage >= 0.95 and direction_consistency is not None and direction_consistency >= 0.8:
                status = "ready_for_later_oof"
                reason = "stable_development_univariate_evidence"
            elif selection == "exclude":
                status = "rejected"
                reason = "unstable_or_insufficient_daily_ic"
            else:
                status = "insufficient_evidence"
                reason = "does_not_meet_later_oof_screen"
        rows.append(
            {
                "feature": feature,
                "status": status,
                "reason": reason,
                "selection": selection,
                "minimum_fold_coverage": float(coverage.min()) if not coverage.empty else 0.0,
                "median_ic": median_ic,
                "direction_consistency": direction_consistency,
            }
        )
    return rows


def _finite_median(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else None


def _prepare_output(destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise FeatureEvidenceError(f"context feature audit output root must be empty: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=False)


def _progress(status: str, stage: str, **payload: Any) -> dict[str, Any]:
    return {"status": status, "stage": stage, "updated_at": _now(), **payload}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
