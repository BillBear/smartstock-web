"""Fail-closed readiness checks for offline historical Top-10 evaluation.

This module checks whether local research artifacts can support a strict
historical comparison. It never fits a model, reads price data, or derives a
label, so it cannot turn a missing final holdout into apparent evidence.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pyarrow.parquet as pq

from app.evaluation.ml_recovery_acceptance import verify_recovery_inputs


TOP_K = 10
HORIZON_SESSIONS = 10
REQUIRED_TOP10_EVALUATION_COLUMNS = frozenset(
    {
        "trade_date",
        "symbol",
        "model_score",
        "baseline_score",
        "alpha_top10_10d",
        "net_return_after_cost_10d",
        "entry_tradeable",
        "horizon_available_10d",
        "path_ambiguous_10d",
    }
)
REQUIRED_DAILY_PORTFOLIO_COLUMNS = frozenset({"portfolio_mark_date", "daily_mark_to_market_return"})


def assess_historical_evaluation_readiness(
    *,
    development_split: Mapping[str, Any],
    future_holdout: Mapping[str, Any],
    candidate_screen: Mapping[str, Any],
    oof_columns: Collection[str],
) -> dict[str, Any]:
    """Return a research-only `ready` or `blocked` historical-evaluation report."""
    blocking_codes: list[str] = []
    fold_report = _assess_walk_forward_folds(development_split, blocking_codes)
    development_dates = set(fold_report["development_dates"])

    if not _candidate_is_qualified(candidate_screen):
        blocking_codes.append("candidate_not_development_qualified")

    holdout_dates = _normalized_dates(future_holdout.get("dates", ()))
    if (
        future_holdout.get("formal_evaluation_allowed") is not True
        or not holdout_dates
        or str(future_holdout.get("status", "")) != "ready_for_historical_evaluation"
    ):
        blocking_codes.append("final_historical_holdout_not_materialized")
    elif development_dates & set(holdout_dates):
        blocking_codes.append("final_historical_holdout_overlaps_development")
    elif development_dates and min(holdout_dates) <= max(development_dates):
        blocking_codes.append("final_historical_holdout_not_after_development")

    columns = {str(column) for column in oof_columns}
    missing_top10_columns = sorted(REQUIRED_TOP10_EVALUATION_COLUMNS - columns)
    if missing_top10_columns:
        blocking_codes.append("top10_execution_contract_incomplete")
    missing_daily_columns = sorted(REQUIRED_DAILY_PORTFOLIO_COLUMNS - columns)
    if missing_daily_columns:
        blocking_codes.append("daily_portfolio_path_not_materialized")

    return {
        "status": "ready" if not blocking_codes else "blocked",
        "blocking_codes": blocking_codes,
        "contract": {
            "top_k": TOP_K,
            "horizon_sessions": HORIZON_SESSIONS,
            "entry_model": "next_tradable_session_open",
            "net_return_field": "net_return_after_cost_10d",
            "baseline_score_column": "baseline_score",
            "candidate_score_column": "model_score",
            "required_development_fold_count": 5,
            "minimum_purge_and_embargo_sessions": HORIZON_SESSIONS,
            "required_candidate_development_support": "4_of_5_precision_at_10_and_ndcg_at_10",
            "max_drawdown_limit": "candidate_not_more_than_10_percent_worse_than_baseline",
            "production_integration_allowed": False,
        },
        "walk_forward": fold_report,
        "candidate": {
            "status": str(candidate_screen.get("status", "")),
            "candidate_freeze_allowed": bool(candidate_screen.get("candidate_freeze_allowed") is True),
        },
        "final_historical_holdout": {
            "status": str(future_holdout.get("status", "")),
            "formal_evaluation_allowed": bool(future_holdout.get("formal_evaluation_allowed") is True),
            "date_count": len(holdout_dates),
            "overlaps_development": bool(development_dates & set(holdout_dates)),
            "starts_after_development": bool(
                development_dates and holdout_dates and min(holdout_dates) > max(development_dates)
            ),
        },
        "oof_schema": {
            "missing_top10_execution_columns": missing_top10_columns,
            "missing_daily_portfolio_columns": missing_daily_columns,
        },
        "market_regime_reporting_available": "signal_market_regime" in columns,
        "research_only": True,
        "production_integration_allowed": False,
    }


def audit_historical_evaluation_readiness(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    panel_root: str | Path,
    candidate_run_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
) -> dict[str, Any]:
    """Bind local metadata and atomically publish a fail-closed audit report."""
    destination = Path(output_dir).expanduser().resolve()
    candidate_root = Path(candidate_run_root).expanduser().resolve()
    if "prospective-lockbox" in candidate_root.parts:
        raise ValueError("candidate run must not read from the prospective lockbox")
    if destination.exists():
        raise FileExistsError(f"historical evaluation output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"incomplete historical evaluation audit requires inspection: {temporary}")
    temporary.mkdir()
    try:
        _write_progress(temporary, "input-verify", status="running")
        inputs = verify_recovery_inputs(label_root, feature_asset_root, panel_root)
        label_path = Path(label_root).expanduser().resolve()
        split_payload = _read_json(label_path / "development_split_plan.json")
        candidate_screen = _read_json(candidate_root / "candidate_screen.json")
        oof_path = candidate_root / "oof_predictions.parquet"
        if not oof_path.is_file():
            raise FileNotFoundError(f"oof_predictions.parquet is missing: {oof_path}")
        oof_columns = tuple(pq.ParquetFile(oof_path).schema_arrow.names)

        _write_progress(temporary, "readiness-assess", status="running")
        readiness = assess_historical_evaluation_readiness(
            development_split=split_payload,
            future_holdout=_mapping_or_empty(split_payload.get("future_holdout")),
            candidate_screen=candidate_screen,
            oof_columns=oof_columns,
        )
        report = {
            **readiness,
            "audit_completed": True,
            "code_commit": str(code_commit),
            "input_manifest": dict(inputs["input_manifest"]),
            "candidate_run_root": str(candidate_root),
            "candidate_screen_status": str(candidate_screen.get("status", "")),
            "oof_schema_column_count": len(oof_columns),
            "prospective_lockbox_read": False,
            "research_only": True,
            "production_integration_allowed": False,
        }
        _write_json(temporary / "historical_evaluation_readiness.json", report)
        _write_progress(temporary, "complete", status="complete", audit_status=report["status"])
        os.replace(temporary, destination)
        return report
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _assess_walk_forward_folds(development_split: Mapping[str, Any], blocking_codes: list[str]) -> dict[str, Any]:
    development_dates = _normalized_dates(development_split.get("development_dates", ()))
    date_positions = {date: index for index, date in enumerate(development_dates)}
    raw_folds = development_split.get("walk_forward")
    if not isinstance(raw_folds, (list, tuple)) or len(raw_folds) != 5:
        blocking_codes.append("walk_forward_fold_count_invalid")
        return {"fold_count": 0 if not isinstance(raw_folds, (list, tuple)) else len(raw_folds), "development_dates": development_dates, "folds": []}

    folds: list[dict[str, Any]] = []
    insufficient_embargo = False
    invalid_chronology = False
    outside_development_dates = False
    for raw_fold in raw_folds:
        if not isinstance(raw_fold, Mapping):
            invalid_chronology = True
            continue
        training_dates = _normalized_dates(raw_fold.get("training_dates", ()))
        validation_dates = _normalized_dates(raw_fold.get("validation_dates", ()))
        train_end = training_dates[-1] if training_dates else None
        validation_start = validation_dates[0] if validation_dates else None
        if not train_end or not validation_start or train_end >= validation_start:
            invalid_chronology = True
            embargo_sessions = None
        elif train_end not in date_positions or validation_start not in date_positions:
            outside_development_dates = True
            embargo_sessions = None
        else:
            embargo_sessions = date_positions[validation_start] - date_positions[train_end] - 1
            if embargo_sessions < HORIZON_SESSIONS:
                insufficient_embargo = True
        folds.append(
            {
                "fold": int(raw_fold.get("fold", 0)),
                "train_end": train_end,
                "validation_start": validation_start,
                "purge_and_embargo_sessions": embargo_sessions,
            }
        )
    if invalid_chronology:
        blocking_codes.append("walk_forward_chronology_invalid")
    if outside_development_dates:
        blocking_codes.append("walk_forward_dates_outside_development")
    if insufficient_embargo:
        blocking_codes.append("walk_forward_embargo_insufficient")
    return {"fold_count": len(folds), "development_dates": development_dates, "folds": folds}


def _candidate_is_qualified(candidate_screen: Mapping[str, Any]) -> bool:
    return (
        str(candidate_screen.get("status", "")) == "development_candidate_for_future_holdout"
        and candidate_screen.get("candidate_freeze_allowed") is True
    )


def _normalized_dates(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result = sorted({str(value).strip() for value in values if str(value).strip()})
    return result


def _mapping_or_empty(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{path.name} is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return payload


def _write_progress(path: Path, stage: str, *, status: str, **details: Any) -> None:
    _write_json(
        path / "progress.json",
        {
            "stage": stage,
            "status": status,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True, default=_json_default)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")
