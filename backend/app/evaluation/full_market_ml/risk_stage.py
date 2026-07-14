"""Contract-bound severe-risk OOF stage."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .ranking_stage import _load_matrix
from .research_contract import RankingResearchContract
from .risk_model import run_risk_oof


def run_risk_oof_stage(contract: RankingResearchContract, run_root: Path) -> dict[str, Any]:
    risk_schema = next((schema for name, schema in contract.feature_blocks if name == "risk_path"), ())
    if not risk_schema:
        raise ValueError("registered contract has no risk_path feature block")
    rows, split = _load_matrix(run_root, list(risk_schema))
    result = run_risk_oof(rows, split, risk_schema)
    artifact_root = run_root / "artifacts" / "risk-oof"
    prediction_path = artifact_root / "risk_predictions.parquet"
    report_path = artifact_root / "risk_report.json"
    artifact_root.mkdir(parents=True, exist_ok=True)
    predictions = result.pop("predictions")
    predictions.to_parquet(prediction_path, compression="zstd", index=False)
    report = {
        "contract_sha256": contract.sha256(),
        "split_sha256": split.split_sha256,
        "feature_schema": list(risk_schema),
        **result,
    }
    _write_json(report_path, report)
    return {
        "risk_predictions": str(prediction_path),
        "risk_report": str(report_path),
        "_status": {
            "research_design_valid": True,
            "model_gate_passed": bool(result["gate_passed"]),
        },
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
