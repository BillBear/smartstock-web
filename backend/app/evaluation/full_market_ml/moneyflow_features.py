"""Detailed TuShare order-size money-flow features with explicit unit conversion."""
from __future__ import annotations

import numpy as np
import pandas as pd


MONEYFLOW_AMOUNT_TO_CNY = 10_000.0
_GROUPS = ("small", "medium", "large", "extra_large")
_RAW_PREFIX = {"small": "sm", "medium": "md", "large": "lg", "extra_large": "elg"}
MONEYFLOW_FEATURE_NAMES = tuple(
    [f"{group}_net_flow_ratio" for group in _GROUPS]
    + [f"{group}_net_flow_missing" for group in _GROUPS]
    + [f"{group}_net_flow_persistence_{window}d" for group in _GROUPS for window in (5, 20)]
    + [
        "large_minus_small_flow_ratio",
        "price_flow_divergence_5d",
        "price_flow_divergence_20d",
        "flow_minus_industry_median",
    ]
)


def build_moneyflow_features(rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    result = rows.reset_index(drop=True).copy()
    required = {"trade_date", "symbol", "amount_cny", "adjusted_return_5d", "adjusted_return_20d", "industry_l1"}
    required.update(
        column
        for prefix in _RAW_PREFIX.values()
        for column in (f"buy_{prefix}_amount", f"sell_{prefix}_amount")
    )
    missing = sorted(required - set(result.columns))
    if missing:
        raise ValueError("moneyflow features missing columns: " + ", ".join(missing))
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result = result.sort_values(["symbol", "trade_date"], kind="stable").reset_index(drop=True)
    denominator = pd.to_numeric(result["amount_cny"], errors="coerce").where(lambda s: s.gt(0))
    for group, prefix in _RAW_PREFIX.items():
        buy = pd.to_numeric(result[f"buy_{prefix}_amount"], errors="coerce")
        sell = pd.to_numeric(result[f"sell_{prefix}_amount"], errors="coerce")
        ratio = (buy - sell) * MONEYFLOW_AMOUNT_TO_CNY / denominator
        result[f"{group}_net_flow_ratio"] = ratio
        result[f"{group}_net_flow_missing"] = ratio.isna().astype("int8")
        for window in (5, 20):
            result[f"{group}_net_flow_persistence_{window}d"] = ratio.groupby(
                result["symbol"], sort=False
            ).transform(lambda s: s.rolling(window, min_periods=window).mean())
    result["large_minus_small_flow_ratio"] = result["large_net_flow_ratio"] - result["small_net_flow_ratio"]
    aggregate = result["large_net_flow_ratio"] + result["extra_large_net_flow_ratio"]
    for window in (5, 20):
        flow_mean = aggregate.groupby(result["symbol"], sort=False).transform(
            lambda s: s.rolling(window, min_periods=window).mean()
        )
        result[f"price_flow_divergence_{window}d"] = flow_mean - result[f"adjusted_return_{window}d"]
    industry_median = aggregate.groupby(
        [result["trade_date"], result["industry_l1"]], dropna=True, sort=False
    ).transform("median")
    result["flow_minus_industry_median"] = aggregate - industry_median
    for name in MONEYFLOW_FEATURE_NAMES:
        if not name.endswith("_missing"):
            result[name] = pd.to_numeric(result[name], errors="coerce").astype("float32")
    return result
