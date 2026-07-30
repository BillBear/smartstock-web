"""Fail-closed readiness checks for offline historical Top-10 evaluation.

This module checks whether local research artifacts can support a strict
historical comparison. It never fits a model, reads price data, or derives a
label, so it cannot turn a missing final holdout into apparent evidence.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any


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
