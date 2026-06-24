"""Risk gates for separating market strength from tradability."""
from __future__ import annotations

from typing import Any, Dict, List


class RiskGateService:
    """Evaluate whether a strong stock is tradable, paper-only or watch-only."""

    @classmethod
    def evaluate_pick(cls, pick: Dict[str, Any], risk_level: str = "medium") -> Dict[str, Any]:
        metrics = pick.get("market_metrics") or {}
        features = (pick.get("feature_snapshot") or {}).get("features") or {}
        reasons: List[str] = []
        hard_block = False
        caution = False

        symbol = str(pick.get("symbol") or "")
        name = str(pick.get("name") or "")
        price = cls._safe_float(metrics.get("price"), cls._safe_float(metrics.get("close"), 0))
        pct_change = cls._safe_float(metrics.get("pct_change"), 0)
        amount_yi = cls._safe_float(metrics.get("amount_yi"), 0)
        turnover = cls._safe_float(metrics.get("turnover_rate"), 0)
        dd_prob = cls._safe_float(pick.get("dd_prob"), 1)
        return_20d = cls._safe_float(features.get("return_20d_pct"), cls._safe_float(metrics.get("return_20d_pct"), 0))
        ma20_gap = cls._safe_float(features.get("ma20_gap_pct"), cls._safe_float(features.get("stretch_from_ma20_pct"), 0))
        rsi = cls._safe_float(features.get("rsi"), 50)
        flow_quality = str(pick.get("money_flow_quality") or metrics.get("money_flow_quality") or "unavailable")
        action = str(pick.get("action") or "watch")

        if "ST" in name.upper() or "退" in name:
            hard_block = True
            reasons.append("ST/退市风险标的禁止进入可执行候选")
        if price > 0 and price < 2.0:
            hard_block = True
            reasons.append("股价低于低价股闸门，流动性和退市风险较高")
        if amount_yi and amount_yi < 1.0:
            hard_block = True
            reasons.append("成交额低于 1 亿，流动性不足")
        if turnover and turnover < 0.4:
            caution = True
            reasons.append("换手率过低，实际成交弹性不足")
        if cls.is_limit_up(pct_change):
            hard_block = True
            reasons.append("疑似涨停，次日买入可成交性不足")
        if cls.is_limit_down(pct_change):
            hard_block = True
            reasons.append("疑似跌停，卖出/止损可成交性不足")

        dd_gate = 0.32 if risk_level == "low" else (0.55 if risk_level == "high" else 0.42)
        if dd_prob > dd_gate:
            caution = True
            reasons.append(f"回撤概率 {dd_prob * 100:.1f}% 超过当前风险偏好闸门")
        if return_20d >= 30 or ma20_gap >= 13 or rsi >= 74:
            caution = True
            reasons.append("短线涨幅/乖离/RSI 偏高，禁止追高升级")
        if action == "buy" and flow_quality != "real":
            caution = True
            reasons.append("资金流非真实来源或不可用，不支持实盘准入")

        if hard_block:
            status = "block"
            display_mode = "watch_only"
        elif caution:
            status = "watch"
            display_mode = "paper_validate" if action == "buy" else "watch_only"
        else:
            status = "pass"
            display_mode = "trade_candidate" if action == "buy" else "paper_validate"

        if not reasons:
            reasons.append("流动性、涨跌停、过热、回撤和资金流闸门未触发硬性限制")

        return {
            "risk_gate_status": status,
            "risk_gate_reasons": reasons[:5],
            "display_mode": display_mode,
            "action_grade": cls.action_grade(action, status),
        }

    @staticmethod
    def action_grade(action: str, gate_status: str) -> str:
        if gate_status == "block":
            return "D"
        if gate_status == "watch":
            return "C" if action != "buy" else "B"
        if action == "buy":
            return "A"
        if action == "watch":
            return "C"
        return "D"

    @staticmethod
    def is_limit_up(pct_change: float, threshold: float = 9.75) -> bool:
        return pct_change >= threshold

    @staticmethod
    def is_limit_down(pct_change: float, threshold: float = -9.75) -> bool:
        return pct_change <= threshold

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)
