"""Configurable scoring helpers for smart-pick recommendations."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


class ScoringService:
    """Own score calibration, ranking weights and score adjustments.

    CoachService still builds most pick features today.  This service is the
    seam that keeps ranking math deterministic and separately testable.
    """

    RANK_WEIGHTS: Dict[str, Dict[str, float]] = {
        "low": {
            "anti_dd": 0.30,
            "edge": 0.22,
            "risk_adjusted": 0.21,
            "profit_factor": 0.09,
            "total": 0.10,
            "theme": 0.08,
        },
        "medium": {
            "up": 0.18,
            "anti_dd": 0.18,
            "edge": 0.25,
            "profit_factor": 0.13,
            "total": 0.17,
            "theme": 0.09,
        },
        "high": {
            "up": 0.20,
            "edge": 0.27,
            "profit_factor": 0.16,
            "total": 0.16,
            "anti_dd": 0.10,
            "theme": 0.11,
        },
    }

    def score(self, features: Iterable[Dict[str, Any]], strategy_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Legacy lightweight feature scorer kept for callers that use feature rows."""
        rows: List[Dict[str, Any]] = []
        for feature in features:
            pct = self._safe_float(feature.get("pct_change"), 0)
            amount_yi = self._safe_float(feature.get("amount"), 0) / 100000000
            total = self._clamp(50.0 + pct * 4.0 + min(amount_yi, 20.0), 0, 100)
            rows.append(
                {
                    "symbol": feature.get("symbol"),
                    "score_breakdown": {
                        "total": round(total, 2),
                        "momentum": round(pct, 2),
                        "liquidity": round(min(amount_yi, 20.0), 2),
                    },
                    "feature_quality": feature.get("data_quality") or {},
                }
            )
        return sorted(rows, key=lambda item: (item.get("score_breakdown") or {}).get("total", 0), reverse=True)

    def rank_score(self, pick: Dict[str, Any], risk_level: str = "medium") -> float:
        weights = self.RANK_WEIGHTS.get(str(risk_level or "medium"), self.RANK_WEIGHTS["medium"])
        breakdown = pick.get("score_breakdown") or {}
        up_prob = self._safe_float(pick.get("up_prob"), 0)
        dd_prob = self._safe_float(pick.get("dd_prob"), 1)
        total_score = self._safe_float(breakdown.get("total"), 0)
        risk_adjusted = self._safe_float(breakdown.get("risk_adjusted"), 0)
        edge_pct = self._safe_float(pick.get("expected_edge_pct"), 0)
        profit_factor = self._safe_float(pick.get("profit_factor_proxy"), 1)
        theme_score = self._safe_float(pick.get("theme_rank_score"), 0)

        components = {
            "up": up_prob * 100,
            "anti_dd": (1 - dd_prob) * 100,
            "edge": self._clamp(50 + edge_pct * 6, 0, 100),
            "profit_factor": self._clamp(45 + (profit_factor - 1) * 22, 0, 100),
            "total": total_score,
            "risk_adjusted": risk_adjusted,
            "theme": theme_score if theme_score > 0 else 35.0,
        }
        return sum(components.get(key, 0) * weight for key, weight in weights.items())

    def risk_specific_sort_key(self, pick: Dict[str, Any], risk_level: str = "medium") -> float:
        breakdown = pick.get("score_breakdown") or {}
        metrics = pick.get("market_metrics") or {}
        risk_level = str(risk_level or "medium")
        base = self.rank_score(pick, risk_level)
        symbol = str(pick.get("symbol") or "")
        board_penalty = 4.0 if symbol.startswith(("300", "688")) else 0.0

        if risk_level == "low":
            turnover = self._safe_float(metrics.get("turnover_rate"), 0)
            flow_yi = self._safe_float(metrics.get("main_net_inflow_yi"), 0)
            quality = self._safe_float(breakdown.get("quality"), 0)
            stability_bonus = self._clamp(100 - abs(turnover - 4.0) * 8, 0, 100) * 0.10
            flow_bonus = self._clamp(flow_yi * 8 + 50, 0, 100) * 0.08
            return base + quality * 0.08 + stability_bonus + flow_bonus - board_penalty

        if risk_level == "high":
            turnover = self._safe_float(metrics.get("turnover_rate"), 0)
            expected_return = self._safe_float(pick.get("expected_return_pct"), 0)
            edge_pct = self._safe_float(pick.get("expected_edge_pct"), 0)
            trend = self._safe_float(breakdown.get("trend"), 0)
            profit_factor = self._safe_float(pick.get("profit_factor_proxy"), 1)
            activity_score = self._clamp(turnover * 7.5, 0, 100)
            watch_bonus = 14.0 if pick.get("action") == "watch" else 0.0
            active_bonus = 8.0 if turnover >= 10 else (4.0 if turnover >= 8 else 0.0)
            growth_board_bonus = 4.0 if symbol.startswith(("300", "688")) else 0.0
            return (
                base
                + expected_return * 1.6
                + edge_pct * 2.2
                + activity_score * 0.24
                + trend * 0.10
                + (profit_factor - 1) * 8
                + watch_bonus
                + active_bonus
                + growth_board_bonus
            )

        return base

    def apply_risk_specific_selection(self, picks: List[Dict[str, Any]], risk_level: str = "medium") -> List[Dict[str, Any]]:
        if not picks:
            return []
        risk_level = str(risk_level or "medium")

        if risk_level == "low":
            selected = [
                p for p in picks
                if (
                    p.get("action") == "buy"
                    and self._safe_float(p.get("dd_prob"), 1) <= 0.24
                    and self._safe_float((p.get("score_breakdown") or {}).get("risk_adjusted"), 0) >= 56
                    and self._safe_float((p.get("market_metrics") or {}).get("turnover_rate"), 0) <= 9
                    and self._safe_float((p.get("market_metrics") or {}).get("main_net_inflow_yi"), 0) >= -0.2
                )
            ]
            if len(selected) < 8:
                selected = [
                    p for p in picks
                    if (
                        p.get("action") == "buy"
                        and self._safe_float(p.get("dd_prob"), 1) <= 0.32
                        and self._safe_float((p.get("score_breakdown") or {}).get("risk_adjusted"), 0) >= 50
                    )
                ]
            selected.sort(key=lambda item: self.risk_specific_sort_key(item, "low"), reverse=True)
            return selected

        if risk_level == "high":
            selected = [
                p for p in picks
                if (
                    p.get("action") in {"buy", "watch"}
                    and self._safe_float(p.get("dd_prob"), 1) <= 0.55
                    and self._safe_float(p.get("expected_edge_pct"), 0) >= 0.0
                )
            ]
            active_selected = [
                p for p in selected
                if (
                    p.get("action") == "watch"
                    or self._safe_float((p.get("market_metrics") or {}).get("turnover_rate"), 0) >= 9
                    or str(p.get("symbol") or "").startswith(("300", "688"))
                )
            ]
            if len(active_selected) >= 10:
                selected = active_selected
            selected.sort(key=lambda item: self.risk_specific_sort_key(item, "high"), reverse=True)
            return selected

        selected = [p for p in picks if self._safe_float(p.get("dd_prob"), 1) <= 0.42]
        selected.sort(key=lambda item: self.risk_specific_sort_key(item, "medium"), reverse=True)
        return selected

    def apply_universe_quality_guard(self, picks: List[Dict[str, Any]], universe_meta: Dict[str, Any]) -> None:
        if not picks:
            return
        source = str((universe_meta or {}).get("source") or "")
        snapshot_count = int(self._safe_float((universe_meta or {}).get("snapshot_count"), 0))
        is_fallback = source.startswith("fallback_") or snapshot_count <= 0
        if not is_fallback:
            return

        for pick in picks:
            breakdown = pick.get("score_breakdown") or {}
            penalty = 7.0
            if pick.get("money_flow_quality") != "real":
                penalty += 4.0
            if not pick.get("theme_tags") and not pick.get("matched_theme_ids"):
                penalty += 2.0
            raw_total = self._safe_float(breakdown.get("total"), 0)
            capped = min(raw_total - penalty, 78.0 if pick.get("money_flow_quality") != "real" else 82.0)
            breakdown["total"] = round(self._clamp(capped, 0, 100), 2)
            breakdown["universe_quality_penalty"] = round(penalty, 2)
            pick["score_breakdown"] = breakdown
            pick["score"] = breakdown["total"]
            pick["data_quality_warning"] = "全A快照不可用，当前来自兜底候选池；评分已按数据置信度降权。"
            if pick.get("action") == "buy" and pick.get("money_flow_quality") != "real":
                pick["action"] = "watch"
                pick["position_pct"] = round(self._safe_float(pick.get("position_pct"), 0) * 0.5, 2)
                risks = pick.setdefault("risks", [])
                warning = "数据源降级且资金流非真实数据，暂不升级为核心买入。"
                if warning not in risks:
                    risks.insert(0, warning)

    def apply_money_flow_to_pick(self, pick: Dict[str, Any], money_flow: Dict[str, Any]) -> Dict[str, Any]:
        quality = "proxy" if money_flow.get("quality") == "proxy" else "real"
        source = str(money_flow.get("source") or "remote")
        main_net_inflow_yi = self._safe_float(money_flow.get("main_net_inflow"), 0) / 100000000
        confidence = 1.0 if quality == "real" else 0.45

        metrics = pick.setdefault("market_metrics", {})
        old_flow_yi = self._safe_float(metrics.get("main_net_inflow_yi"), 0)
        metrics.update(
            {
                "main_net_inflow_yi": round(main_net_inflow_yi, 3),
                "money_flow_source": source,
                "money_flow_quality": quality,
                "money_flow_display_mode": "proxy" if quality == "proxy" else "normal",
            }
        )
        pick["money_flow_quality"] = quality
        pick["money_flow_confidence"] = confidence
        pick["money_flow_source"] = source
        pick["money_flow_display_mode"] = "proxy" if quality == "proxy" else "normal"

        breakdown = pick.get("score_breakdown") or {}
        old_flow_score = self._safe_float(breakdown.get("money_flow"), 50)
        flow_multiplier = 8 if quality == "real" else 3
        new_flow_score = self._clamp(50 + main_net_inflow_yi * flow_multiplier, 0, 100)
        breakdown["money_flow"] = round(new_flow_score, 2)
        breakdown["money_flow_repriced"] = True
        breakdown["money_flow_source"] = source
        total = self._safe_float(breakdown.get("total"), 0)
        breakdown["total"] = round(self._clamp(total + (new_flow_score - old_flow_score) * 0.08, 0, 100), 2)
        pick["score_breakdown"] = breakdown
        pick["score"] = breakdown["total"]

        reasons = pick.setdefault("reasons", [])
        label = "真实资金流" if quality == "real" else "代理资金强度"
        flow_text = (
            f"{label}净流入 {main_net_inflow_yi:.2f} 亿"
            if main_net_inflow_yi >= 0
            else f"{label}净流出 {abs(main_net_inflow_yi):.2f} 亿"
        )
        if flow_text not in reasons:
            reasons.append(flow_text)

        if quality == "real":
            risks = [
                risk for risk in (pick.get("risks") or [])
                if "资金流为代理或不可用" not in str(risk)
            ]
            if old_flow_yi >= 0 and main_net_inflow_yi < 0:
                risks.insert(0, "真实资金流转为净流出，需降低执行优先级。")
            pick["risks"] = risks

        return {
            "quality": quality,
            "source": source,
            "main_net_inflow_yi": main_net_inflow_yi,
            "old_flow_yi": old_flow_yi,
            "new_flow_score": new_flow_score,
        }

    def calibrate_pick_scores(self, picks: List[Dict[str, Any]], market_state: Dict[str, Any]) -> None:
        """Map raw model/rule scores into a stable display score."""
        if not picks:
            return

        raw_scores: List[float] = []
        for pick in picks:
            breakdown = pick.get("score_breakdown") or {}
            raw_total = self._safe_float(breakdown.get("total"), 0)
            breakdown["raw_total"] = round(raw_total, 2)
            pick["score_breakdown"] = breakdown
            raw_scores.append(raw_total)

        ordered = sorted(raw_scores)
        n = len(ordered)
        state_tag = str((market_state or {}).get("state_tag") or "neutral")
        state_adjust = -2.0 if state_tag == "defensive" else (1.0 if state_tag == "offensive" else 0.0)

        for pick in picks:
            breakdown = pick.get("score_breakdown") or {}
            raw_total = self._safe_float(breakdown.get("raw_total", breakdown.get("total")), 0)
            risk_adjusted = self._safe_float(breakdown.get("risk_adjusted"), 0)
            edge_pct = self._safe_float(pick.get("expected_edge_pct"), 0)
            profit_factor = self._safe_float(pick.get("profit_factor_proxy"), 1)

            up_score = self._safe_float(pick.get("up_prob"), 0) * 100
            anti_dd_score = (1 - self._safe_float(pick.get("dd_prob"), 1)) * 100
            edge_score = self._clamp(48 + edge_pct * 6.5, 0, 100)
            pf_score = self._clamp(45 + (profit_factor - 1) * 22, 0, 100)
            relative_score = 48 + self._percentile(raw_total, ordered, n) * 24
            quality_score = (
                up_score * 0.22
                + anti_dd_score * 0.20
                + risk_adjusted * 0.20
                + edge_score * 0.24
                + pf_score * 0.14
            )
            bonus = self._calibration_bonus(pick, edge_pct, profit_factor)
            display_total = self._clamp(
                raw_total * 0.34 + quality_score * 0.46 + relative_score * 0.20 + bonus + state_adjust,
                0,
                100,
            )
            breakdown["total"] = round(display_total, 2)
            breakdown["pre_theme_total"] = breakdown["total"]
            pick["score_breakdown"] = breakdown
            pick["score"] = breakdown["total"]

    def theme_adjustment(self, theme_score: float, reliable: bool) -> float:
        if not reliable:
            return 0.0
        theme_score = self._safe_float(theme_score, 0)
        if theme_score > 0:
            return round(self._clamp((theme_score - 55.0) * 0.10, -1.0, 4.5), 2)
        return -3.0

    def apply_theme_adjustment(self, pick: Dict[str, Any], theme_score: float, reliable: bool) -> None:
        breakdown = pick.setdefault("score_breakdown", {})
        score = self._safe_float(theme_score, 0)
        if "pre_theme_total" not in breakdown:
            breakdown["pre_theme_total"] = round(self._safe_float(breakdown.get("total"), pick.get("score") or 0), 2)
        base_total = self._safe_float(breakdown.get("pre_theme_total"), breakdown.get("total") or pick.get("score") or 0)
        adjustment = self.theme_adjustment(score, reliable)
        breakdown["theme"] = round(score, 2)
        breakdown["theme_adjustment"] = adjustment
        breakdown["total"] = round(self._clamp(base_total + adjustment, 0, 100), 2)
        pick["score_breakdown"] = breakdown
        pick["score"] = breakdown["total"]

    def _calibration_bonus(self, pick: Dict[str, Any], edge_pct: float, profit_factor: float) -> float:
        bonus = 0.0
        if pick.get("action") == "buy":
            bonus += 2.0
        confidence = str(pick.get("confidence_level") or "")
        if confidence == "high":
            bonus += 4.0
        elif confidence == "medium":
            bonus += 2.0
        flow_yi = self._safe_float((pick.get("market_metrics") or {}).get("main_net_inflow_yi"), 0)
        if flow_yi > 2:
            bonus += 2.0
        elif flow_yi < -1:
            bonus -= 4.0
        if self._safe_float(pick.get("dd_prob"), 1) <= 0.20:
            bonus += 1.0
        if edge_pct < 0.6:
            bonus -= 8.0
        elif edge_pct < 1.5:
            bonus -= 3.0
        if profit_factor < 1.15:
            bonus -= 6.0
        elif profit_factor < 1.30:
            bonus -= 2.0
        return bonus

    @staticmethod
    def _percentile(value: float, ordered: List[float], n: int) -> float:
        if n <= 1:
            return 0.5
        less = sum(1 for x in ordered if x < value)
        equal = sum(1 for x in ordered if x == value)
        return (less + 0.5 * equal) / n

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
