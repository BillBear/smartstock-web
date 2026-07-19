"""Market-regime-conditioned, development-only OOF scorecard research."""
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
from .train_only_scorecard_oof import (
    PRE_REGISTERED_COMPARATORS,
    PRE_REGISTERED_FEATURE_GROUPS,
    ScorecardOofError,
    _ALL_FEATURES,
    _REQUIRED_COLUMNS,
)


MARKET_REGIMES = ("trend_up", "mixed", "trend_down")
PRIMARY_BASELINE = "baseline_momentum_60d"
INVERSE_DIAGNOSTIC = "baseline_inverse_60d_diagnostic"
DEFAULT_MINIMUM_DAILY_IC_COUNT = 20
DEFAULT_MINIMUM_VALIDATION_DATES = 5


class RegimeScorecardOofError(ScorecardOofError):
    """Raised when a state-conditioned OOF run violates its research contract."""


def run_regime_conditioned_scorecard_oof_rows(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    *,
    bootstrap_iterations: int = 1000,
    minimum_daily_ic_count: int = DEFAULT_MINIMUM_DAILY_IC_COUNT,
    minimum_validation_dates: int = DEFAULT_MINIMUM_VALIDATION_DATES,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """Evaluate pre-registered scorecards within point-in-time market regimes.

    Each direction is fitted only on the current outer fold's training dates,
    training symbols, and matching market regime. Validation windows overlap,
    therefore every output remains fold-local and is never pooled.
    """
    minimum_daily_ic_count = _positive_int(minimum_daily_ic_count, "minimum_daily_ic_count")
    minimum_validation_dates = _positive_int(minimum_validation_dates, "minimum_validation_dates")
    data = _normalize_rows(rows, split_plan)
    all_symbols = set(split_plan.A_dev_train_symbols) | set(split_plan.C_dev_unseen_symbols)
    data = data.loc[
        data["symbol"].isin(all_symbols)
        & data["eligible_for_training_10d"].eq(True)
        & data["regime_history_complete"].eq(True)
        & data["market_regime"].isin(MARKET_REGIMES)
    ].copy()
    data = data.loc[pd.to_numeric(data["adjusted_return_60d"], errors="coerce").notna()].copy()
    if data.empty:
        raise RegimeScorecardOofError("regime scorecard has no eligible point-in-time regime rows")
    data["risk_eligible"] = True

    predictions: list[pd.DataFrame] = []
    directions: list[dict[str, Any]] = []
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    bootstrap: dict[str, dict[str, dict[str, Any]]] = {}
    portfolios: dict[str, dict[str, dict[str, Any]]] = {}
    skipped: list[dict[str, Any]] = []
    for fold in split_plan.walk_forward:
        for regime_index, regime in enumerate(MARKET_REGIMES):
            fit = data.loc[
                data["trade_date"].isin(fold.training_dates)
                & data["symbol"].isin(fold.training_symbols)
                & data["market_regime"].eq(regime)
            ].copy()
            validation = data.loc[
                data["trade_date"].isin(fold.validation_dates) & data["market_regime"].eq(regime)
            ].copy()
            validation_date_count = int(validation["trade_date"].nunique())
            context = {
                "fold": int(fold.fold),
                "market_regime": regime,
                "fit_start": fold.train_start,
                "fit_end": fold.train_end,
                "validation_start": fold.validation_start,
                "validation_end": fold.validation_end,
                "fit_row_count": int(len(fit)),
                "fit_date_count": int(fit["trade_date"].nunique()),
                "validation_row_count": int(len(validation)),
                "validation_date_count": validation_date_count,
            }
            if fit.empty or validation_date_count < minimum_validation_dates:
                skipped.append(
                    {
                        **context,
                        "status": "insufficient_regime_rows",
                        "reason": "matching regime lacks fit rows or the registered minimum validation dates",
                    }
                )
                continue
            fitted = fit_scorecard_directions(
                fit,
                feature_schema=_ALL_FEATURES,
                minimum_daily_ic_count=minimum_daily_ic_count,
            )
            trial, active_comparators = _score_trial(validation, fitted["directions"], fold=int(fold.fold))
            _validate_comparator_rows(trial, active_comparators)
            predictions.append(trial)
            directions.append(
                {
                    **context,
                    "status": "evaluated",
                    "minimum_daily_ic_count": minimum_daily_ic_count,
                    "directions": fitted["directions"],
                    "direction_evidence": fitted["direction_evidence"],
                    "active_comparators": sorted(active_comparators),
                    "inactive_comparators": sorted(set(PRE_REGISTERED_COMPARATORS) - active_comparators),
                }
            )
            for quadrant, symbols in (
                ("A_development_seen", set(fold.training_symbols)),
                ("C_development_unseen", set(split_plan.C_dev_unseen_symbols)),
            ):
                subset = trial.loc[trial["symbol"].isin(symbols)].copy()
                if subset.empty:
                    continue
                key = f"fold_{fold.fold}_{regime}_{quadrant}"
                metrics[key] = _evaluate_comparators(subset, active_comparators)
                bootstrap[key] = _bootstrap_comparators(
                    subset,
                    active_comparators,
                    iterations=bootstrap_iterations,
                    seed_offset=int(fold.fold) * 100 + regime_index * 10,
                )
                portfolios[key] = _portfolio_comparators(subset, active_comparators)
        if on_progress is not None:
            on_progress({"completed_folds": int(fold.fold), "current_fold": int(fold.fold)})

    if not predictions:
        raise RegimeScorecardOofError("no regime/fold combination met the registered validation-date minimum")
    output = pd.concat(predictions, ignore_index=True).sort_values(
        ["fold", "market_regime", "trade_date", "symbol"], kind="stable"
    ).reset_index(drop=True)
    return {
        "predictions": output,
        "fold_directions": directions,
        "skipped_regime_folds": skipped,
        "fold_metrics": metrics,
        "fold_bootstrap": bootstrap,
        "fold_portfolios": portfolios,
        "candidate_screen": _candidate_screen(metrics, bootstrap, portfolios),
        "input_summary": {
            "row_count": int(len(data)),
            "date_count": int(data["trade_date"].nunique()),
            "symbol_count": int(data["symbol"].nunique()),
            "regime_date_counts": {
                regime: int(data.loc[data["market_regime"].eq(regime), "trade_date"].nunique())
                for regime in MARKET_REGIMES
            },
            "minimum_daily_ic_count": minimum_daily_ic_count,
            "minimum_validation_dates": minimum_validation_dates,
            "outer_test_aggregation_policy": "fold_local_metrics_only",
            "outer_test_windows_overlap": True,
        },
    }


def _normalize_rows(rows: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    required = set(_REQUIRED_COLUMNS) | set(_ALL_FEATURES) | {"market_regime", "regime_history_complete"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise RegimeScorecardOofError("regime scorecard rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)
    if result["trade_date"].isna().any() or result["trade_date"].isin(split_plan.final_dates).any():
        raise FinalHoldoutAccessError("regime scorecard OOF cannot read final holdout dates")
    if (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("regime scorecard OOF cannot read dates outside the development plan")
    if result.duplicated(["trade_date", "symbol"]).any():
        raise RegimeScorecardOofError("regime scorecard rows contain duplicate trade_date and symbol keys")
    state_counts = result.groupby("trade_date", sort=True)["market_regime"].nunique(dropna=False)
    if state_counts.gt(1).any():
        raise RegimeScorecardOofError("regime scorecard has conflicting market regimes within a trade date")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _score_trial(
    validation: pd.DataFrame,
    directions: Mapping[str, int],
    *,
    fold: int,
) -> tuple[pd.DataFrame, set[str]]:
    trial = validation.copy()
    trial["fold"] = int(fold)
    trial["score__baseline_momentum_60d"] = pd.to_numeric(trial["adjusted_return_60d"], errors="coerce")
    trial["score__baseline_inverse_60d_diagnostic"] = -trial["score__baseline_momentum_60d"]
    active = {PRIMARY_BASELINE, INVERSE_DIAGNOSTIC}
    for group, features in PRE_REGISTERED_FEATURE_GROUPS.items():
        name = f"scorecard_{group}"
        group_directions = {feature: int(directions[feature]) for feature in features if feature in directions}
        trial[f"score__{name}"] = np.nan
        if group_directions:
            trial[f"score__{name}"] = score_with_directions(trial, directions=group_directions)["score"]
            active.add(name)
    combined = "scorecard_combined_h1_h2_h3"
    trial[f"score__{combined}"] = np.nan
    if directions:
        trial[f"score__{combined}"] = score_with_directions(trial, directions=dict(directions))["score"]
        active.add(combined)
    return trial, active


def _validate_comparator_rows(rows: pd.DataFrame, comparators: set[str]) -> None:
    if PRIMARY_BASELINE not in comparators:
        raise RegimeScorecardOofError("primary momentum baseline must remain active")
    prepared = {
        name: rows.assign(score=pd.to_numeric(rows[f"score__{name}"], errors="coerce"))
        for name in sorted(comparators)
    }
    if any(frame["score"].isna().any() for frame in prepared.values()):
        raise RegimeScorecardOofError("registered comparators have unequal score availability")
    validate_identical_comparison_rows(prepared)


def _evaluate_comparators(rows: pd.DataFrame, comparators: set[str]) -> dict[str, dict[str, Any]]:
    return {name: evaluate_ranking(rows.assign(score=rows[f"score__{name}"])) for name in sorted(comparators)}


def _bootstrap_comparators(
    rows: pd.DataFrame,
    comparators: set[str],
    *,
    iterations: int,
    seed_offset: int,
) -> dict[str, dict[str, Any]]:
    baseline = "score__baseline_momentum_60d"
    return {
        name: {
            "status": "diagnostic_only" if name == INVERSE_DIAGNOSTIC else "candidate_comparator",
            **bootstrap_uplift(
                rows.assign(score=rows[f"score__{name}"], baseline_score=rows[baseline]),
                baseline_score_col="baseline_score",
                iterations=iterations,
                seed=1000 + seed_offset + index,
            ),
        }
        for index, name in enumerate(sorted(comparators))
        if name != PRIMARY_BASELINE
    }


def _portfolio_comparators(rows: pd.DataFrame, comparators: set[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in sorted(comparators):
        try:
            result[name] = {
                "status": "diagnostic_only" if name == INVERSE_DIAGNOSTIC else "candidate_comparator",
                **simulate_daily_topk_portfolio(rows.assign(score=rows[f"score__{name}"])),
            }
        except ValueError as error:
            result[name] = {"status": "unavailable", "reason": str(error)}
    return result


def _candidate_screen(
    metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    bootstrap: Mapping[str, Mapping[str, Mapping[str, Any]]],
    portfolios: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, dict[str, Any]]:
    candidates = [
        name for name in PRE_REGISTERED_COMPARATORS if name not in {PRIMARY_BASELINE, INVERSE_DIAGNOSTIC}
    ]
    result: dict[str, dict[str, Any]] = {}
    for regime in MARKET_REGIMES:
        a_keys = sorted(key for key in metrics if f"_{regime}_A_development_seen" in key)
        c_keys = sorted(key for key in metrics if f"_{regime}_C_development_unseen" in key)
        result[regime] = {}
        for name in candidates:
            a_active = [key for key in a_keys if name in metrics[key]]
            c_active = [key for key in c_keys if name in metrics[key]]
            if not a_active:
                result[regime][name] = {
                    "status": "inactive_no_train_only_direction",
                    "a_evaluable_fold_count": len(a_keys),
                    "a_active_fold_count": 0,
                    "c_evaluable_fold_count": len(c_keys),
                    "c_active_fold_count": len(c_active),
                    "production_integration_allowed": False,
                }
                continue
            a_pass = [key for key in a_active if _passes_a_gate(key, name, metrics, bootstrap, portfolios)]
            c_non_collapsed = [
                key
                for key in c_active
                if metrics[key][name]["ndcg_at_10"] >= metrics[key][PRIMARY_BASELINE]["ndcg_at_10"] - 0.02
            ]
            passed = len(a_active) >= 4 and len(a_pass) >= 4 and len(c_active) >= 4 and len(c_non_collapsed) >= 4
            result[regime][name] = {
                "status": "development_screen_passed" if passed else "development_screen_failed",
                "a_evaluable_fold_count": len(a_keys),
                "a_active_fold_count": len(a_active),
                "a_folds_passing_all_registered_checks": len(a_pass),
                "c_evaluable_fold_count": len(c_keys),
                "c_active_fold_count": len(c_active),
                "c_folds_without_ndcg_collapse": len(c_non_collapsed),
                "production_integration_allowed": False,
                "reason": "Development-only state-conditioned evidence cannot authorize production integration.",
            }
    return result


def _passes_a_gate(
    key: str,
    name: str,
    metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    bootstrap: Mapping[str, Mapping[str, Mapping[str, Any]]],
    portfolios: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> bool:
    candidate, baseline = metrics[key][name], metrics[key][PRIMARY_BASELINE]
    return (
        candidate["ndcg_at_10"] >= baseline["ndcg_at_10"]
        and candidate["precision_at_5"] >= baseline["precision_at_5"]
        and candidate["top_5_mean_return"] >= baseline["top_5_mean_return"]
        and _portfolio_not_worse(portfolios[key][name], portfolios[key][PRIMARY_BASELINE])
        and bootstrap[key][name]["precision_at_5_uplift_ci_low"] > 0.0
    )


def _portfolio_not_worse(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    if candidate.get("status") == "unavailable" or baseline.get("status") == "unavailable":
        return False
    return float(candidate.get("maximum_drawdown", 0.0)) >= float(baseline.get("maximum_drawdown", 0.0))


def _positive_int(value: int, name: str) -> int:
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be at least 1")
    return result
