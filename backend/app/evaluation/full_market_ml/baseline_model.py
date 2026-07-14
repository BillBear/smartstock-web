"""Deterministic date-balanced linear baseline for nested feature evidence."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from .features import assert_leak_free_schema


class RegisteredBaselineTrainer:
    """Fit one frozen linear score on date-sectional feature ranks."""

    def __init__(self, *, ridge_alpha: float = 1.0):
        self.ridge_alpha = float(ridge_alpha)

    def fit_predict(
        self,
        train_rows: pd.DataFrame,
        validation_rows: pd.DataFrame,
        feature_schema: Sequence[str],
    ) -> pd.DataFrame:
        schema = tuple(str(name) for name in feature_schema)
        if not schema or len(schema) != len(set(schema)):
            raise ValueError("feature_schema must contain unique feature names")
        assert_leak_free_schema(schema)
        required = {"trade_date", "symbol", "alpha_target_10d", *schema}
        for name, rows in (("train", train_rows), ("validation", validation_rows)):
            missing = sorted(required - set(rows.columns))
            if missing:
                raise ValueError(f"{name} rows missing columns: " + ", ".join(missing))
        train = train_rows.copy()
        validation = validation_rows.copy()
        train_x = _date_rank_matrix(train, schema)
        validation_x = _date_rank_matrix(validation, schema)
        medians = train_x.median(axis=0).fillna(0.5)
        train_x = train_x.fillna(medians).astype("float32")
        validation_x = validation_x.fillna(medians).astype("float32")
        target = pd.to_numeric(train["alpha_target_10d"], errors="coerce")
        valid = target.notna()
        if valid.sum() < max(20, len(schema) * 2):
            raise ValueError("linear baseline has insufficient labeled training rows")
        date_counts = train.loc[valid].groupby("trade_date")["symbol"].transform("size")
        weights = (1.0 / date_counts).to_numpy(dtype="float64", copy=True)
        weights *= len(weights) / weights.sum()
        model = Ridge(alpha=self.ridge_alpha, fit_intercept=True)
        model.fit(train_x.loc[valid], target.loc[valid], sample_weight=weights)
        result = validation.copy()
        result["score"] = model.predict(validation_x).astype("float32")
        return result


def _date_rank_matrix(rows: pd.DataFrame, schema: tuple[str, ...]) -> pd.DataFrame:
    numeric = rows[list(schema)].apply(pd.to_numeric, errors="coerce")
    ranked = numeric.groupby(rows["trade_date"], sort=False).rank(method="average", pct=True)
    ranked.columns = list(schema)
    return ranked.replace([np.inf, -np.inf], np.nan)
