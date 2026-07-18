"""Signal-date market and historical-industry state features."""
from __future__ import annotations

import numpy as np
import pandas as pd


MARKET_FEATURE_NAMES = (
    "market_positive_breadth_1d",
    "market_above_sma20_rate",
    "market_cross_section_return_median_1d",
    "market_cross_section_return_median_5d",
    "market_cross_section_return_median_20d",
    "market_return_dispersion_5d",
    "market_return_dispersion_20d",
    "market_limit_up_rate",
    "market_limit_down_rate",
    "small_minus_large_return_5d",
    "small_minus_large_return_20d",
    "industry_return_concentration_5d",
    "industry_return_concentration_20d",
)

INDUSTRY_FEATURE_NAMES = (
    "industry_signal_return_median_5d",
    "industry_signal_return_median_20d",
    "industry_strength_rank_5d",
    "industry_strength_rank_20d",
    "stock_excess_vs_industry_5d",
    "stock_excess_vs_industry_20d",
    "industry_positive_breadth_1d",
    "industry_above_sma20_rate",
    "industry_amount_acceleration_5d",
    "industry_signal_turnover_median",
    "industry_limit_up_rate",
    "industry_limit_down_rate",
)


def build_market_state_features(rows: pd.DataFrame) -> pd.DataFrame:
    result = _normalized(rows)
    _require(
        result,
        {
            "adjusted_return_1d",
            "adjusted_return_5d",
            "adjusted_return_20d",
            "price_to_sma_20d",
            "total_mv",
            "at_up_limit",
            "at_down_limit",
        },
    )
    grouped = result.groupby("trade_date", sort=False)
    result["market_positive_breadth_1d"] = grouped["adjusted_return_1d"].transform(lambda s: s.gt(0).mean())
    result["market_above_sma20_rate"] = grouped["price_to_sma_20d"].transform(lambda s: s.gt(0).mean())
    result["market_limit_up_rate"] = grouped["at_up_limit"].transform(lambda s: s.eq(True).mean())
    result["market_limit_down_rate"] = grouped["at_down_limit"].transform(lambda s: s.eq(True).mean())
    for window in (1, 5, 20):
        source = f"adjusted_return_{window}d"
        result[f"market_cross_section_return_median_{window}d"] = grouped[source].transform("median")
    for window in (5, 20):
        source = f"adjusted_return_{window}d"
        result[f"market_return_dispersion_{window}d"] = grouped[source].transform("std")
        result[f"small_minus_large_return_{window}d"] = grouped.apply(
            lambda frame: _small_minus_large(frame, source), include_groups=False
        ).reindex(result["trade_date"]).to_numpy()
        result[f"industry_return_concentration_{window}d"] = grouped.apply(
            lambda frame: _industry_concentration(frame, source), include_groups=False
        ).reindex(result["trade_date"]).to_numpy()
    return _float32(result, MARKET_FEATURE_NAMES)


def build_industry_state_features(rows: pd.DataFrame) -> pd.DataFrame:
    result = _normalized(rows)
    _require(
        result,
        {
            "industry_l1",
            "adjusted_return_1d",
            "adjusted_return_5d",
            "adjusted_return_20d",
            "price_to_sma_20d",
            "amount_ratio_5d",
            "turnover_rate",
            "at_up_limit",
            "at_down_limit",
        },
    )
    # Cross-sectional construction revisits each date while retaining prior-date
    # columns in the symbol shard. Drop stale outputs before merging fresh daily
    # industry statistics so Pandas cannot suffix the registered feature names.
    result = result.drop(columns=[name for name in INDUSTRY_FEATURE_NAMES if name in result], errors="ignore")
    keys = ["trade_date", "industry_l1"]
    valid = result["industry_l1"].notna()
    source = result.loc[valid].copy()
    grouped = source.groupby(keys, sort=False)
    stats = grouped.agg(
        industry_signal_return_median_5d=("adjusted_return_5d", "median"),
        industry_signal_return_median_20d=("adjusted_return_20d", "median"),
        industry_positive_breadth_1d=("adjusted_return_1d", lambda s: s.gt(0).mean()),
        industry_above_sma20_rate=("price_to_sma_20d", lambda s: s.gt(0).mean()),
        industry_amount_acceleration_5d=("amount_ratio_5d", "median"),
        industry_signal_turnover_median=("turnover_rate", "median"),
        industry_limit_up_rate=("at_up_limit", lambda s: s.eq(True).mean()),
        industry_limit_down_rate=("at_down_limit", lambda s: s.eq(True).mean()),
    ).reset_index()
    for window in (5, 20):
        median_name = f"industry_signal_return_median_{window}d"
        stats[f"industry_strength_rank_{window}d"] = stats.groupby("trade_date", sort=False)[median_name].rank(pct=True)
    result = result.merge(stats, on=keys, how="left", validate="many_to_one")
    for window in (5, 20):
        result[f"stock_excess_vs_industry_{window}d"] = (
            result[f"adjusted_return_{window}d"] - result[f"industry_signal_return_median_{window}d"]
        )
    return _float32(result, INDUSTRY_FEATURE_NAMES)


def _small_minus_large(frame: pd.DataFrame, source: str) -> float:
    size = pd.to_numeric(frame["total_mv"], errors="coerce")
    returns = pd.to_numeric(frame[source], errors="coerce")
    valid = size.notna() & returns.notna()
    if valid.sum() < 3:
        return np.nan
    low, high = size.loc[valid].quantile([0.3, 0.7])
    return float(returns.loc[valid & size.le(low)].mean() - returns.loc[valid & size.ge(high)].mean())


def _industry_concentration(frame: pd.DataFrame, source: str) -> float:
    if "industry_l1" not in frame:
        return np.nan
    medians = frame.dropna(subset=["industry_l1"]).groupby("industry_l1")[source].median().abs()
    total = medians.sum()
    return float(medians.max() / total) if len(medians) and total > 0 else np.nan


def _normalized(rows: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    result = rows.reset_index(drop=True).copy()
    _require(result, {"trade_date", "symbol"})
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return result


def _require(rows: pd.DataFrame, required: set[str]) -> None:
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError("market/industry features missing columns: " + ", ".join(missing))


def _float32(rows: pd.DataFrame, names: tuple[str, ...]) -> pd.DataFrame:
    for name in names:
        if name not in rows:
            rows[name] = np.nan
        rows[name] = pd.to_numeric(rows[name], errors="coerce").astype("float32")
    return rows
