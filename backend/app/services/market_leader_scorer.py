"""Market-leader scoring for smart-pick recommendations.

The score deliberately measures strength before tradability. Risk gates can
later downgrade a strong stock to watch-only, but weak stocks should not rank
above market leaders simply because they look quiet.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List


class MarketLeaderScorer:
    """Score relative market leadership from quote, theme and flow evidence."""

    @classmethod
    def score_pick(cls, pick: Dict[str, Any]) -> Dict[str, Any]:
        metrics = pick.get("market_metrics") or {}
        features = (pick.get("feature_snapshot") or {}).get("features") or {}
        breakdown = pick.get("score_breakdown") or {}

        pct_change = cls._safe_float(metrics.get("pct_change"), cls._safe_float(features.get("pct_change"), 0))
        amount_yi = cls._safe_float(metrics.get("amount_yi"), cls._safe_float(features.get("amount_yi"), 0))
        turnover = cls._safe_float(metrics.get("turnover_rate"), 0)
        volume_ratio = cls._safe_float(metrics.get("volume_ratio"), cls._safe_float(features.get("volume_ratio_20"), 1))
        return_5d = cls._safe_float(features.get("return_5d_pct"), cls._safe_float(metrics.get("return_5d_pct"), 0))
        return_20d = cls._safe_float(features.get("return_20d_pct"), cls._safe_float(metrics.get("return_20d_pct"), 0))
        from_high = cls._safe_float(features.get("from_20d_high_pct"), cls._safe_float(metrics.get("from_20d_high_pct"), 0))
        theme_score = cls._safe_float(pick.get("theme_rank_score"), cls._safe_float(breakdown.get("theme"), 0))
        flow_yi = cls._safe_float(metrics.get("main_net_inflow_yi"), 0)
        flow_quality = str(pick.get("money_flow_quality") or metrics.get("money_flow_quality") or "")

        intraday_component = cls._clamp(50 + pct_change * 6.0, 0, 100)
        liquidity_component = cls._clamp(amount_yi * 5.5, 0, 100)
        turnover_component = cls._turnover_component(turnover)
        volume_component = cls._clamp(42 + (volume_ratio - 1.0) * 22.0, 0, 100)
        relative_strength_component = cls._clamp(
            48
            + return_5d * 2.0
            + return_20d * 1.05
            + max(from_high, -20.0) * 0.55,
            0,
            100,
        )
        theme_component = theme_score if theme_score > 0 else 45.0
        flow_component = cls._clamp(50 + flow_yi * (8.0 if flow_quality == "real" else 3.5), 0, 100)

        leader_score = cls._clamp(
            intraday_component * 0.18
            + relative_strength_component * 0.22
            + volume_component * 0.16
            + liquidity_component * 0.13
            + turnover_component * 0.11
            + theme_component * 0.13
            + flow_component * 0.07,
            0,
            100,
        )

        reasons: List[str] = []
        if pct_change >= 3:
            reasons.append(f"当日涨幅 {pct_change:.2f}% 位于强势区间")
        if return_5d >= 4 or return_20d >= 8:
            reasons.append(f"近5/20日相对强度 {return_5d:.1f}% / {return_20d:.1f}%")
        if volume_ratio >= 1.3:
            reasons.append(f"量能放大 {volume_ratio:.2f} 倍")
        if amount_yi >= 5:
            reasons.append(f"成交额约 {amount_yi:.1f} 亿，流动性可观察")
        if theme_score >= 70:
            reasons.append("匹配市场主线或高强度主题")
        if flow_quality == "real" and flow_yi > 0:
            reasons.append(f"真实资金流净流入 {flow_yi:.2f} 亿")
        elif flow_quality and flow_quality != "real":
            reasons.append("资金流为代理/低置信来源，仅弱支撑强势判断")
        if not reasons:
            reasons.append("强势分由涨幅、相对强度、量能、流动性、主题和资金质量综合得到")

        return {
            "leader_score": round(leader_score, 2),
            "leader_rank_reason": reasons[:5],
            "leader_components": {
                "intraday": round(intraday_component, 2),
                "relative_strength": round(relative_strength_component, 2),
                "volume": round(volume_component, 2),
                "liquidity": round(liquidity_component, 2),
                "turnover": round(turnover_component, 2),
                "theme": round(theme_component, 2),
                "money_flow": round(flow_component, 2),
            },
        }

    @staticmethod
    def _turnover_component(turnover: float) -> float:
        if turnover <= 0:
            return 40.0
        if turnover <= 3:
            return 45 + turnover * 9
        if turnover <= 12:
            return 72 + (turnover - 3) * 2.4
        if turnover <= 25:
            return 94 - (turnover - 12) * 2.2
        return max(15.0, 65 - (turnover - 25) * 2.0)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            result = float(value)
            if not math.isfinite(result):
                return float(default)
            return result
        except Exception:
            return float(default)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        try:
            result = float(value)
        except Exception:
            return low
        if not math.isfinite(result):
            return low
        return max(low, min(high, result))
