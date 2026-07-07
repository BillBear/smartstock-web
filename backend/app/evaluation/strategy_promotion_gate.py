from __future__ import annotations

from typing import Any, Dict, List


def evaluate_promotion_gate(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate whether evidence is sufficient to plan a production strategy change."""
    reasons: List[str] = []
    if int(metrics.get("complete_label_date_count", 0) or 0) < 30:
        reasons.append("complete_label_date_count_below_30")
    if float(metrics.get("test_precision_at_5", 0.0) or 0.0) < 0.60:
        reasons.append("test_precision_at_5_below_0_60")
    if float(metrics.get("test_top5_return_after_cost", 0.0) or 0.0) <= float(metrics.get("baseline_top5_return_after_cost", 0.0) or 0.0):
        reasons.append("top5_return_after_cost_not_above_baseline")
    if int(metrics.get("closed_roundtrip_count", 0) or 0) < 20:
        reasons.append("closed_roundtrip_count_below_required")
    if metrics.get("max_drawdown_not_worse_than_baseline") is not True:
        reasons.append("max_drawdown_worse_or_missing")
    if int(metrics.get("market_state_fail_count", 0) or 0) > 0:
        reasons.append("market_state_failure_detected")
    if metrics.get("full_market_feature_scope") is False:
        reasons.append("full_market_feature_scope_missing")
    if metrics.get("ml_v2_2_training_allowed") is not True:
        reasons.append("ml_v2_2_training_not_allowed")
    if metrics.get("ml_decision") == "prefer_rule_baseline_over_ml_for_now":
        reasons.append("ml_prefer_rule_baseline_over_ml")
    return {
        "passed": not reasons,
        "blocking_reasons": reasons,
        "production_action": "allow_strategy_change_plan" if not reasons else "do_not_change_strategy",
    }
