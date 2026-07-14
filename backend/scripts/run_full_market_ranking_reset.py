#!/usr/bin/env python3
"""Run one contract-bound stage of the full-market ranking reset."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import signal
import sys
import tempfile
import threading
import time
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
from app.evaluation.full_market_ml.ablation_stage import run_nested_ablation_stage
from app.evaluation.full_market_ml.ranking_stage import (
    run_baseline_oof_stage,
    run_ranker_oof_stage,
)
from app.evaluation.full_market_ml.risk_stage import run_risk_oof_stage
from app.evaluation.full_market_ml.controlled_stage import run_controlled_evaluation_stage
from app.evaluation.full_market_ml.research_preflight import (
    collect_research_evidence,
    evaluate_research_preflight,
)


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
DEFAULT_STAGE_TIMEOUTS_SECONDS = {
    "contract": 20 * 60,
    "label-audit": 60 * 60,
    "feature-evidence": 90 * 60,
    "baseline-oof": 45 * 60,
    "nested-ablation": 120 * 60,
    "ranker-oof": 120 * 60,
    "risk-oof": 60 * 60,
    "controlled-evaluation": 45 * 60,
    "closure": 20 * 60,
}
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
    "nested-ablation": (
        "app/evaluation/full_market_ml/ablation.py",
        "app/evaluation/full_market_ml/ablation_stage.py",
        "app/evaluation/full_market_ml/baseline_model.py",
        "app/evaluation/full_market_ml/feature_selection.py",
    ),
    "baseline-oof": (
        "app/evaluation/full_market_ml/ranking_model.py",
        "app/evaluation/full_market_ml/ranking_stage.py",
        "app/evaluation/full_market_ml/research_contract.py",
    ),
    "ranker-oof": (
        "app/evaluation/full_market_ml/ranking_model.py",
        "app/evaluation/full_market_ml/ranking_stage.py",
        "app/evaluation/full_market_ml/research_preflight.py",
        "app/evaluation/full_market_ml/splits.py",
    ),
    "risk-oof": (
        "app/evaluation/full_market_ml/risk_model.py",
        "app/evaluation/full_market_ml/risk_stage.py",
    ),
    "controlled-evaluation": (
        "app/evaluation/full_market_ml/controlled_stage.py",
        "app/evaluation/full_market_ml/evaluator.py",
    ),
}
STAGE_DEPENDENCIES = {
    "label-audit": "contract",
    "feature-evidence": "label-audit",
    "baseline-oof": "feature-evidence",
    "nested-ablation": "baseline-oof",
    "ranker-oof": "nested-ablation",
    "risk-oof": "nested-ablation",
    "controlled-evaluation": "risk-oof",
}


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
        heartbeat_interval_seconds: float = 30.0,
        stage_timeouts_seconds: Mapping[str, float] | None = None,
        rss_reader: Callable[[], float] | None = None,
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
        self.asset_root = Path(asset_root).resolve() if asset_root is not None else None
        self.heartbeat_interval_seconds = max(0.005, float(heartbeat_interval_seconds))
        self.stage_timeouts_seconds = {
            **DEFAULT_STAGE_TIMEOUTS_SECONDS,
            **dict(stage_timeouts_seconds or {}),
        }
        self.rss_reader = rss_reader or _process_rss_gb
        self._state_lock = threading.Lock()
        self._peak_rss_gb = 0.0
        self._monitor_failure: str | None = None
        if services is not None:
            self.services = dict(services)
        else:
            self.services = {"contract": _write_contract_artifact}
            if self.asset_root is not None:
                resolved_asset_root = self.asset_root
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
                self.services["nested-ablation"] = (
                    lambda contract, run_root, _stage: run_nested_ablation_stage(
                        contract, run_root
                    )
                )
                self.services["baseline-oof"] = (
                    lambda contract, run_root, _stage: run_baseline_oof_stage(
                        contract, run_root
                    )
                )
                self.services["ranker-oof"] = (
                    lambda contract, run_root, _stage: run_ranker_oof_stage(
                        contract, run_root
                    )
                )
                self.services["risk-oof"] = (
                    lambda contract, run_root, _stage: run_risk_oof_stage(
                        contract, run_root
                    )
                )
                self.services["controlled-evaluation"] = (
                    lambda contract, run_root, _stage: run_controlled_evaluation_stage(
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
        self._peak_rss_gb = max(0.0, float(self.rss_reader()))
        self._monitor_failure = None
        self._write_state(
            stage,
            self._state(stage, "running", {}, started_at=started_at),
            event="started",
        )
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(stage, stop),
            name=f"ranking-reset-{stage}-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        previous_alarm = self._start_timeout(stage)
        previous_termination = self._start_termination_handler()
        try:
            self._enforce_rss_limit()
            artifacts = dict(self.services[stage](self.contract, self.run_root, stage) or {})
            self._stop_monitor(stop, heartbeat)
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
            self._write_state(stage, state, event="complete")
            return state
        except BaseException as error:
            self._stop_monitor(stop, heartbeat)
            if isinstance(error, TimeoutError):
                terminal = "timeout"
            elif self._monitor_failure == "resource_exceeded" or isinstance(error, MemoryError):
                terminal = "resource_exceeded"
                if not isinstance(error, MemoryError):
                    error = MemoryError(
                        f"stage={stage} exceeded RSS limit {self.contract.rss_abort_gb:.2f} GB"
                    )
            elif isinstance(error, (KeyboardInterrupt, SystemExit)):
                terminal = "aborted"
            else:
                terminal = "failed"
            state = self._state(
                stage,
                terminal,
                {},
                started_at=started_at,
                ended_at=_now(),
                failure={"type": type(error).__name__, "message": str(error)},
            )
            self._write_state(stage, state, event=terminal)
            raise
        finally:
            self._stop_monitor(stop, heartbeat)
            self._stop_termination_handler(previous_termination)
            self._stop_timeout(previous_alarm)

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
            "elapsed_seconds": _elapsed_seconds(started_at, ended_at),
            "peak_rss_gb": float(self._peak_rss_gb),
            "pid": os.getpid(),
            "resume_command": self._resume_command(stage),
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
        if stage == "ranker-oof":
            preflight_path = (
                self.run_root / "artifacts" / "preflight" / "model" / "preflight_report.json"
            )
            if not preflight_path.is_file():
                raise RuntimeError("ranker-oof requires a completed model research preflight")
            preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
            if self.asset_root is None:
                raise RuntimeError("ranker-oof preflight verification requires --asset-root")
            current = evaluate_research_preflight(
                collect_research_evidence(
                    self.contract, self.run_root, self.asset_root, phase="model"
                ),
                expected_contract_sha=self.contract_sha256,
                phase="model",
            )
            if (
                preflight.get("contract_sha256") != self.contract_sha256
                or not preflight.get("passed")
                or not preflight.get("model_ready")
                or preflight != current
            ):
                raise RuntimeError("ranker-oof blocked by model research preflight")

    def _read_state(self, stage: str) -> dict[str, Any] | None:
        path = self._state_path(stage)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def _write_state(
        self, stage: str, state: Mapping[str, Any], *, event: str | None = None
    ) -> None:
        with self._state_lock:
            _write_json_atomic(self._state_path(stage), state)
            _write_json_atomic(self.run_root / "progress.json", state)
            log_path = self._state_path(stage).parent / "stage.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "at": _now(),
                            "event": event or str(state.get("status", "state")),
                            "status": state.get("status"),
                            "peak_rss_gb": state.get("peak_rss_gb"),
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                    + "\n"
                )

    def _heartbeat(self, stage: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval_seconds):
            rss = max(0.0, float(self.rss_reader()))
            self._peak_rss_gb = max(self._peak_rss_gb, rss)
            state = self._read_state(stage)
            if not state or state.get("status") != "running":
                return
            state["heartbeat_at"] = _now()
            state["peak_rss_gb"] = float(self._peak_rss_gb)
            state["elapsed_seconds"] = _elapsed_seconds(str(state["started_at"]), None)
            self._write_state(stage, state, event="heartbeat")
            if rss >= self.contract.rss_abort_gb:
                self._monitor_failure = "resource_exceeded"
                if hasattr(signal, "SIGTERM"):
                    os.kill(os.getpid(), signal.SIGTERM)
                return

    def _enforce_rss_limit(self) -> None:
        rss = max(0.0, float(self.rss_reader()))
        self._peak_rss_gb = max(self._peak_rss_gb, rss)
        if rss >= self.contract.rss_abort_gb:
            self._monitor_failure = "resource_exceeded"
            raise MemoryError(
                f"RSS limit exceeded: observed={rss:.3f}GB limit={self.contract.rss_abort_gb:.3f}GB"
            )

    def _start_timeout(self, stage: str):
        timeout = float(self.stage_timeouts_seconds.get(stage, 0.0))
        if (
            timeout <= 0
            or not hasattr(signal, "SIGALRM")
            or threading.current_thread() is not threading.main_thread()
        ):
            return None
        previous = signal.getsignal(signal.SIGALRM)

        def raise_timeout(_number, _frame):
            raise TimeoutError(f"stage={stage} exceeded timeout_seconds={timeout}")

        signal.signal(signal.SIGALRM, raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        return previous

    @staticmethod
    def _stop_timeout(previous) -> None:
        if previous is None or not hasattr(signal, "SIGALRM"):
            return
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    @staticmethod
    def _start_termination_handler():
        if (
            not hasattr(signal, "SIGTERM")
            or threading.current_thread() is not threading.main_thread()
        ):
            return None
        previous = signal.getsignal(signal.SIGTERM)

        def abort_stage(_number, _frame):
            raise KeyboardInterrupt("received SIGTERM")

        signal.signal(signal.SIGTERM, abort_stage)
        return previous

    @staticmethod
    def _stop_termination_handler(previous) -> None:
        if previous is not None and hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, previous)

    @staticmethod
    def _stop_monitor(stop: threading.Event, heartbeat: threading.Thread) -> None:
        stop.set()
        if heartbeat.is_alive() and heartbeat is not threading.current_thread():
            heartbeat.join(timeout=1.0)

    def _resume_command(self, stage: str) -> str:
        command = (
            f"python scripts/run_full_market_ranking_reset.py --config {self.config_path} "
            f"--run-root {self.run_root} --stage {stage} --resume"
        )
        if self.asset_root is not None:
            command += f" --asset-root {self.asset_root}"
        return command

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


def _elapsed_seconds(started_at: str, ended_at: str | None) -> float:
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(ended_at) if ended_at else datetime.now(timezone.utc)
    return max(0.0, float((end - start).total_seconds()))


def _process_rss_gb() -> float:
    usage = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024.0 ** 3 if sys.platform == "darwin" else 1024.0 ** 2
    return usage / divisor


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
