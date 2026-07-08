from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


def add_full_market_forward_labels(
    panel: pd.DataFrame,
    horizons: Iterable[int] | None = None,
    take_profit_pct: float = 8.0,
    stop_loss_pct: float = 6.0,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    horizons = sorted({int(h) for h in (horizons or [3, 5, 10, 20]) if int(h) > 0})
    if panel is None or panel.empty:
        return pd.DataFrame(), {"horizons": horizons, "row_count": 0}
    local = panel.copy().sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    for column in ["close", "high", "low"]:
        local[column] = pd.to_numeric(local[column], errors="coerce")
    if "entry_tradeable" not in local.columns:
        local["entry_tradeable"] = True
    if "hit_limit_up_today" not in local.columns:
        local["hit_limit_up_today"] = False
    if "hit_limit_down_today" not in local.columns:
        local["hit_limit_down_today"] = False

    parts = []
    for _, group in local.groupby("symbol", sort=False):
        parts.append(_label_symbol(group.copy(), horizons, take_profit_pct, stop_loss_pct))
    labeled = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    labeled = labeled.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    for horizon in horizons:
        _attach_daily_distribution_labels(labeled, horizon, take_profit_pct, stop_loss_pct)
    report = {
        "horizons": horizons,
        "row_count": int(len(labeled)),
        "labelable_10d_count": int(labeled.get("future_return_10d_pct", pd.Series(dtype=float)).notna().sum()),
    }
    return labeled, report


def _label_symbol(group: pd.DataFrame, horizons: List[int], take_profit_pct: float, stop_loss_pct: float) -> pd.DataFrame:
    close = group["close"].astype(float)
    high = group["high"].astype(float)
    low = group["low"].astype(float)
    limit_up = group["hit_limit_up_today"].astype(bool)
    limit_down = group["hit_limit_down_today"].astype(bool)
    for horizon in horizons:
        future_close = close.shift(-horizon)
        valid = future_close.notna()
        suffix = f"{horizon}d"
        future_high = _future_window(high, horizon, "max")
        future_low = _future_window(low, horizon, "min")
        group[f"future_return_{suffix}_pct"] = ((future_close / close) - 1.0) * 100.0
        group.loc[~valid, f"future_return_{suffix}_pct"] = np.nan
        group[f"future_max_profit_{suffix}_pct"] = ((future_high / close) - 1.0) * 100.0
        group[f"future_max_drawdown_{suffix}_pct"] = ((future_low / close) - 1.0) * 100.0
        group.loc[~valid, [f"future_max_profit_{suffix}_pct", f"future_max_drawdown_{suffix}_pct"]] = np.nan
        group[f"future_limit_up_count_{suffix}"] = _future_window(limit_up.astype(int), horizon, "sum")
        group[f"future_limit_down_count_{suffix}"] = _future_window(limit_down.astype(int), horizon, "sum")
        tp_flags, sl_flags = _path_flags(close, high, low, horizon, take_profit_pct, stop_loss_pct)
        group[f"tp_before_sl_{suffix}"] = tp_flags
        group[f"sl_before_tp_{suffix}"] = sl_flags
        group.loc[~valid, [f"tp_before_sl_{suffix}", f"sl_before_tp_{suffix}"]] = 0
    return group


def _future_window(series: pd.Series, horizon: int, op: str) -> pd.Series:
    shifted = series.shift(-1)
    reversed_values = shifted.iloc[::-1]
    if op == "max":
        return reversed_values.rolling(horizon, min_periods=1).max().iloc[::-1]
    if op == "min":
        return reversed_values.rolling(horizon, min_periods=1).min().iloc[::-1]
    return reversed_values.rolling(horizon, min_periods=1).sum().iloc[::-1]


def _path_flags(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    horizon: int,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> Tuple[List[int], List[int]]:
    close_values = close.to_numpy(dtype=float)
    high_values = high.to_numpy(dtype=float)
    low_values = low.to_numpy(dtype=float)
    tp_result: List[int] = []
    sl_result: List[int] = []
    for idx, entry in enumerate(close_values):
        tp_day = None
        sl_day = None
        for offset in range(1, horizon + 1):
            j = idx + offset
            if j >= len(close_values):
                break
            if tp_day is None and high_values[j] >= entry * (1.0 + take_profit_pct / 100.0):
                tp_day = offset
            if sl_day is None and low_values[j] <= entry * (1.0 - stop_loss_pct / 100.0):
                sl_day = offset
            if tp_day is not None and sl_day is not None:
                break
        tp_result.append(1 if tp_day is not None and (sl_day is None or tp_day <= sl_day) else 0)
        sl_result.append(1 if sl_day is not None and (tp_day is None or sl_day < tp_day) else 0)
    return tp_result, sl_result


def _attach_daily_distribution_labels(
    labeled: pd.DataFrame,
    horizon: int,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> None:
    suffix = f"{horizon}d"
    return_col = f"future_return_{suffix}_pct"
    if return_col not in labeled.columns:
        return
    labeled[f"future_return_rank_pct_{suffix}"] = labeled.groupby("trade_date")[return_col].rank(method="average", pct=True)
    daily_median = labeled.groupby("trade_date")[return_col].transform("median")
    labeled[f"future_excess_return_vs_market_{suffix}_pct"] = labeled[return_col] - daily_median
    if "industry" in labeled.columns:
        industry_median = labeled.groupby(["trade_date", "industry"])[return_col].transform("median")
        labeled[f"future_excess_return_vs_industry_{suffix}_pct"] = labeled[return_col] - industry_median
    else:
        labeled[f"future_excess_return_vs_industry_{suffix}_pct"] = 0.0
    rank = labeled[f"future_return_rank_pct_{suffix}"]
    max_profit = labeled[f"future_max_profit_{suffix}_pct"]
    max_drawdown = labeled[f"future_max_drawdown_{suffix}_pct"]
    entry_tradeable = labeled["entry_tradeable"].eq(True)
    labeled[f"label_core_strong_{suffix}"] = ((rank >= 0.90) & (max_profit >= 6.0) & (max_drawdown >= -8.0) & entry_tradeable).astype(int)
    labeled[f"label_strong_a_{suffix}"] = ((rank >= 0.95) & ((labeled[f"tp_before_sl_{suffix}"] == 1) | (max_profit >= take_profit_pct)) & (max_drawdown >= -6.0)).astype(int)
    labeled[f"label_weak_positive_{suffix}"] = ((rank >= 0.80) & (labeled[f"label_core_strong_{suffix}"] == 0) & (labeled[f"label_strong_a_{suffix}"] == 0)).astype(int)
    labeled[f"label_negative_{suffix}"] = ((rank <= 0.20) | (max_drawdown <= -8.0)).astype(int)
    labeled[f"label_severe_negative_{suffix}"] = ((rank <= 0.10) | (labeled[f"sl_before_tp_{suffix}"] == 1) | (labeled[f"future_limit_down_count_{suffix}"] > 0)).astype(int)
    if horizon == 10:
        for name in [
            "future_excess_return_vs_market",
            "future_excess_return_vs_industry",
            "future_max_profit",
            "future_max_drawdown",
            "tp_before_sl",
            "sl_before_tp",
            "future_limit_up_count",
            "future_limit_down_count",
        ]:
            source = f"{name}_{suffix}" + ("_pct" if name.startswith("future_excess") or name.startswith("future_max") else "")
            if source in labeled.columns:
                labeled[name + ("_pct" if name.startswith("future_excess") or name.startswith("future_max") else "")] = labeled[source]
