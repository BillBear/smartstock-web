"""Production readiness gates for ranking evaluation evidence."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


DEFAULT_PRODUCTION_GATE_THRESHOLDS = {
    "precision_at_3": 0.65,
    "precision_at_5": 0.60,
    "min_market_state_count": 3,
    "max_failed_market_states": 0,
    "recent_holdout_ratio": 0.80,
}


def evaluate_ranking_production_gate(
    summary: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate whether ranking evidence is sufficient for production promotion."""
    config = {**DEFAULT_PRODUCTION_GATE_THRESHOLDS, **(thresholds or {})}
    metrics = summary.get("metrics") or {}
    benchmarks = summary.get("benchmarks") or {}
    coverage = summary.get("coverage") or {}
    market_state_validation = summary.get("market_state_validation") or {}
    holdout_validation = summary.get("holdout_validation") or {}

    checks: List[Dict[str, Any]] = []

    _add_check(
        checks,
        key="coverage_status",
        actual=coverage.get("coverage_status"),
        threshold="complete",
        passed=coverage.get("coverage_status") == "complete",
        message="ranking evaluation coverage must be complete",
    )
    _add_numeric_check(
        checks,
        key="precision_at_3",
        actual=metrics.get("precision_at_3"),
        threshold=config["precision_at_3"],
        op="gte",
        message="Precision@3 must pass production threshold",
    )
    _add_numeric_check(
        checks,
        key="precision_at_5",
        actual=metrics.get("precision_at_5"),
        threshold=config["precision_at_5"],
        op="gte",
        message="Precision@5 must pass production threshold",
    )
    _add_numeric_check(
        checks,
        key="market_median_return_pct",
        actual=metrics.get("top_5_avg_return_pct"),
        threshold=benchmarks.get("market_median_return_pct"),
        op="gt",
        message="Top5 average return must beat full-market median",
    )
    _add_numeric_check(
        checks,
        key="baseline_top_5_avg_return_pct",
        actual=metrics.get("top_5_avg_return_pct"),
        threshold=benchmarks.get("baseline_top_5_avg_return_pct"),
        op="gt",
        message="Top5 average return must beat current baseline",
    )
    _add_numeric_check(
        checks,
        key="baseline_max_drawdown",
        actual=metrics.get("max_drawdown"),
        threshold=benchmarks.get("baseline_max_drawdown"),
        op="lte",
        message="Maximum drawdown must not be worse than baseline",
    )
    _add_numeric_check(
        checks,
        key="validated_market_state_count",
        actual=market_state_validation.get("validated_state_count"),
        threshold=config["min_market_state_count"],
        op="gte",
        message="At least three market states must be validated",
    )
    _add_numeric_check(
        checks,
        key="failed_market_state_count",
        actual=market_state_validation.get("failed_state_count"),
        threshold=config["max_failed_market_states"],
        op="lte",
        message="No validated market state may show obvious failure",
    )

    walk_forward_precision = _safe_float(holdout_validation.get("walk_forward_precision_at_5"))
    recent_holdout_precision = _safe_float(holdout_validation.get("recent_holdout_precision_at_5"))
    holdout_threshold = walk_forward_precision * float(config["recent_holdout_ratio"]) if walk_forward_precision is not None else None
    _add_numeric_check(
        checks,
        key="recent_holdout_vs_walk_forward",
        actual=recent_holdout_precision,
        threshold=holdout_threshold,
        op="gte",
        message="Recent holdout Precision@5 must remain at least 80% of walk-forward performance",
    )

    failed_checks = [item for item in checks if not item["passed"]]
    return {
        "schema_version": "production_gate_v1",
        "ready": len(failed_checks) == 0,
        "status": "passed" if not failed_checks else "blocked",
        "summary": (
            "Ranking evidence passes production promotion gates."
            if not failed_checks
            else "Ranking evidence is insufficient for production strategy changes."
        ),
        "thresholds": config,
        "checks": checks,
        "failed_checks": failed_checks,
        "policy": {
            "diagnostic_only": True,
            "does_not_change_strategy": True,
            "production_strategy_changes_require_separate_baseline": True,
        },
    }


def _add_numeric_check(
    checks: List[Dict[str, Any]],
    *,
    key: str,
    actual: Any,
    threshold: Any,
    op: str,
    message: str,
) -> None:
    actual_value = _safe_float(actual)
    threshold_value = _safe_float(threshold)
    if actual_value is None or threshold_value is None:
        _add_check(checks, key=key, actual=actual, threshold=threshold, passed=False, message=f"{message}; value missing")
        return
    if op == "gte":
        passed = actual_value >= threshold_value
    elif op == "gt":
        passed = actual_value > threshold_value
    elif op == "lte":
        passed = actual_value <= threshold_value
    else:
        passed = False
    _add_check(checks, key=key, actual=actual_value, threshold=threshold_value, passed=passed, message=message)


def _add_check(
    checks: List[Dict[str, Any]],
    *,
    key: str,
    actual: Any,
    threshold: Any,
    passed: bool,
    message: str,
) -> None:
    checks.append(
        {
            "key": key,
            "actual": actual,
            "threshold": threshold,
            "passed": bool(passed),
            "message": message,
        }
    )


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
