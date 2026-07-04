from __future__ import annotations

import math
from typing import Iterable, List

import numpy as np
import pandas as pd


def add_local_core_labels(
    panel_df: pd.DataFrame,
    horizons: List[int],
    primary_horizon: int = 10,
    absolute_return_threshold_pct: float = 8.0,
    take_profit_pct: float = 8.0,
    stop_loss_pct: float = 6.0,
) -> pd.DataFrame:
    """Add local ML labels without changing production label logic."""
    if panel_df is None or panel_df.empty:
        return pd.DataFrame()
    required = {"date", "symbol", "close", "high", "low", "volume", "amount"}
    missing = required - set(panel_df.columns)
    if missing:
        raise ValueError(f"local ML labels require columns: {', '.join(sorted(missing))}")

    horizons = _normalized_horizons(horizons, primary_horizon)
    rows = panel_df.copy()
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    rows = rows[rows["date"].notna()].copy()
    rows = rows.sort_values(["symbol", "date"]).reset_index(drop=True)
    for column in ["close", "high", "low", "volume", "amount"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")

    labeled_parts = []
    for _, group in rows.groupby("symbol", sort=False):
        labeled_parts.append(
            _label_symbol_path(
                group.copy(),
                horizons=horizons,
                absolute_return_threshold_pct=absolute_return_threshold_pct,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
            )
        )
    labeled = pd.concat(labeled_parts, ignore_index=True)

    primary_suffix = f"{int(primary_horizon)}d"
    primary_return = f"future_return_{primary_suffix}_pct"
    primary_drawdown = f"future_max_drawdown_{primary_suffix}_pct"
    labeled["tradability_flag"] = (
        (labeled["close"] > 0)
        & (labeled["volume"] > 0)
        & (labeled["amount"] > 0)
        & labeled[primary_return].notna()
    )
    if "pct_change" in labeled.columns:
        labeled["tradability_flag"] = labeled["tradability_flag"] & (pd.to_numeric(labeled["pct_change"], errors="coerce").abs() < 19.9)

    risk_col = f"future_risk_adjusted_return_{primary_suffix}"
    labeled[risk_col] = labeled[primary_return] + labeled[primary_drawdown].fillna(0.0) * 0.45
    labeled[f"label_top20_{primary_suffix}"] = 0
    labeled[f"label_bottom20_{primary_suffix}"] = 0

    for _, index in labeled.groupby("date").groups.items():
        tradable = labeled.loc[index]
        tradable = tradable[tradable["tradability_flag"] & tradable[risk_col].notna()]
        if tradable.empty:
            continue
        cutoff = max(1, int(math.ceil(len(tradable) * 0.20)))
        top_index = tradable.sort_values([risk_col, "symbol"], ascending=[False, True]).head(cutoff).index
        bottom_index = tradable.sort_values([risk_col, "symbol"], ascending=[True, True]).head(cutoff).index
        labeled.loc[top_index, f"label_top20_{primary_suffix}"] = 1
        labeled.loc[bottom_index, f"label_bottom20_{primary_suffix}"] = 1

    return labeled.sort_values(["date", "symbol"]).reset_index(drop=True)


def _label_symbol_path(
    group: pd.DataFrame,
    horizons: Iterable[int],
    absolute_return_threshold_pct: float,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> pd.DataFrame:
    close = group["close"].to_numpy(dtype=float)
    high = group["high"].to_numpy(dtype=float)
    low = group["low"].to_numpy(dtype=float)
    n = len(group)

    for horizon in horizons:
        suffix = f"{int(horizon)}d"
        future_return = np.full(n, np.nan)
        future_max_gain = np.full(n, np.nan)
        future_max_drawdown = np.full(n, np.nan)
        tp_before_sl = np.zeros(n, dtype=int)

        for index in range(n):
            current_close = close[index]
            end_index = index + int(horizon)
            if not np.isfinite(current_close) or current_close <= 0 or end_index >= n:
                continue
            future_slice = slice(index + 1, end_index + 1)
            future_close = close[end_index]
            future_high = np.nanmax(high[future_slice])
            future_low = np.nanmin(low[future_slice])
            future_return[index] = (future_close / current_close - 1.0) * 100.0
            future_max_gain[index] = (future_high / current_close - 1.0) * 100.0
            future_max_drawdown[index] = (future_low / current_close - 1.0) * 100.0
            tp_before_sl[index] = _tp_before_sl(
                high[future_slice],
                low[future_slice],
                current_close=current_close,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
            )

        group[f"future_return_{suffix}_pct"] = future_return
        group[f"future_max_gain_{suffix}_pct"] = future_max_gain
        group[f"future_max_drawdown_{suffix}_pct"] = future_max_drawdown
        group[f"label_up_{suffix}_abs"] = (group[f"future_return_{suffix}_pct"] >= absolute_return_threshold_pct).astype(int)
        group[f"label_tp_before_sl_{suffix}"] = tp_before_sl

    return group


def _tp_before_sl(
    future_high: np.ndarray,
    future_low: np.ndarray,
    current_close: float,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> int:
    take_profit_price = current_close * (1.0 + take_profit_pct / 100.0)
    stop_loss_price = current_close * (1.0 - stop_loss_pct / 100.0)
    for high_value, low_value in zip(future_high, future_low):
        hit_tp = np.isfinite(high_value) and high_value >= take_profit_price
        hit_sl = np.isfinite(low_value) and low_value <= stop_loss_price
        if hit_sl:
            return 0
        if hit_tp:
            return 1
    return 0


def _normalized_horizons(horizons: Iterable[int], primary_horizon: int) -> List[int]:
    values = {int(primary_horizon)}
    for horizon in horizons or []:
        values.add(int(horizon))
    return sorted(value for value in values if value > 0)
