from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def build_local_ml_config(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build local-only ML training defaults without enabling production use."""
    payload = dict(payload or {})
    model_family = str(payload.get("model_family") or "local_core_v1")
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_root = Path(__file__).resolve().parents[3]
    output_root = Path(payload.get("output_root") or repo_root / "runtime" / "ml_runs" / model_family)
    artifact_root = Path(payload.get("artifact_root") or repo_root / "backend" / "data" / "ml_models" / model_family)

    return {
        "model_family": model_family,
        "run_id": str(payload.get("run_id") or f"{model_family}_{now}"),
        "model_display_name": str(payload.get("model_display_name") or "Local Core ML v1 - 700 symbols"),
        "train_start": str(payload.get("train_start") or "2025-01-01"),
        "train_end": str(payload.get("train_end") or datetime.now().strftime("%Y-%m-%d")),
        "target_valid_symbols": int(payload.get("target_valid_symbols") or 700),
        "oversample_symbols": int(payload.get("oversample_symbols") or 760),
        "min_formal_model_symbols": int(payload.get("min_formal_model_symbols") or 700),
        "pilot_symbols": int(payload.get("pilot_symbols") or 100),
        "sample_step": int(payload.get("sample_step") or 2),
        "primary_horizon": int(payload.get("primary_horizon") or 10),
        "auxiliary_horizons": [5, 20],
        "exclude_news_features": bool(payload.get("exclude_news_features", True)),
        "exclude_market_state_features": bool(payload.get("exclude_market_state_features", True)),
        "production_enabled": False,
        "status": "paper_only",
        "seed": int(payload.get("seed") or 20260704),
        "output_root": str(output_root),
        "artifact_root": str(artifact_root),
        "min_disk_free_gb": int(payload.get("min_disk_free_gb") or 50),
        "min_memory_gb": int(payload.get("min_memory_gb") or 12),
        "min_full_snapshot_count": int(payload.get("min_full_snapshot_count") or 5000),
        "history_retry_count": int(payload.get("history_retry_count") or 2),
        "history_retry_sleep_seconds": float(payload.get("history_retry_sleep_seconds") or 1.5),
        "history_inter_request_sleep_seconds": float(payload.get("history_inter_request_sleep_seconds") or 0.12),
        "history_circuit_sleep_seconds": float(payload.get("history_circuit_sleep_seconds") or 65.0),
        "history_fetch_workers": int(payload.get("history_fetch_workers") or 1),
    }
