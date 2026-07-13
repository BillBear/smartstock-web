"""Pre-registered price, liquidity, and risk interaction features."""
from __future__ import annotations

import numpy as np
import pandas as pd


INTERACTION_FEATURE_NAMES = (
    "return_5d_x_amount_ratio_5d",
    "return_20d_x_turnover_rank",
    "return_60d_x_volatility_20d",
    "close_to_high_x_amount_ratio_5d",
    "reversal_5d_x_trend_60d",
    "amount_turnover_joint_decile",
    "amount_rank_u_shape",
    "turnover_rank_u_shape",
    "atr_rank_u_shape",
    "return_60d_rank_u_shape",
)


def build_interaction_features(rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    result = rows.reset_index(drop=True).copy()
    required = {
        "trade_date", "adjusted_return_5d", "adjusted_return_20d", "adjusted_return_60d",
        "amount_ratio_5d", "turnover_rate_rank", "realized_volatility_20d",
        "adjusted_close_to_high", "atr_pct_14d", "amount_log_rank",
    }
    missing = sorted(required - set(result.columns))
    if missing:
        raise ValueError("interaction features missing columns: " + ", ".join(missing))
    result["return_5d_x_amount_ratio_5d"] = result["adjusted_return_5d"] * result["amount_ratio_5d"]
    result["return_20d_x_turnover_rank"] = result["adjusted_return_20d"] * result["turnover_rate_rank"]
    result["return_60d_x_volatility_20d"] = result["adjusted_return_60d"] * result["realized_volatility_20d"]
    result["close_to_high_x_amount_ratio_5d"] = result["adjusted_close_to_high"] * result["amount_ratio_5d"]
    result["reversal_5d_x_trend_60d"] = -result["adjusted_return_5d"] * result["adjusted_return_60d"]
    amount_decile = _decile(result["amount_log_rank"])
    turnover_decile = _decile(result["turnover_rate_rank"])
    result["amount_turnover_joint_decile"] = amount_decile * 10 + turnover_decile
    atr_rank = result.groupby("trade_date", sort=False)["atr_pct_14d"].rank(pct=True)
    return_rank = result.groupby("trade_date", sort=False)["adjusted_return_60d"].rank(pct=True)
    for source, output in (
        (result["amount_log_rank"], "amount_rank_u_shape"),
        (result["turnover_rate_rank"], "turnover_rank_u_shape"),
        (atr_rank, "atr_rank_u_shape"),
        (return_rank, "return_60d_rank_u_shape"),
    ):
        result[output] = (pd.to_numeric(source, errors="coerce") - 0.5).abs() * 2.0
    for name in INTERACTION_FEATURE_NAMES:
        result[name] = pd.to_numeric(result[name], errors="coerce").astype("float32")
    return result


def _decile(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").clip(0.0, 1.0)
    return np.floor(numeric * 9.999999).astype("float32")
