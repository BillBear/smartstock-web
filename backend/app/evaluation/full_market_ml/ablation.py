"""Actual nested-OOF feature-block admission for the ranking reset."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from .feature_selection import FeatureBlockDecision
from .features import assert_leak_free_schema
from .splits import SplitPlan


def run_nested_block_ablation(
    rows: pd.DataFrame,
    split_plan: SplitPlan,
    base_features: Sequence[str],
    candidate_blocks: Mapping[str, Sequence[str]],
    trainer,
) -> tuple[FeatureBlockDecision, ...]:
    """Reselect every block on inner dates, then estimate its outer OOF uplift."""
    base = tuple(dict.fromkeys(str(name) for name in base_features))
    blocks = tuple((str(name), tuple(dict.fromkeys(map(str, schema)))) for name, schema in candidate_blocks.items())
    if not base or not blocks:
        raise ValueError("base_features and candidate_blocks cannot be empty")
    assert_leak_free_schema(base + tuple(feature for _, schema in blocks for feature in schema))
    required = {
        "trade_date",
        "symbol",
        "alpha_target_10d",
        "alpha_top10_10d",
        "alpha_relevance_grade_10d",
        "net_return_after_cost_10d",
        *base,
        *(feature for _, schema in blocks for feature in schema),
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("ablation rows missing columns: " + ", ".join(missing))
    data = rows.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if (~data["trade_date"].isin(split_plan.development_dates)).any():
        raise PermissionError("nested ablation accepts development dates only")
    decisions = []
    for block_name, block_features in blocks:
        if not block_features:
            raise ValueError(f"candidate block {block_name} is empty")
        schema = tuple(dict.fromkeys((*base, *block_features)))
        inner_selected = []
        outer_uplifts = []
        daily_precision_uplifts = []
        for fold in split_plan.walk_forward:
            training = data.loc[
                data["trade_date"].isin(fold.training_dates)
                & data["symbol"].isin(fold.training_symbols)
            ].copy()
            outer = data.loc[
                data["trade_date"].isin(fold.validation_dates)
                & data["symbol"].isin(fold.training_symbols)
            ].copy()
            training_dates = tuple(sorted(training["trade_date"].unique()))
            if len(training_dates) < 80:
                raise ValueError(f"outer fold {fold.fold} has fewer than 80 dates for inner ablation")
            inner_validation_dates = training_dates[-20:]
            inner_fit_dates = training_dates[:-20]
            inner_fit = training.loc[training["trade_date"].isin(inner_fit_dates)].copy()
            inner_validation = training.loc[training["trade_date"].isin(inner_validation_dates)].copy()
            inner_fit["fold"], inner_fit["role"] = fold.fold, "inner_fit"
            inner_validation["fold"], inner_validation["role"] = fold.fold, "inner"
            base_inner = trainer.fit_predict(inner_fit, inner_validation, base)
            block_inner = trainer.fit_predict(inner_fit, inner_validation, schema)
            inner_uplift, _ = _compare_predictions(block_inner, base_inner)
            selected = all(inner_uplift[key] > 0 for key in _METRIC_KEYS)
            inner_selected.append(bool(selected))

            training["fold"], training["role"] = fold.fold, "outer_fit"
            outer["fold"], outer["role"] = fold.fold, "outer"
            base_outer = trainer.fit_predict(training, outer, base)
            block_outer = trainer.fit_predict(training, outer, schema)
            uplift, daily = _compare_predictions(block_outer, base_outer)
            outer_uplifts.append(uplift)
            daily_precision_uplifts.extend(daily)

        aggregate = {
            key: float(np.mean([fold[key] for fold in outer_uplifts]))
            for key in _METRIC_KEYS
        }
        nonnegative_folds = sum(all(fold[key] >= 0 for key in _METRIC_KEYS) for fold in outer_uplifts)
        ci_low, ci_high = _bootstrap_mean_ci(daily_precision_uplifts)
        numeric = data[list(block_features)].apply(pd.to_numeric, errors="coerce")
        coverage = float(numeric.notna().all(axis=1).mean())
        reasons = []
        if coverage < 0.95:
            reasons.append("coverage_below_0_95")
        if sum(inner_selected) < 4:
            reasons.append("inner_selection_below_4_of_5")
        if nonnegative_folds < 4 or aggregate["ndcg_at_10_uplift"] <= 0 or aggregate["top5_return_uplift"] <= 0:
            reasons.append("negative_actual_oof_uplift")
        if not np.isfinite(ci_low) or ci_low <= 0:
            reasons.append("precision_bootstrap_lower_bound_not_positive")
        status = "accepted_alpha" if not reasons else "rejected"
        decisions.append(
            FeatureBlockDecision(
                name=block_name,
                status=status,
                coverage=coverage,
                return_fold_directions=tuple(1 if fold["top5_return_uplift"] > 0 else (-1 if fold["top5_return_uplift"] < 0 else 0) for fold in outer_uplifts),
                risk_fold_directions=(),
                c_direction_matches=True,
                max_psi=0.0,
                oof_uplift=aggregate,
                reasons=tuple(reasons),
                inner_selected_folds=tuple(inner_selected),
                outer_fold_uplifts=tuple(outer_uplifts),
                precision_bootstrap_ci=(ci_low, ci_high),
            )
        )
    return tuple(decisions)


_METRIC_KEYS = ("precision_at_5_uplift", "ndcg_at_10_uplift", "top5_return_uplift")


def _compare_predictions(candidate: pd.DataFrame, baseline: pd.DataFrame) -> tuple[dict[str, float], list[float]]:
    keys = ["trade_date", "symbol"]
    if not candidate[keys].reset_index(drop=True).equals(baseline[keys].reset_index(drop=True)):
        raise ValueError("candidate and baseline predictions must use identical rows")
    candidate_daily = _daily_metrics(candidate)
    baseline_daily = _daily_metrics(baseline)
    merged = candidate_daily.merge(baseline_daily, on="trade_date", suffixes=("_candidate", "_baseline"), validate="one_to_one")
    daily_precision = (merged["precision_at_5_candidate"] - merged["precision_at_5_baseline"]).tolist()
    return (
        {
            "precision_at_5_uplift": float(np.mean(daily_precision)),
            "ndcg_at_10_uplift": float((merged["ndcg_at_10_candidate"] - merged["ndcg_at_10_baseline"]).mean()),
            "top5_return_uplift": float((merged["top5_return_candidate"] - merged["top5_return_baseline"]).mean()),
        },
        [float(value) for value in daily_precision],
    )


def _daily_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    records = []
    for trade_date, daily in predictions.groupby("trade_date", sort=True):
        ranked = daily.sort_values(["score", "symbol"], ascending=[False, True], kind="stable")
        top5 = ranked.head(5)
        grades = pd.to_numeric(ranked["alpha_relevance_grade_10d"], errors="coerce").fillna(0).to_numpy()
        ideal = np.sort(grades)[::-1][:10]
        discounts = np.log2(np.arange(min(10, len(grades))) + 2)
        dcg = np.sum((2 ** grades[:10] - 1) / discounts)
        idcg = np.sum((2 ** ideal - 1) / discounts)
        records.append(
            {
                "trade_date": trade_date,
                "precision_at_5": float(top5["alpha_top10_10d"].astype(bool).mean()),
                "ndcg_at_10": float(dcg / idcg) if idcg else 0.0,
                "top5_return": float(pd.to_numeric(top5["net_return_after_cost_10d"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(records)


def _bootstrap_mean_ci(values: list[float], *, iterations: int = 1000, seed: int = 17) -> tuple[float, float]:
    array = np.asarray(values, dtype="float64")
    if not len(array):
        return np.nan, np.nan
    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype="float64")
    for index in range(iterations):
        means[index] = rng.choice(array, size=len(array), replace=True).mean()
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)
