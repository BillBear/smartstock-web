from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def review_local_ml_run(run_dir: str | Path) -> Dict[str, Any]:
    root = Path(run_dir)
    dataset_meta = _read_json(root / "dataset_meta.json")
    feature_audit = _read_json(root / "feature_audit.json")
    model_comparison = _read_json(root / "model_comparison.json")
    review = build_training_review(dataset_meta, feature_audit, model_comparison)
    (root / "post_run_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "post_run_review.md").write_text(_review_markdown(review), encoding="utf-8")
    (root / "next_run_recommendations.json").write_text(
        json.dumps(review["next_run_recommendations"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return review


def build_training_review(
    dataset_meta: Dict[str, Any],
    feature_audit: Dict[str, Any],
    model_comparison: Dict[str, Any],
) -> Dict[str, Any]:
    valid_symbols = int(dataset_meta.get("valid_symbol_count") or dataset_meta.get("actual_valid_symbols") or 0)
    required_symbols = int(dataset_meta.get("required_valid_symbol_count") or 700)
    sample_count = int(dataset_meta.get("sample_count") or 0)
    leakage = list(feature_audit.get("leakage_violations") or [])
    best_model = str(model_comparison.get("best_model") or "")
    models = model_comparison.get("models") or {}
    best = models.get(best_model) or {}
    baseline = models.get("logistic_baseline") or {}
    blocking = []
    warnings = []

    if valid_symbols < required_symbols:
        blocking.append(f"valid_symbols_below_{required_symbols}")
    if leakage:
        blocking.append("feature_leakage_detected")
    if sample_count < 100000:
        warnings.append("sample_count_below_100000")

    best_final_p5 = _metric(best, "final_holdout", "precision_at_5")
    best_stock_p5 = _metric(best, "stock_holdout", "precision_at_5")
    baseline_final_p5 = _metric(baseline, "final_holdout", "precision_at_5")
    baseline_stock_p5 = _metric(baseline, "stock_holdout", "precision_at_5")
    if best_model and best_model != "logistic_baseline":
        if best_final_p5 <= baseline_final_p5 or best_stock_p5 <= baseline_stock_p5:
            warnings.append("best_model_does_not_beat_logistic_on_holdouts")
        if best_stock_p5 < best_final_p5 * 0.8:
            warnings.append("stock_holdout_materially_weaker_than_final_holdout")
    elif best_model == "logistic_baseline":
        warnings.append("no_candidate_beat_logistic_baseline")

    if blocking:
        recommendation = "blocked"
    elif warnings:
        recommendation = "rerun_with_changes"
    else:
        recommendation = "promote_to_observation"

    return {
        "recommendation": recommendation,
        "blocking_reasons": blocking,
        "warnings": warnings,
        "valid_symbol_count": valid_symbols,
        "required_valid_symbol_count": required_symbols,
        "sample_count": sample_count,
        "best_model": best_model,
        "metrics": {
            "best_final_precision_at_5": best_final_p5,
            "best_stock_precision_at_5": best_stock_p5,
            "baseline_final_precision_at_5": baseline_final_p5,
            "baseline_stock_precision_at_5": baseline_stock_p5,
        },
        "top_feature_findings": _feature_findings(feature_audit, "core_candidate"),
        "weak_feature_findings": _feature_findings(feature_audit, "weak_or_unstable"),
        "next_run_recommendations": _next_run_recommendations(
            recommendation,
            blocking,
            warnings,
            feature_audit,
            primary_label=str(dataset_meta.get("primary_label") or "label_top20_10d"),
        ),
        "production_status": "paper_only",
    }


def _next_run_recommendations(
    recommendation: str,
    blocking: List[str],
    warnings: List[str],
    feature_audit: Dict[str, Any],
    primary_label: str = "label_top20_10d",
) -> Dict[str, Any]:
    return {
        "decision": recommendation,
        "sample_adjustments": _sample_adjustments(blocking, warnings),
        "feature_adjustments": _feature_adjustments(feature_audit),
        "label_adjustments": [
            {
                "current_label": str(primary_label),
                "next_test": "compare stricter rank, excess-return, tp-before-sl, and drawdown-safe labels only in a new explicit run config",
            }
        ],
        "model_adjustments": [
            {
                "model": "xgboost_classifier/lightgbm_classifier",
                "next_run_change": "use only if local OpenMP runtime is available; otherwise keep sklearn candidates",
            }
        ],
        "blocked_actions": ["do_not_change_production_strategy_until_multiple_runs_pass"],
    }


def _sample_adjustments(blocking: List[str], warnings: List[str]) -> List[Dict[str, str]]:
    result = []
    symbol_block = next((item for item in blocking if item.startswith("valid_symbols_below_")), None)
    if symbol_block:
        result.append({"reason": symbol_block, "next_run_change": "increase oversample_symbols before rerunning"})
    if "sample_count_below_100000" in warnings:
        result.append({"reason": "sample_count_below_100000", "next_run_change": "extend train_start or lower sample_step"})
    return result


def _feature_adjustments(feature_audit: Dict[str, Any]) -> List[Dict[str, str]]:
    result = []
    for name, metrics in (feature_audit.get("features") or {}).items():
        classification = str(metrics.get("classification") or "")
        decision = "keep" if classification == "core_candidate" else "exclude_or_audit"
        result.append({"feature": name, "decision": decision, "evidence": classification})
    return result


def _feature_findings(feature_audit: Dict[str, Any], classification: str) -> List[str]:
    return [
        name
        for name, metrics in (feature_audit.get("features") or {}).items()
        if metrics.get("classification") == classification
    ][:20]


def _metric(model: Dict[str, Any], section: str, key: str) -> float:
    try:
        return float(((model.get(section) or {}).get(key)) or 0.0)
    except Exception:
        return 0.0


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _review_markdown(review: Dict[str, Any]) -> str:
    lines = [
        "# Local Core ML V1 Training Review",
        "",
        f"recommendation: {review.get('recommendation')}",
        f"production_status: {review.get('production_status')}",
        f"valid_symbol_count: {review.get('valid_symbol_count')}",
        f"sample_count: {review.get('sample_count')}",
        f"best_model: {review.get('best_model')}",
        "",
        "## Metrics",
    ]
    for key, value in (review.get("metrics") or {}).items():
        lines.append(f"- {key}: {value}")
    if review.get("blocking_reasons"):
        lines.extend(["", "## Blocking Reasons"])
        lines.extend([f"- {item}" for item in review["blocking_reasons"]])
    if review.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend([f"- {item}" for item in review["warnings"]])
    lines.extend(["", "## Next Run", "See `next_run_recommendations.json`."])
    return "\n".join(lines) + "\n"
