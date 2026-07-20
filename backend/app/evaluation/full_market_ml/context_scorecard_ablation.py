"""Exploratory, fold-local context-feature ablation for the fixed scorecard.

The feature definitions were chosen after a prior development-period audit.
This module therefore preserves a strict ``exploratory_post_selection_only``
status even when its fold-local diagnostics look positive.  It is not a model
selection or production-integration gate.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from .evaluator import (
    bootstrap_uplift,
    evaluate_ranking,
    simulate_daily_topk_portfolio,
    validate_identical_comparison_rows,
)
from .splits import FinalHoldoutAccessError, SplitPlan
from .train_only_scorecard import fit_scorecard_directions, score_with_directions
from .train_only_scorecard_oof import ScorecardOofError, _ALL_FEATURES, _REQUIRED_COLUMNS


BASELINE_SCORECARD = "scorecard_baseline_h1_h2_h3"
CANDIDATE_SCORECARD = "scorecard_candidate_h1_h2_h3_context"
MOMENTUM_REFERENCE = "baseline_momentum_60d"
CONTEXT_ABLATION_FEATURES = (
    "stock_excess_vs_industry_5d",
    "industry_limit_up_rate",
    "industry_limit_down_rate",
)
_COMPARATORS = (MOMENTUM_REFERENCE, BASELINE_SCORECARD, CANDIDATE_SCORECARD)


class ContextScorecardAblationError(ScorecardOofError):
    """Raised when the context ablation breaks its research contract."""


def run_context_scorecard_ablation_rows(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    *,
    bootstrap_iterations: int = 1000,
    direction_target_column: str = "net_return_after_cost_10d",
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """Compare a fixed scorecard to a three-feature context extension.

    The context schema is fixed, but each sign is fitted only from the current
    outer fold's A-quadrant fit rows.  A candidate may not silently omit one of
    the three registered context features; an incomplete candidate is inactive
    for that fold and is excluded from direct metrics.
    """
    data = _normalize_rows(rows, split_plan, direction_target_column=direction_target_column)
    known_symbols = set(split_plan.A_dev_train_symbols) | set(split_plan.C_dev_unseen_symbols)
    data = data.loc[
        data["symbol"].isin(known_symbols) & data["eligible_for_training_10d"].eq(True)
    ].copy()
    data = data.loc[pd.to_numeric(data["adjusted_return_60d"], errors="coerce").notna()].copy()
    if data.empty:
        raise ContextScorecardAblationError("context scorecard ablation has no label-eligible baseline rows")
    data["risk_eligible"] = True

    predictions: list[pd.DataFrame] = []
    fold_directions: list[dict[str, Any]] = []
    fold_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    fold_bootstrap: dict[str, dict[str, dict[str, Any]]] = {}
    fold_portfolios: dict[str, dict[str, dict[str, Any]]] = {}
    inactive_folds: list[dict[str, Any]] = []
    for fold in split_plan.walk_forward:
        fit = data.loc[
            data["trade_date"].isin(fold.training_dates) & data["symbol"].isin(fold.training_symbols)
        ].copy()
        validation = data.loc[data["trade_date"].isin(fold.validation_dates)].copy()
        if fit.empty or validation.empty:
            raise ContextScorecardAblationError(
                f"fold {fold.fold} has no fit or validation rows after fixed eligibility"
            )
        baseline_fit = fit_scorecard_directions(
            fit,
            feature_schema=_ALL_FEATURES,
            target_column=direction_target_column,
        )
        context_fit = fit_scorecard_directions(
            fit,
            feature_schema=CONTEXT_ABLATION_FEATURES,
            target_column=direction_target_column,
        )
        trial = validation.copy()
        trial["fold"] = int(fold.fold)
        trial[f"score__{MOMENTUM_REFERENCE}"] = pd.to_numeric(trial["adjusted_return_60d"], errors="coerce")
        trial[f"score__{BASELINE_SCORECARD}"] = score_with_directions(
            trial,
            directions=baseline_fit["directions"],
        )["score"]

        active_context_directions = {
            feature: int(context_fit["directions"][feature])
            for feature in CONTEXT_ABLATION_FEATURES
            if feature in context_fit["directions"]
        }
        candidate_active = len(active_context_directions) == len(CONTEXT_ABLATION_FEATURES)
        trial[f"score__{CANDIDATE_SCORECARD}"] = np.nan
        active_comparators = {MOMENTUM_REFERENCE, BASELINE_SCORECARD}
        candidate_status = "inactive_missing_fold_local_context_direction"
        if candidate_active:
            candidate_directions = {**baseline_fit["directions"], **active_context_directions}
            trial[f"score__{CANDIDATE_SCORECARD}"] = score_with_directions(
                trial,
                directions=candidate_directions,
            )["score"]
            active_comparators.add(CANDIDATE_SCORECARD)
            candidate_status = "active"
        else:
            inactive_folds.append(
                {
                    "fold": int(fold.fold),
                    "reason": "one_or_more_registered_context_features_lacked_a_fit_only_stable_direction",
                    "active_context_features": sorted(active_context_directions),
                    "missing_context_features": sorted(set(CONTEXT_ABLATION_FEATURES) - set(active_context_directions)),
                }
            )
        _validate_comparator_rows(trial, active_comparators)
        predictions.append(trial)
        fold_directions.append(
            {
                "fold": int(fold.fold),
                "fit_start": fold.train_start,
                "fit_end": fold.train_end,
                "validation_start": fold.validation_start,
                "validation_end": fold.validation_end,
                "direction_target_column": direction_target_column,
                "baseline_directions": baseline_fit["directions"],
                "baseline_direction_evidence": baseline_fit["direction_evidence"],
                "candidate_context_directions": active_context_directions,
                "candidate_context_direction_evidence": context_fit["direction_evidence"],
                "candidate_status": candidate_status,
                "active_comparators": sorted(active_comparators),
                "inactive_comparators": sorted(set(_COMPARATORS) - active_comparators),
            }
        )
        for quadrant, symbols in (
            ("A_development_seen", set(fold.training_symbols)),
            ("C_development_unseen", set(split_plan.C_dev_unseen_symbols)),
        ):
            subset = trial.loc[trial["symbol"].isin(symbols)].copy()
            if subset.empty:
                continue
            key = f"fold_{fold.fold}_{quadrant}"
            fold_metrics[key] = _evaluate_comparators(subset, active_comparators)
            fold_bootstrap[key] = _bootstrap_candidate_uplift(
                subset,
                active_comparators,
                iterations=bootstrap_iterations,
                seed_offset=int(fold.fold) * 100 + (0 if quadrant.startswith("A_") else 10),
            )
            fold_portfolios[key] = _portfolio_comparators(subset, active_comparators)
        if on_progress is not None:
            on_progress({"completed_folds": int(fold.fold), "current_fold": int(fold.fold)})

    output = pd.concat(predictions, ignore_index=True).sort_values(
        ["fold", "trade_date", "symbol"], kind="stable"
    ).reset_index(drop=True)
    return {
        "predictions": output,
        "fold_directions": fold_directions,
        "inactive_folds": inactive_folds,
        "fold_metrics": fold_metrics,
        "fold_bootstrap": fold_bootstrap,
        "fold_portfolios": fold_portfolios,
        "candidate_screen": _candidate_screen(fold_metrics, fold_bootstrap, fold_portfolios, inactive_folds),
        "input_summary": {
            "row_count": int(len(data)),
            "date_count": int(data["trade_date"].nunique()),
            "symbol_count": int(data["symbol"].nunique()),
            "direction_target_column": str(direction_target_column),
            "baseline_features": list(_ALL_FEATURES),
            "context_features": list(CONTEXT_ABLATION_FEATURES),
            "outer_test_aggregation_policy": "fold_local_metrics_only",
            "outer_test_windows_overlap": True,
            "final_holdout_used": False,
        },
    }


def _normalize_rows(rows: pd.DataFrame, split_plan: SplitPlan, *, direction_target_column: str) -> pd.DataFrame:
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    required = set(_REQUIRED_COLUMNS) | set(_ALL_FEATURES) | set(CONTEXT_ABLATION_FEATURES) | {direction_target_column}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ContextScorecardAblationError("context scorecard rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isna().any() or result["trade_date"].isin(split_plan.final_dates).any():
        raise FinalHoldoutAccessError("context scorecard ablation cannot read final holdout dates")
    if (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("context scorecard ablation cannot read dates outside the development plan")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise ContextScorecardAblationError("context scorecard rows contain duplicate trade_date and symbol keys")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _validate_comparator_rows(rows: pd.DataFrame, comparators: set[str]) -> None:
    if BASELINE_SCORECARD not in comparators or MOMENTUM_REFERENCE not in comparators:
        raise ContextScorecardAblationError("baseline comparators must remain active")
    prepared = {
        name: rows.assign(score=pd.to_numeric(rows[f"score__{name}"], errors="coerce"))
        for name in sorted(comparators)
    }
    if any(frame["score"].isna().any() for frame in prepared.values()):
        raise ContextScorecardAblationError("active ablation comparators have unequal score availability")
    validate_identical_comparison_rows(prepared)


def _evaluate_comparators(rows: pd.DataFrame, comparators: set[str]) -> dict[str, dict[str, Any]]:
    return {
        name: evaluate_ranking(rows.assign(score=rows[f"score__{name}"]))
        for name in sorted(comparators)
    }


def _bootstrap_candidate_uplift(
    rows: pd.DataFrame,
    comparators: set[str],
    *,
    iterations: int,
    seed_offset: int,
) -> dict[str, dict[str, Any]]:
    if CANDIDATE_SCORECARD not in comparators:
        return {}
    return {
        CANDIDATE_SCORECARD: {
            "status": "exploratory_post_selection_only",
            **bootstrap_uplift(
                rows.assign(
                    score=rows[f"score__{CANDIDATE_SCORECARD}"],
                    baseline_score=rows[f"score__{BASELINE_SCORECARD}"],
                ),
                baseline_score_col="baseline_score",
                iterations=max(1, int(iterations)),
                seed=3000 + int(seed_offset),
            ),
        }
    }


def _portfolio_comparators(rows: pd.DataFrame, comparators: set[str]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for name in sorted(comparators):
        try:
            results[name] = simulate_daily_topk_portfolio(rows.assign(score=rows[f"score__{name}"]))
        except ValueError as error:
            results[name] = {"status": "unavailable", "reason": str(error)}
    return results


def _candidate_screen(
    fold_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    fold_bootstrap: Mapping[str, Mapping[str, Mapping[str, Any]]],
    fold_portfolios: Mapping[str, Mapping[str, Mapping[str, Any]]],
    inactive_folds: list[Mapping[str, Any]],
) -> dict[str, Any]:
    a_keys = sorted(key for key in fold_metrics if key.endswith("_A_development_seen"))
    c_keys = sorted(key for key in fold_metrics if key.endswith("_C_development_unseen"))
    a_active = [key for key in a_keys if CANDIDATE_SCORECARD in fold_metrics[key]]
    c_active = [key for key in c_keys if CANDIDATE_SCORECARD in fold_metrics[key]]
    if len(a_active) != len(a_keys) or len(c_active) != len(c_keys):
        return {
            "status": "exploratory_inactive",
            "production_integration_allowed": False,
            "a_fold_count": len(a_keys),
            "a_active_fold_count": len(a_active),
            "c_fold_count": len(c_keys),
            "c_active_fold_count": len(c_active),
            "inactive_folds": list(inactive_folds),
            "reason": "candidate cannot omit a registered context feature when its fold-local direction is unstable",
        }
    a_passing = [
        key
        for key in a_active
        if _a_fold_passes(
            fold_metrics[key][CANDIDATE_SCORECARD],
            fold_metrics[key][BASELINE_SCORECARD],
            fold_bootstrap[key][CANDIDATE_SCORECARD],
            fold_portfolios[key][CANDIDATE_SCORECARD],
            fold_portfolios[key][BASELINE_SCORECARD],
        )
    ]
    c_non_collapsed = [
        key
        for key in c_active
        if float(fold_metrics[key][CANDIDATE_SCORECARD]["ndcg_at_10"])
        >= float(fold_metrics[key][BASELINE_SCORECARD]["ndcg_at_10"]) - 0.02
    ]
    required_a = max(1, int(np.ceil(len(a_active) * 0.8)))
    required_c = max(1, int(np.ceil(len(c_active) * 0.8)))
    diagnostic_support = len(a_passing) >= required_a and len(c_non_collapsed) >= required_c
    return {
        "status": "exploratory_post_selection_only",
        "production_integration_allowed": False,
        "diagnostic_support_observed": bool(diagnostic_support),
        "a_fold_count": len(a_active),
        "a_folds_passing_all_registered_checks": len(a_passing),
        "a_folds_required_for_diagnostic_support": required_a,
        "c_fold_count": len(c_active),
        "c_folds_without_ndcg_collapse": len(c_non_collapsed),
        "c_folds_required_for_diagnostic_support": required_c,
        "comparison_baseline": BASELINE_SCORECARD,
        "reason": (
            "The three context features were chosen by an earlier development-period audit. "
            "This direct comparison is exploratory post-selection research and cannot freeze or promote a candidate."
        ),
    }


def _a_fold_passes(
    candidate_metrics: Mapping[str, Any],
    baseline_metrics: Mapping[str, Any],
    candidate_bootstrap: Mapping[str, Any],
    candidate_portfolio: Mapping[str, Any],
    baseline_portfolio: Mapping[str, Any],
) -> bool:
    if candidate_portfolio.get("status") == "unavailable" or baseline_portfolio.get("status") == "unavailable":
        return False
    return bool(
        float(candidate_metrics["ndcg_at_10"]) >= float(baseline_metrics["ndcg_at_10"])
        and float(candidate_metrics["precision_at_5"]) >= float(baseline_metrics["precision_at_5"])
        and float(candidate_metrics["top_5_mean_return"]) >= float(baseline_metrics["top_5_mean_return"])
        and float(candidate_portfolio.get("maximum_drawdown", 0.0))
        >= float(baseline_portfolio.get("maximum_drawdown", 0.0))
        and float(candidate_bootstrap["precision_at_5_uplift_ci_low"]) > 0.0
    )
