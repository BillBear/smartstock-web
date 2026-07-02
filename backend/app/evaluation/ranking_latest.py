"""Helpers for selecting production-grade ranking evaluation evidence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def _is_smoke_summary(payload: Dict[str, Any]) -> bool:
    coverage = payload.get("coverage") or {}
    return coverage.get("fixture") == "smoke" or payload.get("fixture") == "smoke"


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
            payload["production_evidence"] = False
            payload["evidence_type"] = "smoke"
            return payload
        payload["available"] = True
        payload["production_evidence"] = True
        payload["evidence_type"] = "real"
        return payload

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
