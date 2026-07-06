"""Offline recall experiment comparison helpers.

This module compares precomputed ranking-evaluation summaries. It does not run
or mutate production selection, ranking, buy/sell, stop, or position logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_EXPERIMENTS: List[Dict[str, Any]] = [
    {
        "key": "baseline",
        "label": "baseline: current production replay",
        "recall_size": 220,
        "deep_analysis_size": 72,
        "recall_method": "production_pre_score",
    },
    {
        "key": "recall_220_deep_150",
        "label": "experiment A: recall 220, deep analysis 150",
        "recall_size": 220,
        "deep_analysis_size": 150,
        "recall_method": "production_pre_score",
    },
    {
        "key": "recall_300_deep_300",
        "label": "experiment B: recall 300, deep analysis 300",
        "recall_size": 300,
        "deep_analysis_size": 300,
        "recall_method": "production_pre_score",
    },
    {
        "key": "recall_500_deep_500",
        "label": "experiment C: recall 500, deep analysis 500",
        "recall_size": 500,
        "deep_analysis_size": 500,
        "recall_method": "production_pre_score",
    },
    {
        "key": "production_cap_240",
        "label": "funnel ablation: production-style industry cap, recall 240",
        "recall_size": 240,
        "deep_analysis_size": 240,
        "recall_method": "production_pre_score",
        "industry_cap_mode": "pre_recall",
        "industry_cap": 16,
    },
    {
        "key": "no_industry_cap_240",
        "label": "funnel ablation: no industry cap, recall 240",
        "recall_size": 240,
        "deep_analysis_size": 240,
        "recall_method": "production_pre_score",
        "industry_cap_mode": "none",
    },
    {
        "key": "no_industry_cap_500",
        "label": "funnel ablation: no industry cap, recall 500",
        "recall_size": 500,
        "deep_analysis_size": 500,
        "recall_method": "production_pre_score",
        "industry_cap_mode": "none",
    },
    {
        "key": "multi_channel_union",
        "label": "experiment D: multi-channel recall union",
        "recall_size": 500,
        "deep_analysis_size": 500,
        "recall_method": "multi_channel_union",
        "channels": [
            "trend_breakout",
            "pullback_repair",
            "theme_strength",
            "volume_price_acceleration",
            "money_flow_activity",
            "low_drawdown_stability",
        ],
    },
]

METRIC_FIELDS = [
    "precision_at_3",
    "precision_at_5",
    "ndcg_at_10",
    "top_5_avg_return_pct",
    "max_drawdown",
]

METRIC_ALIASES = {
    "top_5_avg_return_pct": ["top_5_avg_return_10d"],
}

CONTEXT_FIELDS = [
    "strategy_code",
    "risk_level",
    "start_date",
    "end_date",
    "horizons",
    "top_k_values",
    "label_config",
    "execution_config",
]


def build_recall_experiment_report(
    experiment_root: Path,
    experiments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compare offline recall experiment summaries from a directory."""
    root = Path(experiment_root)
    matrix = [dict(item) for item in (experiments or DEFAULT_EXPERIMENTS)]
    rows = []
    missing = []
    for item in matrix:
        key = item["key"]
        summary = _load_summary(root, key)
        if summary is None:
            missing.append(key)
        rows.append(_build_row(item, summary))

    baseline = next((row for row in rows if row["key"] == "baseline" and row.get("available")), None)
    incompatible = _mark_compatibility(rows, baseline)
    winner = _select_winner(rows, baseline) if baseline and not missing and not incompatible else None
    blocking_reasons = []
    if missing:
        blocking_reasons.append("missing_experiment_reports")
    if not baseline:
        blocking_reasons.append("baseline_report_missing")
    if incompatible:
        blocking_reasons.append("incompatible_experiment_reports")
    if winner is None:
        blocking_reasons.append("no_variant_passed_gates")

    ready = not blocking_reasons
    return {
        "schema_version": "1.0",
        "artifact_type": "recall_experiment_comparison",
        "status": "ready" if ready else "blocked",
        "production_switch_ready": ready,
        "blocking_reasons": blocking_reasons,
        "experiments": rows,
        "winner": winner,
        "summary": {
            "required_experiment_count": len(matrix),
            "available_experiment_count": sum(1 for row in rows if row.get("available")),
            "missing_experiment_keys": missing,
        },
        "guardrails": {
            "production_logic_unchanged": True,
            "requires_manual_strategy_review": True,
            "switch_requires_baseline_evidence": True,
        },
    }


def write_recall_experiment_report(report: Dict[str, Any], output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _load_summary(root: Path, experiment_key: str) -> Optional[Dict[str, Any]]:
    candidates = [
        root / experiment_key / "ranking_summary.json",
        root / f"{experiment_key}.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def _build_row(experiment: Dict[str, Any], summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    row = dict(experiment)
    row["available"] = summary is not None
    if summary is None:
        row["evidence_status"] = "missing"
        row["compatibility_status"] = "missing"
        row["metrics"] = {}
        return row
    row["context"] = _summary_context(summary)
    row["compatibility_status"] = "unchecked"
    readiness = summary.get("evidence_readiness") or {}
    production_evidence = bool(summary.get("production_evidence") or readiness.get("production_evidence"))
    row["evidence_status"] = readiness.get("status") or ("ready" if production_evidence else "insufficient")
    row["production_evidence"] = production_evidence
    row["candidate_row_count"] = int(summary.get("candidate_row_count") or 0)
    row["coverage"] = summary.get("coverage") or {}
    row["funnel_summary"] = row["coverage"].get("funnel_summary") or {}
    metrics = summary.get("metrics") or {}
    row["metrics"] = {field: _metric_value(metrics, field) for field in METRIC_FIELDS}
    return row


def _mark_compatibility(rows: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]]) -> List[str]:
    if not baseline:
        return []
    baseline_context = baseline.get("context") or {}
    incompatible = []
    for row in rows:
        if row.get("key") == "baseline":
            row["compatibility_status"] = "baseline"
            row["compatibility_issues"] = []
            continue
        if not row.get("available"):
            continue
        issues = _context_issues(baseline_context, row.get("context") or {})
        row["compatibility_issues"] = issues
        if issues:
            row["compatibility_status"] = "incompatible"
            row["evidence_status"] = "incompatible"
            row["production_evidence"] = False
            incompatible.append(row["key"])
        else:
            row["compatibility_status"] = "compatible"
    return incompatible


def _summary_context(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {field: summary.get(field) for field in CONTEXT_FIELDS if summary.get(field) is not None}


def _context_issues(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> List[str]:
    issues = []
    for field in CONTEXT_FIELDS:
        if field not in baseline or field not in candidate:
            continue
        if _canonical_value(baseline.get(field)) != _canonical_value(candidate.get(field)):
            issues.append(f"{field}_mismatch")
    return issues


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    return value


def _select_winner(rows: List[Dict[str, Any]], baseline: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates = []
    for row in rows:
        if row["key"] == "baseline" or not row.get("available"):
            continue
        if row.get("compatibility_status") == "incompatible":
            continue
        if not row.get("production_evidence"):
            continue
        deltas = _metric_deltas(row, baseline)
        if _passes_switch_gates(row, baseline, deltas):
            candidate = dict(row)
            candidate["deltas"] = deltas
            candidates.append(candidate)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            row["deltas"].get("precision_at_3", 0.0),
            row["deltas"].get("ndcg_at_10", 0.0),
            row["deltas"].get("top_5_avg_return_pct", 0.0),
        ),
        reverse=True,
    )[0]


def _metric_deltas(row: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, float]:
    metrics = row.get("metrics") or {}
    baseline_metrics = baseline.get("metrics") or {}
    return {field: round(_safe_float(metrics.get(field)) - _safe_float(baseline_metrics.get(field)), 6) for field in METRIC_FIELDS}


def _passes_switch_gates(row: Dict[str, Any], baseline: Dict[str, Any], deltas: Dict[str, float]) -> bool:
    metrics = row.get("metrics") or {}
    baseline_metrics = baseline.get("metrics") or {}
    return all(
        [
            _safe_float(metrics.get("precision_at_3")) >= 0.65,
            _safe_float(metrics.get("precision_at_5")) >= 0.60,
            deltas.get("precision_at_3", 0.0) > 0.0,
            deltas.get("ndcg_at_10", 0.0) > 0.0,
            deltas.get("top_5_avg_return_pct", 0.0) > 0.0,
            _safe_float(metrics.get("max_drawdown")) <= _safe_float(baseline_metrics.get("max_drawdown")),
        ]
    )


def _metric_value(metrics: Dict[str, Any], field: str) -> float:
    candidates = [field] + METRIC_ALIASES.get(field, [])
    for key in candidates:
        if key in metrics:
            return _safe_float(metrics.get(key))
    return 0.0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
