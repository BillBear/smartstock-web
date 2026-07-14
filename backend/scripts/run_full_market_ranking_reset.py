#!/usr/bin/env python3
"""Run one contract-bound stage of the full-market ranking reset."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.full_market_ml.research_contract import (
    RankingResearchContract,
    contract_from_mapping,
)
from app.evaluation.full_market_ml.label_stage import run_label_audit_stage
from app.evaluation.full_market_ml.feature_stage import run_feature_evidence_stage


RANKING_STAGES = (
    "contract",
    "label-audit",
    "feature-evidence",
    "baseline-oof",
    "nested-ablation",
    "ranker-oof",
    "risk-oof",
    "controlled-evaluation",
    "closure",
)
StageService = Callable[[RankingResearchContract, Path, str], Mapping[str, Any]]
STAGE_IMPLEMENTATION_FILES = {
    "contract": ("app/evaluation/full_market_ml/research_contract.py",),
    "label-audit": (
        "app/evaluation/full_market_ml/research_contract.py",
        "app/evaluation/full_market_ml/label_stage.py",
        "app/evaluation/full_market_ml/ranking_labels.py",
    ),
    "feature-evidence": (
        "app/evaluation/full_market_ml/research_contract.py",
        "app/evaluation/full_market_ml/feature_evidence.py",
        "app/evaluation/full_market_ml/feature_stage.py",
        "app/evaluation/full_market_ml/fundamental_features.py",
    ),
}
STAGE_DEPENDENCIES = {"label-audit": "contract", "feature-evidence": "label-audit"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--asset-root", default=os.environ.get("SMARTSTOCK_ASSET_ROOT"))
    parser.add_argument("--stage", required=True, choices=RANKING_STAGES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


class RankingResetRunner:
    def __init__(
        self,
        config_path: str | Path,
        run_root: str | Path,
        *,
        services: Mapping[str, StageService] | None = None,
        asset_root: str | Path | None = None,
    ):
        self.config_path = Path(config_path).resolve()
        self.run_root = Path(run_root).resolve()
        raw = self.config_path.read_bytes()
        self.config_sha256 = hashlib.sha256(raw).hexdigest()
        config = json.loads(raw.decode("utf-8"))
        if not isinstance(config, dict):
            raise ValueError("ranking reset config must be a JSON object")
        self.contract = contract_from_mapping(config, source_config_sha256=self.config_sha256)
        self.contract_sha256 = self.contract.sha256()
        if services is not None:
            self.services = dict(services)
        else:
            self.services = {"contract": _write_contract_artifact}
            if asset_root is not None:
                resolved_asset_root = Path(asset_root).resolve()
                self.services["label-audit"] = (
                    lambda contract, run_root, _stage: run_label_audit_stage(
                        contract, run_root, resolved_asset_root
                    )
                )
                self.services["feature-evidence"] = (
                    lambda contract, run_root, _stage: run_feature_evidence_stage(
                        contract, run_root, resolved_asset_root
                    )
                )

    def run(self, stage: str, *, resume: bool = False) -> dict[str, Any]:
        if stage not in RANKING_STAGES:
            raise ValueError(f"unknown ranking reset stage: {stage}")
        if stage not in self.services:
            raise RuntimeError(f"stage is not implemented: {stage}")
        self._require_predecessor(stage)
        existing = self._read_state(stage)
        if existing and existing.get("status") == "complete":
            if existing.get("contract_sha256") != self.contract_sha256:
                raise ValueError(f"stage contract changed after completion: {stage}")
            if not self._artifacts_valid(existing):
                raise ValueError(f"stage artifacts changed after completion: {stage}")
            if existing.get("implementation_sha256") != _implementation_sha256(stage):
                raise ValueError(f"stage implementation changed after completion: {stage}")
            if resume:
                return existing
            raise FileExistsError(f"stage already complete: {stage}; use --resume")

        started_at = _now()
        self._write_state(
            stage,
            self._state(stage, "running", {}, started_at=started_at),
        )
        try:
            artifacts = dict(self.services[stage](self.contract, self.run_root, stage) or {})
            status_overrides = artifacts.pop("_status", {})
            if status_overrides and not isinstance(status_overrides, Mapping):
                raise TypeError("stage _status override must be a mapping")
            state = self._state(
                stage,
                "complete",
                artifacts,
                started_at=started_at,
                ended_at=_now(),
                engineering_valid=True,
                research_design_valid=bool(status_overrides.get("research_design_valid", stage == "contract")),
                model_gate_passed=bool(status_overrides.get("model_gate_passed", False)),
            )
            self._write_state(stage, state)
            return state
        except BaseException as error:
            terminal = "aborted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
            state = self._state(
                stage,
                terminal,
                {},
                started_at=started_at,
                ended_at=_now(),
                failure={"type": type(error).__name__, "message": str(error)},
            )
            self._write_state(stage, state)
            raise

    def _state(
        self,
        stage: str,
        status: str,
        artifacts: Mapping[str, Any],
        *,
        started_at: str,
        ended_at: str | None = None,
        engineering_valid: bool = False,
        research_design_valid: bool = False,
        model_gate_passed: bool = False,
        failure: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "status": status,
            "contract_sha256": self.contract_sha256,
            "config_sha256": self.config_sha256,
            "implementation_sha256": _implementation_sha256(stage),
            "artifacts": dict(artifacts),
            "artifact_hashes": _artifact_hashes(artifacts),
            "engineering_valid": bool(engineering_valid),
            "research_design_valid": bool(research_design_valid),
            "model_gate_passed": bool(model_gate_passed),
            "production_candidate": False,
            "started_at": started_at,
            "ended_at": ended_at,
            "heartbeat_at": ended_at or _now(),
            "pid": os.getpid(),
            "failure": dict(failure) if failure else None,
        }

    def _state_path(self, stage: str) -> Path:
        return self.run_root / "stages" / stage / "stage_state.json"

    def _require_predecessor(self, stage: str) -> None:
        predecessor = STAGE_DEPENDENCIES.get(stage)
        if not predecessor:
            return
        state = self._read_state(predecessor)
        if not state or state.get("status") != "complete" or not state.get("research_design_valid"):
            raise RuntimeError(f"required predecessor is incomplete: {predecessor}")
        if state.get("contract_sha256") != self.contract_sha256:
            raise ValueError(f"required predecessor contract changed: {predecessor}")
        if state.get("implementation_sha256") != _implementation_sha256(predecessor):
            raise ValueError(f"required predecessor implementation changed: {predecessor}")
        if not self._artifacts_valid(state):
            raise ValueError(f"required predecessor artifacts changed: {predecessor}")

    def _read_state(self, stage: str) -> dict[str, Any] | None:
        path = self._state_path(stage)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _write_state(self, stage: str, state: Mapping[str, Any]) -> None:
        _write_json_atomic(self._state_path(stage), state)

    @staticmethod
    def _artifacts_valid(state: Mapping[str, Any]) -> bool:
        artifacts = state.get("artifacts", {})
        expected = state.get("artifact_hashes", {})
        return isinstance(artifacts, Mapping) and isinstance(expected, Mapping) and _artifact_hashes(artifacts) == dict(expected)


def _write_contract_artifact(
    contract: RankingResearchContract, run_root: Path, _stage: str
) -> Mapping[str, Any]:
    path = run_root / "artifacts" / "research_contract.json"
    _write_json_atomic(
        path,
        {"contract_sha256": contract.sha256(), "contract": contract.canonical_payload()},
    )
    return {"research_contract": str(path)}


def _artifact_hashes(artifacts: Mapping[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, value in artifacts.items():
        if not isinstance(value, str):
            continue
        path = Path(value)
        if path.is_file():
            hashes[str(name)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _implementation_sha256(stage: str) -> str:
    digest = hashlib.sha256()
    for relative in STAGE_IMPLEMENTATION_FILES.get(stage, ("scripts/run_full_market_ranking_reset.py",)):
        path = BACKEND_ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-", suffix=".tmp", delete=False
    ) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = RankingResetRunner(args.config, args.run_root, asset_root=args.asset_root)
    if args.dry_run:
        print(json.dumps({"stage": args.stage, "contract_sha256": runner.contract_sha256}, sort_keys=True))
        return 0
    state = runner.run(args.stage, resume=args.resume)
    print(json.dumps(state, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
