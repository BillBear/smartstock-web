"""Leak-free linear scorecards whose directions are learned on fit dates only."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from .features import assert_leak_free_schema


MIN_ABSOLUTE_MEDIAN_IC = 0.01
MIN_DIRECTION_CONSISTENCY = 0.80


def fit_train_only_scorecard(
    fit_rows: pd.DataFrame,
    prediction_rows: pd.DataFrame,
    *,
    feature_schema: Iterable[str],
) -> dict[str, Any]:
    """Learn direction from fit labels and score later rows without their labels.

    This deliberately has no hyperparameters or validation-set feature selection.
    It is a diagnostic comparator for OOF research, not a production model.
    """
    features = tuple(str(feature) for feature in feature_schema)
    assert_leak_free_schema(features)
    _validate_fit_rows(fit_rows, features)
    _validate_prediction_rows(prediction_rows, features)
    fitted = fit_scorecard_directions(fit_rows, feature_schema=features)
    scored = score_with_directions(prediction_rows, directions=fitted["directions"])
    return {**fitted, "predictions": scored}


def fit_scorecard_directions(
    fit_rows: pd.DataFrame,
    *,
    feature_schema: Iterable[str],
    minimum_daily_ic_count: int = 0,
) -> dict[str, Any]:
    """Derive sign-stable feature directions from fit-period labels only."""
    minimum_daily_ic_count = int(minimum_daily_ic_count)
    if minimum_daily_ic_count < 0:
        raise ValueError("minimum_daily_ic_count must be non-negative")
    features = tuple(str(feature) for feature in feature_schema)
    assert_leak_free_schema(features)
    _validate_fit_rows(fit_rows, features)
    evidence = {feature: _fit_direction_evidence(fit_rows, feature) for feature in features}
    directions = {
        feature: int(summary["direction"])
        for feature, summary in evidence.items()
        if int(summary["direction"]) != 0 and int(summary["daily_ic_count"]) >= minimum_daily_ic_count
    }
    return {
        "directions": directions,
        "direction_evidence": evidence,
        "minimum_daily_ic_count": minimum_daily_ic_count,
    }


def score_with_directions(
    prediction_rows: pd.DataFrame,
    *,
    directions: dict[str, int],
) -> pd.DataFrame:
    """Rank signal-time inputs with previously fitted directions.

    Missing feature values receive a neutral daily percentile rather than
    silently changing the number of components in a row's score.
    """
    features = tuple(str(feature) for feature in directions)
    assert_leak_free_schema(features)
    _validate_prediction_rows(prediction_rows, features)
    scored = prediction_rows.copy()
    if not directions:
        scored["score"] = 0.0
        return scored
    components = []
    for feature, direction in directions.items():
        values = pd.to_numeric(scored[feature], errors="coerce")
        ranks = values.groupby(scored["trade_date"], sort=False).rank(method="average", pct=True).fillna(0.5)
        components.append((ranks - 0.5) * int(direction))
    scored["score"] = pd.concat(components, axis=1).mean(axis=1).astype("float32")
    return scored


def _fit_direction(rows: pd.DataFrame, feature: str) -> int:
    return int(_fit_direction_evidence(rows, feature)["direction"])


def _fit_direction_evidence(rows: pd.DataFrame, feature: str) -> dict[str, float | int]:
    daily_ics = []
    for _, daily in rows.groupby("trade_date", sort=True):
        valid = daily[[feature, "net_return_after_cost_10d"]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(valid) < 3 or valid[feature].nunique() < 2 or valid["net_return_after_cost_10d"].nunique() < 2:
            continue
        ic = valid[feature].corr(valid["net_return_after_cost_10d"], method="spearman")
        if pd.notna(ic):
            daily_ics.append(float(ic))
    if not daily_ics:
        return {"direction": 0, "daily_ic_count": 0, "median_ic": 0.0, "direction_consistency": 0.0}
    values = np.asarray(daily_ics, dtype=float)
    median_ic = float(np.median(values))
    if abs(median_ic) < MIN_ABSOLUTE_MEDIAN_IC:
        return {
            "direction": 0,
            "daily_ic_count": int(len(values)),
            "median_ic": median_ic,
            "direction_consistency": float((np.sign(values) == np.sign(median_ic)).mean()) if median_ic else 0.0,
        }
    direction = 1 if median_ic > 0 else -1
    consistency = float((np.sign(values) == direction).mean())
    return {
        "direction": direction if consistency >= MIN_DIRECTION_CONSISTENCY else 0,
        "daily_ic_count": int(len(values)),
        "median_ic": median_ic,
        "direction_consistency": consistency,
    }


def _validate_fit_rows(rows: pd.DataFrame, features: tuple[str, ...]) -> None:
    required = {"trade_date", "net_return_after_cost_10d", *features}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("scorecard fit rows missing columns: " + ", ".join(missing))
    if rows.empty:
        raise ValueError("scorecard fit rows are empty")


def _validate_prediction_rows(rows: pd.DataFrame, features: tuple[str, ...]) -> None:
    required = {"trade_date", "symbol", *features}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("scorecard prediction rows missing columns: " + ", ".join(missing))
    if rows.empty:
        raise ValueError("scorecard prediction rows are empty")
