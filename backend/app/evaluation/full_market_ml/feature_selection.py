"""Development-only feature-block evidence and acceptance gates."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping

import numpy as np
import pandas as pd

from .feature_audit import _population_stability_index
from .features import assert_leak_free_schema
from .splits import FinalHoldoutAccessError, SplitPlan


@dataclass(frozen=True)
class FeatureBlockDecision:
    name: str
    status: Literal["accepted", "rejected", "diagnostic_only"]
    coverage: float
    return_fold_directions: tuple[int, ...]
    risk_fold_directions: tuple[int, ...]
    c_direction_matches: bool
    max_psi: float
    oof_uplift: dict[str, float]
    reasons: tuple[str, ...]


def evaluate_feature_blocks(
    development_rows: pd.DataFrame,
    split_plan: SplitPlan,
    block_schemas: Mapping[str, tuple[str, ...]],
) -> tuple[FeatureBlockDecision, ...]:
    """Evaluate coverage, fold direction, unseen-stock direction, drift, and OOF uplift."""
    rows = _development_rows(development_rows, split_plan)
    if not isinstance(block_schemas, Mapping) or not block_schemas:
        raise ValueError("block_schemas must contain at least one feature block")
    schemas = tuple((str(name), tuple(features)) for name, features in block_schemas.items())
    all_features = tuple(dict.fromkeys(feature for _, features in schemas for feature in features))
    return tuple(
        _evaluate_block(name, features, all_features, rows, split_plan)
        for name, features in schemas
    )


def _evaluate_block(
    name: str,
    features: tuple[str, ...],
    all_features: tuple[str, ...],
    rows: pd.DataFrame,
    split_plan: SplitPlan,
) -> FeatureBlockDecision:
    if not features:
        raise ValueError(f"feature block {name} is empty")
    missing = sorted(set(features) - set(rows.columns))
    if missing:
        raise ValueError(f"feature block {name} missing columns: " + ", ".join(missing))
    assert_leak_free_schema(features)
    numeric = rows[list(features)].apply(pd.to_numeric, errors="coerce")
    coverage = float(numeric.notna().all(axis=1).mean())
    return_target = _first_existing(
        rows,
        ("target_clipped_return_10d", "net_return_after_cost_10d", "net_return_after_cost", "future_return_10d"),
    )
    risk_target = _first_existing(rows, ("label_severe_negative_10d_v2", "label_severe_negative_10d"))

    return_directions = []
    risk_directions = []
    psi_values = []
    prior_values: dict[str, pd.Series] | None = None
    fold_uplifts = []
    for fold in split_plan.walk_forward:
        validation = rows.loc[
            rows["trade_date"].isin(fold.validation_dates)
            & rows["symbol"].isin(fold.training_symbols)
        ]
        return_directions.append(_block_direction(validation, features, return_target))
        risk_directions.append(_block_direction(validation, features, risk_target) if risk_target else 0)
        current_values = {
            feature: pd.to_numeric(validation[feature], errors="coerce").dropna()
            for feature in features
        }
        if prior_values is not None:
            psi_values.extend(
                _population_stability_index(prior_values[feature], current_values[feature])
                for feature in features
            )
        prior_values = current_values

        training = rows.loc[
            rows["trade_date"].isin(fold.training_dates)
            & rows["symbol"].isin(fold.training_symbols)
        ]
        learned = {
            feature: _feature_direction(training, feature, return_target)
            for feature in all_features
        }
        fold_uplifts.append(
            _fold_leave_one_block_out_uplift(
                validation,
                all_features,
                features,
                learned,
                return_target,
            )
        )

    majority = _majority_direction(tuple(return_directions))
    c_rows = rows.loc[rows["symbol"].isin(split_plan.C_dev_unseen_symbols)]
    c_direction = _block_direction(c_rows, features, return_target) if not c_rows.empty else 0
    c_matches = c_direction == 0 or majority == 0 or c_direction == majority
    max_psi = float(np.nanmax(psi_values)) if psi_values and not np.isnan(psi_values).all() else 0.0
    oof_uplift = {
        key: float(np.mean([item[key] for item in fold_uplifts])) if fold_uplifts else 0.0
        for key in ("top5_mean_return_uplift", "actionable_precision_uplift", "ndcg_at_10_uplift")
    }

    reasons = []
    lowered_name = name.lower()
    if "fundamental" in lowered_name:
        minimum_coverage = 0.70
    elif "moneyflow" in lowered_name:
        minimum_coverage = 0.90
    else:
        minimum_coverage = 0.95
    if coverage < minimum_coverage:
        reasons.append(f"coverage_below_{minimum_coverage:.2f}".replace(".", "_"))
    if max_psi > 0.50:
        reasons.append("psi_above_0_50")
    required_consistent = max(1, math.ceil(len(return_directions) * 0.80))
    consistent = sum(direction == majority and direction != 0 for direction in return_directions)
    if consistent < required_consistent:
        reasons.append("return_direction_not_stable")
    if not c_matches:
        reasons.append("c_direction_mismatch")

    if coverage < minimum_coverage and "moneyflow" in name.lower():
        status: Literal["accepted", "rejected", "diagnostic_only"] = "diagnostic_only"
    elif reasons:
        status = "rejected"
    else:
        status = "accepted"
    return FeatureBlockDecision(
        name=name,
        status=status,
        coverage=coverage,
        return_fold_directions=tuple(return_directions),
        risk_fold_directions=tuple(risk_directions),
        c_direction_matches=c_matches,
        max_psi=max_psi,
        oof_uplift=oof_uplift,
        reasons=tuple(reasons),
    )


def _development_rows(rows: pd.DataFrame, split_plan: SplitPlan) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("development_rows must be a pandas DataFrame")
    if not isinstance(split_plan, SplitPlan):
        raise TypeError("split_plan must be a SplitPlan")
    required = {"trade_date", "symbol"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("development_rows missing columns: " + ", ".join(missing))
    result = rows.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result["symbol"] = result["symbol"].astype("string").fillna("")
    if (~result["trade_date"].isin(split_plan.development_dates)).any():
        raise FinalHoldoutAccessError("feature selection accepts development dates only")
    return result.sort_values(["trade_date", "symbol"], kind="stable").reset_index(drop=True)


def _block_direction(rows: pd.DataFrame, features: tuple[str, ...], target: str) -> int:
    directions = [_feature_direction(rows, feature, target) for feature in features]
    return _majority_direction(tuple(directions))


def _feature_direction(rows: pd.DataFrame, feature: str, target: str) -> int:
    if not target or rows.empty:
        return 0
    daily = []
    for _, current in rows.groupby("trade_date", sort=False):
        values = current[[feature, target]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(values) >= 3 and values[feature].nunique() > 1 and values[target].nunique() > 1:
            correlation = values[feature].corr(values[target], method="spearman")
            if pd.notna(correlation):
                daily.append(float(correlation))
    value = float(np.median(daily)) if daily else 0.0
    return 1 if value > 0 else (-1 if value < 0 else 0)


def _fold_leave_one_block_out_uplift(
    validation: pd.DataFrame,
    all_features: tuple[str, ...],
    removed_features: tuple[str, ...],
    directions: Mapping[str, int],
    return_target: str,
) -> dict[str, float]:
    if validation.empty:
        return {"top5_mean_return_uplift": 0.0, "actionable_precision_uplift": 0.0, "ndcg_at_10_uplift": 0.0}
    scored = validation.copy()
    scored["_all_score"] = _rank_score(scored, all_features, directions)
    retained = tuple(feature for feature in all_features if feature not in set(removed_features))
    if retained:
        scored["_without_block_score"] = _rank_score(scored, retained, directions)
    else:
        baseline = _first_existing(scored, ("amount_log", "adjusted_return_60d"))
        scored["_without_block_score"] = scored[baseline] if baseline else 0.0
    full = _daily_top_metrics(scored, "_all_score", return_target)
    without = _daily_top_metrics(scored, "_without_block_score", return_target)
    return {
        key + "_uplift": full[key] - without[key]
        for key in ("top5_mean_return", "actionable_precision", "ndcg_at_10")
    }


def _rank_score(rows: pd.DataFrame, features: tuple[str, ...], directions: Mapping[str, int]) -> pd.Series:
    parts = []
    for feature in features:
        rank = rows.groupby("trade_date", sort=False)[feature].rank(pct=True)
        direction = directions.get(feature, 0)
        parts.append(rank * direction if direction else rank * 0.0)
    return pd.concat(parts, axis=1).mean(axis=1)


def _daily_top_metrics(rows: pd.DataFrame, score: str, target: str) -> dict[str, float]:
    metrics = []
    for _, current in rows.groupby("trade_date", sort=False):
        ranked = current.sort_values([score, "symbol"], ascending=[False, True], kind="stable")
        top = ranked.head(5)
        returns = pd.to_numeric(top[target], errors="coerce")
        precision = top.get("label_actionable_positive_10d", pd.Series(False, index=top.index)).eq(True).mean()
        if "return_relevance_grade_10d_v2" in ranked:
            grades = pd.to_numeric(ranked["return_relevance_grade_10d_v2"], errors="coerce").fillna(0).to_numpy()
            selected = grades[:10]
            ideal = np.sort(grades)[::-1][:10]
            discounts = np.log2(np.arange(len(selected)) + 2)
            dcg = np.sum((2**selected - 1) / discounts)
            idcg = np.sum((2**ideal - 1) / discounts)
            ndcg = float(dcg / idcg) if idcg else 0.0
        else:
            ndcg = 0.0
        metrics.append((float(returns.mean()), float(precision), ndcg))
    values = np.asarray(metrics, dtype=float)
    return {
        "top5_mean_return": float(values[:, 0].mean()) if len(values) else 0.0,
        "actionable_precision": float(values[:, 1].mean()) if len(values) else 0.0,
        "ndcg_at_10": float(values[:, 2].mean()) if len(values) else 0.0,
    }


def _majority_direction(directions: tuple[int, ...]) -> int:
    positive = sum(value > 0 for value in directions)
    negative = sum(value < 0 for value in directions)
    return 1 if positive > negative else (-1 if negative > positive else 0)


def _first_existing(rows: pd.DataFrame, columns: tuple[str, ...]) -> str:
    return next((column for column in columns if column in rows), "")
