from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from app.evaluation.local_ml_labels import add_local_core_labels


V2_FEATURE_SPECS: List[Dict[str, str]] = [
    {"name": "return_5d_pct", "category": "momentum", "description": "5 trading day return."},
    {"name": "return_10d_pct", "category": "momentum", "description": "10 trading day return."},
    {"name": "return_20d_pct", "category": "momentum", "description": "20 trading day return."},
    {"name": "return_60d_pct", "category": "momentum", "description": "60 trading day return."},
    {"name": "momentum_accel_5_20", "category": "momentum", "description": "Short momentum minus scaled 20 day momentum."},
    {"name": "momentum_accel_20_60", "category": "momentum", "description": "20 day momentum minus scaled 60 day momentum."},
    {"name": "return_20d_rank", "category": "relative_strength", "description": "Daily percentile rank of 20 day return."},
    {"name": "return_60d_rank", "category": "relative_strength", "description": "Daily percentile rank of 60 day return."},
    {"name": "ma20_gap_pct", "category": "trend_quality", "description": "Close versus MA20."},
    {"name": "ma60_gap_pct", "category": "trend_quality", "description": "Close versus MA60."},
    {"name": "ma_alignment", "category": "trend_quality", "description": "Moving average alignment count."},
    {"name": "trend_slope_20d", "category": "trend_quality", "description": "20 day log-price regression slope."},
    {"name": "trend_r2_20d", "category": "trend_quality", "description": "20 day trend fit quality."},
    {"name": "up_day_count_10d", "category": "trend_quality", "description": "Positive close-to-close days in last 10 days."},
    {"name": "up_day_count_20d", "category": "trend_quality", "description": "Positive close-to-close days in last 20 days."},
    {"name": "pullback_from_20d_high_pct", "category": "risk", "description": "Distance from 20 day high."},
    {"name": "recovery_from_20d_low_pct", "category": "risk", "description": "Distance above 20 day low."},
    {"name": "breakout_20d_count_5d", "category": "trend_quality", "description": "Recent closes above prior 20 day high."},
    {"name": "amount_log", "category": "liquidity", "description": "Log traded amount."},
    {"name": "amount_pct_rank", "category": "liquidity", "description": "Daily traded amount percentile rank."},
    {"name": "amount_ratio_5_20", "category": "liquidity", "description": "5 day amount average versus 20 day average."},
    {"name": "volume_spike_days_5d", "category": "liquidity", "description": "Recent persistent volume spikes."},
    {"name": "liquidity_stability_20d", "category": "liquidity", "description": "Share of recent days with usable amount."},
    {"name": "volatility_20d", "category": "risk", "description": "Annualized 20 day realized volatility."},
    {"name": "atr_14_pct", "category": "risk", "description": "14 day average true range percentage."},
    {"name": "large_down_day_count_20d", "category": "risk", "description": "Large down days in last 20 trading days."},
    {"name": "intraday_range_pct", "category": "risk", "description": "Daily high-low range."},
    {"name": "rsi", "category": "technical", "description": "RSI technical state."},
    {"name": "macd_hist", "category": "technical", "description": "MACD histogram."},
]
V2_FEATURE_NAMES = [spec["name"] for spec in V2_FEATURE_SPECS]


def filter_daily_cross_section(df: pd.DataFrame, min_daily_count: int = 500) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if df is None or df.empty:
        return pd.DataFrame(), {
            "min_required_daily_count": int(min_daily_count),
            "original_date_count": 0,
            "kept_date_count": 0,
            "dropped_date_count": 0,
            "min_daily_count": 0,
        }
    local = df.copy()
    local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[local["date"].notna()].copy()
    daily_count = local.groupby("date").size()
    keep_dates = set(daily_count[daily_count >= int(min_daily_count)].index)
    filtered = local[local["date"].isin(keep_dates)].copy()
    report = {
        "min_required_daily_count": int(min_daily_count),
        "original_date_count": int(local["date"].nunique()),
        "kept_date_count": int(filtered["date"].nunique()),
        "dropped_date_count": int(local["date"].nunique() - filtered["date"].nunique()),
        "min_daily_count": int(daily_count.min()) if not daily_count.empty else 0,
        "median_daily_count": float(daily_count.median()) if not daily_count.empty else 0.0,
        "max_daily_count": int(daily_count.max()) if not daily_count.empty else 0,
    }
    return filtered.sort_values(["date", "symbol"]).reset_index(drop=True), report


def add_local_core_v2_labels(
    panel_df: pd.DataFrame,
    horizons: List[int],
    primary_horizon: int = 10,
    absolute_return_threshold_pct: float = 8.0,
    take_profit_pct: float = 8.0,
    stop_loss_pct: float = 6.0,
) -> pd.DataFrame:
    labeled = add_local_core_labels(
        panel_df,
        horizons=horizons,
        primary_horizon=primary_horizon,
        absolute_return_threshold_pct=absolute_return_threshold_pct,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
    )
    if labeled.empty:
        return labeled
    horizons = _normalized_horizons(horizons, primary_horizon)
    labeled["label_tradeable_entry"] = labeled["tradability_flag"].astype(int)
    for horizon in horizons:
        suffix = f"{int(horizon)}d"
        return_col = f"future_return_{suffix}_pct"
        drawdown_col = f"future_max_drawdown_{suffix}_pct"
        tp_col = f"label_tp_before_sl_{suffix}"
        excess_col = f"future_excess_return_{suffix}_pct"
        if return_col not in labeled.columns:
            continue
        daily_median = labeled.groupby("date")[return_col].transform("median")
        labeled[excess_col] = labeled[return_col] - daily_median
        labeled[f"label_rank_top10_{suffix}"] = 0
        labeled[f"label_alpha_top20_{suffix}"] = 0
        labeled[f"label_drawdown_safe_{suffix}"] = (
            pd.to_numeric(labeled.get(drawdown_col), errors="coerce").fillna(-999) >= -float(stop_loss_pct)
        ).astype(int)
        labeled[f"label_trade_quality_{suffix}"] = 0

        for _, index in labeled.groupby("date").groups.items():
            rows = labeled.loc[index].copy()
            tradable = rows[rows["tradability_flag"] & rows[return_col].notna()]
            if tradable.empty:
                continue
            top10_count = max(1, int(math.ceil(len(tradable) * 0.10)))
            top20_count = max(1, int(math.ceil(len(tradable) * 0.20)))
            rank_index = tradable.sort_values([return_col, "symbol"], ascending=[False, True]).head(top10_count).index
            alpha_index = tradable.sort_values([excess_col, "symbol"], ascending=[False, True]).head(top20_count).index
            quality = tradable[
                (tradable.index.isin(rank_index))
                & (pd.to_numeric(tradable.get(tp_col), errors="coerce").fillna(0).astype(int) == 1)
                & (pd.to_numeric(tradable.get(drawdown_col), errors="coerce").fillna(-999) >= -float(stop_loss_pct))
            ]
            labeled.loc[rank_index, f"label_rank_top10_{suffix}"] = 1
            labeled.loc[alpha_index, f"label_alpha_top20_{suffix}"] = 1
            labeled.loc[quality.index, f"label_trade_quality_{suffix}"] = 1
    return labeled.sort_values(["date", "symbol"]).reset_index(drop=True)


def build_local_core_v2_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
    if df is None or df.empty:
        return pd.DataFrame(), V2_FEATURE_SPECS
    local = df.copy()
    local["date"] = pd.to_datetime(local["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    local = local[local["date"].notna()].sort_values(["symbol", "date"]).reset_index(drop=True)
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        local[column] = pd.to_numeric(local[column], errors="coerce")

    parts = []
    for _, group in local.groupby("symbol", sort=False):
        parts.append(_build_symbol_features(group.copy()))
    featured = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if featured.empty:
        return featured, V2_FEATURE_SPECS

    featured = featured.sort_values(["date", "symbol"]).reset_index(drop=True)
    featured["return_20d_rank"] = featured.groupby("date")["return_20d_pct"].rank(pct=True).fillna(0.5)
    featured["return_60d_rank"] = featured.groupby("date")["return_60d_pct"].rank(pct=True).fillna(0.5)
    featured["amount_pct_rank"] = featured.groupby("date")["amount"].rank(pct=True).fillna(0.5)
    for name in V2_FEATURE_NAMES:
        if name not in featured.columns:
            featured[name] = 0.0
        featured[f"{name}_missing"] = featured[name].isna().astype(int)
        featured[name] = pd.to_numeric(featured[name], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return featured, V2_FEATURE_SPECS


def _build_symbol_features(group: pd.DataFrame) -> pd.DataFrame:
    close = group["close"].astype(float)
    high = group["high"].astype(float)
    low = group["low"].astype(float)
    volume = group["volume"].astype(float)
    amount = group["amount"].astype(float)
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    group["return_5d_pct"] = _existing_or_return(group, "return_5d_pct", close, 5)
    group["return_10d_pct"] = (close / close.shift(10) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    group["return_20d_pct"] = _existing_or_return(group, "return_20d_pct", close, 20)
    group["return_60d_pct"] = (close / close.shift(60) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    group["momentum_accel_5_20"] = group["return_5d_pct"] - group["return_20d_pct"] * 0.25
    group["momentum_accel_20_60"] = group["return_20d_pct"] - group["return_60d_pct"] / 3.0
    group["ma20_gap_pct"] = pd.to_numeric(group.get("ma20_gap_pct", 0.0), errors="coerce")
    group["ma60_gap_pct"] = pd.to_numeric(group.get("ma60_gap_pct", 0.0), errors="coerce")
    group["ma_alignment"] = pd.to_numeric(group.get("ma_alignment", 0.0), errors="coerce")
    group["trend_slope_20d"] = close.rolling(20, min_periods=10).apply(_rolling_log_slope, raw=True)
    group["trend_r2_20d"] = close.rolling(20, min_periods=10).apply(_rolling_log_r2, raw=True)
    group["up_day_count_10d"] = (returns > 0).rolling(10, min_periods=1).sum()
    group["up_day_count_20d"] = (returns > 0).rolling(20, min_periods=1).sum()
    prior_20d_high = high.shift(1).rolling(20, min_periods=5).max()
    rolling_20d_high = high.rolling(20, min_periods=5).max()
    rolling_20d_low = low.rolling(20, min_periods=5).min()
    group["pullback_from_20d_high_pct"] = (close / rolling_20d_high - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    group["recovery_from_20d_low_pct"] = (close / rolling_20d_low - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0
    group["breakout_20d_count_5d"] = (close > prior_20d_high).rolling(5, min_periods=1).sum()
    group["amount_log"] = np.log1p(amount.clip(lower=0.0))
    group["amount_ratio_5_20"] = _safe_div(amount.rolling(5, min_periods=1).mean(), amount.rolling(20, min_periods=5).mean(), 1.0)
    group["volume_spike_days_5d"] = (_safe_div(volume, volume.rolling(20, min_periods=5).mean(), 1.0) >= 1.5).rolling(5, min_periods=1).sum()
    group["liquidity_stability_20d"] = (amount > 0).rolling(20, min_periods=1).mean()
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    group["atr_14_pct"] = _safe_div(true_range.rolling(14, min_periods=3).mean(), close, 0.0) * 100.0
    group["large_down_day_count_20d"] = (returns <= -0.05).rolling(20, min_periods=1).sum()
    group["volatility_20d"] = pd.to_numeric(group.get("volatility_20d", returns.rolling(20).std() * np.sqrt(252) * 100), errors="coerce")
    group["intraday_range_pct"] = pd.to_numeric(group.get("intraday_range_pct", _safe_div(high - low, close, 0.0) * 100.0), errors="coerce")
    group["rsi"] = pd.to_numeric(group.get("rsi", 50.0), errors="coerce")
    group["macd_hist"] = pd.to_numeric(group.get("macd_hist", 0.0), errors="coerce")
    return group


def _existing_or_return(group: pd.DataFrame, column: str, close: pd.Series, days: int) -> pd.Series:
    if column in group.columns:
        return pd.to_numeric(group[column], errors="coerce")
    return (close / close.shift(days) - 1.0).replace([np.inf, -np.inf], np.nan) * 100.0


def _safe_div(num: pd.Series, den: pd.Series, default: float = 0.0) -> pd.Series:
    return (num / den.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(default)


def _rolling_log_slope(values: Iterable[float]) -> float:
    y = np.log(np.asarray(values, dtype=float).clip(min=0.001))
    x = np.arange(len(y), dtype=float)
    if len(y) < 2 or not np.isfinite(y).all():
        return 0.0
    slope = np.polyfit(x, y, 1)[0]
    return float(slope * 100.0)


def _rolling_log_r2(values: Iterable[float]) -> float:
    y = np.log(np.asarray(values, dtype=float).clip(min=0.001))
    x = np.arange(len(y), dtype=float)
    if len(y) < 3 or not np.isfinite(y).all():
        return 0.0
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    total = float(np.sum((y - np.mean(y)) ** 2))
    if total <= 0:
        return 0.0
    return float(1.0 - np.sum((y - fitted) ** 2) / total)


def _normalized_horizons(horizons: Iterable[int], primary_horizon: int) -> List[int]:
    values = {int(primary_horizon)}
    for horizon in horizons or []:
        values.add(int(horizon))
    return sorted(value for value in values if value > 0)
