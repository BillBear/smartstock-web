"""Helpers for selecting production-grade ranking evaluation evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


MIN_PRODUCTION_COVERED_DATES = 30


def _is_smoke_summary(payload: Dict[str, Any]) -> bool:
    coverage = payload.get("coverage") or {}
    return coverage.get("fixture") == "smoke" or payload.get("fixture") == "smoke"


def annotate_ranking_evidence_readiness(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Classify whether a ranking report is usable as production strategy evidence."""
    output = dict(payload or {})
    coverage = output.get("coverage") or {}
    blocking_reasons = []
    coverage_status = str(coverage.get("coverage_status") or "")
    covered_date_count = _safe_int(coverage.get("covered_date_count"), 0)
    candidate_row_count = _safe_int(output.get("candidate_row_count"), 0)
    fixture = _is_smoke_summary(output)
    summary_metrics = output.get("summary_metrics") or output.get("metrics") or {}

    if fixture:
        blocking_reasons.append("fixture_smoke")
    if coverage_status and coverage_status != "complete":
        blocking_reasons.append(f"coverage_status_{coverage_status}")
    if covered_date_count < MIN_PRODUCTION_COVERED_DATES:
        blocking_reasons.append(f"covered_dates_below_{MIN_PRODUCTION_COVERED_DATES}")
    if candidate_row_count <= 0:
        blocking_reasons.append("candidate_rows_empty")

    ready = not blocking_reasons
    output["summary_metrics"] = summary_metrics
    output["coverage_status"] = coverage_status or None
    output["covered_date_count"] = covered_date_count
    output["requested_date_count"] = _safe_int(coverage.get("requested_date_count"), 0)
    output["report_path"] = output.get("report_path") or output.get("summary_path")
    output["readiness_blockers"] = blocking_reasons
    output["production_evidence"] = ready
    output["evidence_type"] = "real" if ready else ("smoke" if fixture else "real_insufficient")
    output["evidence_readiness"] = {
        "status": "ready" if ready else "insufficient",
        "production_evidence": ready,
        "blocking_reasons": blocking_reasons,
        "covered_date_count": covered_date_count,
        "required_covered_date_count": MIN_PRODUCTION_COVERED_DATES,
        "coverage_status": coverage_status or None,
        "candidate_row_count": candidate_row_count,
    }
    return output


def load_latest_ranking_summary(runs_dir: Path, include_fixture: bool = False) -> Dict[str, Any]:
    """Load latest ranking summary, skipping smoke fixtures unless explicitly requested."""
    root = Path(runs_dir)
    if not root.exists():
        return {
            "available": False,
            "message": "ranking evaluation report not found",
            "production_evidence": False,
            "evidence_type": "missing",
        }

    summaries = sorted(
        root.glob("*/ranking_summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    latest_smoke = None
    for path in summaries:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["summary_path"] = str(path)
        if _is_smoke_summary(payload):
            latest_smoke = latest_smoke or payload
            if not include_fixture:
                continue
            payload["available"] = True
            return annotate_ranking_evidence_readiness(payload)
        payload["available"] = True
        return annotate_ranking_evidence_readiness(payload)

    if latest_smoke:
        return {
            "available": False,
            "message": "only smoke ranking evaluation reports found; run real historical evaluation",
            "production_evidence": False,
            "evidence_type": "smoke_only",
            "latest_smoke_run_id": latest_smoke.get("run_id"),
            "latest_smoke_summary_path": latest_smoke.get("summary_path"),
        }
    return {
        "available": False,
        "message": "ranking evaluation report not found",
        "production_evidence": False,
        "evidence_type": "missing",
    }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
