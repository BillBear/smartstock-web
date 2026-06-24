"""Execution constraints for historical replay backtests."""
from __future__ import annotations

from typing import Any, Dict


class BacktestEngine:
    """A-share execution helper used by the replay backtest."""

    LOT_SIZE = 100

    @classmethod
    def default_constraints(cls, slippage: float) -> Dict[str, Any]:
        return {
            "engine": "historical_replay_v2_a_share_constraints",
            "buy_t_plus_1": True,
            "lot_size": cls.LOT_SIZE,
            "limit_up_buy_blocked": True,
            "limit_down_sell_blocked": True,
            "suspended_skip": True,
            "execution_price": "next_open_for_buy_close_for_sell_with_slippage",
            "slippage": slippage,
            "money_flow": "historical replay uses proxy money-flow; proxy flow cannot pass live-trading admission",
        }

    @classmethod
    def can_buy(cls, row: Any) -> Dict[str, Any]:
        pct_change = cls._safe_float(cls._row_get(row, "pct_change"), 0)
        open_price = cls._safe_float(cls._row_get(row, "open"), 0)
        close_price = cls._safe_float(cls._row_get(row, "close"), 0)
        volume = cls._safe_float(cls._row_get(row, "volume"), 0)
        if open_price <= 0 or close_price <= 0 or volume <= 0:
            return {"allowed": False, "reason": "停牌或无有效开盘价，买入跳过"}
        if pct_change >= 9.75:
            return {"allowed": False, "reason": "疑似涨停，买入不可成交"}
        return {"allowed": True, "reason": "可按次日开盘价模拟买入"}

    @classmethod
    def can_sell(cls, row: Any) -> Dict[str, Any]:
        pct_change = cls._safe_float(cls._row_get(row, "pct_change"), 0)
        close_price = cls._safe_float(cls._row_get(row, "close"), 0)
        volume = cls._safe_float(cls._row_get(row, "volume"), 0)
        if close_price <= 0 or volume <= 0:
            return {"allowed": False, "reason": "停牌或无有效收盘价，卖出顺延"}
        if pct_change <= -9.75:
            return {"allowed": False, "reason": "疑似跌停，卖出不可成交"}
        return {"allowed": True, "reason": "可按收盘价模拟卖出"}

    @staticmethod
    def _row_get(row: Any, key: str) -> Any:
        try:
            return row.get(key)
        except Exception:
            try:
                return row[key]
            except Exception:
                return None

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)
