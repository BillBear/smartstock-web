"""
Presentation-oriented explainability helpers for model-scored picks.
"""
from __future__ import annotations

from typing import Any, Dict, List


class MLExplainService:
    """Builds a stable explanation payload from frozen pick snapshots."""

    @staticmethod
    def build_pick_explanation(pick: Dict[str, Any]) -> Dict[str, Any]:
        if not pick:
            return {"available": False, "message": "推荐不存在或尚未生成"}

        model_probability = pick.get("model_probability") or {}
        contributions: List[Dict[str, Any]] = pick.get("factor_contributions") or []
        positive = [row for row in contributions if row.get("direction") == "positive"]
        negative = [row for row in contributions if row.get("direction") == "negative"]
        positive.sort(key=lambda x: abs(float(x.get("contribution") or 0)), reverse=True)
        negative.sort(key=lambda x: abs(float(x.get("contribution") or 0)), reverse=True)

        if not model_probability:
            return {
                "available": False,
                "pick_id": pick.get("pick_id"),
                "symbol": pick.get("symbol"),
                "name": pick.get("name"),
                "message": "当前推荐尚未接入已训练机器学习模型，仍使用规则代理概率。",
                "probability_model": pick.get("probability_model"),
                "score_breakdown": pick.get("score_breakdown"),
            }

        return {
            "available": True,
            "pick_id": pick.get("pick_id"),
            "symbol": pick.get("symbol"),
            "name": pick.get("name"),
            "model_version_id": pick.get("model_version_id"),
            "model_probability": model_probability,
            "top_positive_factors": positive[:5],
            "top_negative_factors": negative[:5],
            "factor_contributions": contributions,
            "similar_sample_evidence": pick.get("similar_sample_evidence") or {},
            "calibration_metrics": pick.get("calibration_metrics") or {},
            "feature_snapshot": pick.get("feature_snapshot") or {},
            "score_breakdown": pick.get("score_breakdown") or {},
            "decision": pick.get("decision") or {},
            "explain_notes": [
                "贡献值表示该变量相对模型均值对“更值得买入”的边际影响。",
                "相似样本证据来自历史训练集，不是未来收益承诺。",
                "若模型状态不是 live_ready，系统仍应默认模拟验证。",
            ],
        }
