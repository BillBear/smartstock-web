"""Resumable, hash-verified orchestration for the full-market ML workflow.

This module owns stage state only.  Collection, quality, feature, training, and
evaluation decisions remain in their established modules or injected adapters.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    import resource
except ImportError:  # pragma: no cover - resource is unavailable on Windows.
    resource = None

from .quality import TrainingBlockedError


STAGES = (
    "preflight",
    "probe",
    "pilot-build",
    "full-build",
    "feature-audit",
    "dev-train",
    "final-evaluate",
    "final-fit",
    "final-holdout-evaluate",
)
DEFAULT_STAGE_TIMEOUTS_SECONDS = {
    "preflight": 15 * 60,
    "probe": 15 * 60,
    "pilot-build": 90 * 60,
    "full-build": 90 * 60,
    "feature-audit": 60 * 60,
    "dev-train": 45 * 60,
    "final-evaluate": 15 * 60,
    "final-fit": 30 * 60,
    "final-holdout-evaluate": 30 * 60,
}
FORMAL_DOWNSTREAM_STAGES = {"final-fit", "final-holdout-evaluate"}


def select_probe_dates(open_dates: list[str] | tuple[str, ...], count: int = 5) -> tuple[str, ...]:
    """Return the final ``count`` verified open sessions for a bounded probe."""
    dates = tuple(sorted({str(value) for value in open_dates if str(value)}))
    if len(dates) < count:
        raise ValueError(f"probe requires at least {count} open trading dates")
    return dates[-count:]


class FrozenModelMismatchError(PermissionError):
    """Raised when final evaluation is not bound to the frozen candidate."""


@dataclass(frozen=True)
class PipelineRunResult:
    stage: str
    reused_stages: list[str]
    stage_states: dict[str, dict[str, Any]]


StageService = Callable[[Any, Path, Mapping[str, Any]], Mapping[str, Any] | None]


class FullMarketMLPipeline:
    """Run immutable stages in order, refusing hash or quality-gate bypasses."""

    def __init__(
        self,
        config: Any,
        runtime_root: str | Path,
        services: Mapping[str, StageService],
        *,
        heartbeat_interval_seconds: float = 30.0,
        stage_timeouts_seconds: Mapping[str, float] | None = None,
    ):
        self.config = config
        self.runtime_root = Path(runtime_root)
        self.services = dict(services)
        self.heartbeat_interval_seconds = max(0.001, float(heartbeat_interval_seconds))
        self.stage_timeouts_seconds = {**DEFAULT_STAGE_TIMEOUTS_SECONDS, **dict(stage_timeouts_seconds or {})}
        missing = [stage for stage in STAGES if stage not in self.services]
        if missing:
            raise ValueError("missing pipeline stage services: " + ", ".join(missing))

    def run(self, stage: str, *, resume: bool = False, frozen_model_sha: str | None = None) -> PipelineRunResult:
        if stage not in STAGES:
            raise ValueError("stage must be one of " + ", ".join(STAGES))
        if frozen_model_sha is not None and stage not in {"final-evaluate", "final-fit", "final-holdout-evaluate"}:
            raise ValueError("frozen_model_sha is only accepted for final evaluation stages")

        states: dict[str, dict[str, Any]] = {}
        reused: list[str] = []
        for current in STAGES[: STAGES.index(stage) + 1]:
            inputs = self._input_hashes(current, states)
            self._require_formal_stage_inputs(current)
            existing = self._load_state(current)
            if self._is_reusable(existing, inputs) and (resume or current != stage):
                states[current] = existing
                reused.append(current)
                continue
            if existing and existing.get("status") == "complete":
                raise ValueError(f"stage already complete: {current}; rerun with resume")

            if current in {"final-evaluate", "final-fit", "final-holdout-evaluate"}:
                self._require_frozen_sha(frozen_model_sha)
            states[current] = self._run_stage(current, inputs, states)

        return PipelineRunResult(stage=stage, reused_stages=reused, stage_states=states)

    def stage_state(self, stage: str) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError("unknown stage")
        state = self._load_state(stage)
        if state is None:
            raise FileNotFoundError(self._state_path(stage))
        return state

    def status_report(self) -> dict[str, Any]:
        """Return a read-only, machine-readable view of this run's recovery state."""
        return self.inspect_runtime(self.runtime_root)

    @classmethod
    def inspect_runtime(cls, runtime_root: str | Path) -> dict[str, Any]:
        """Read status without constructing services or touching data providers."""
        root = Path(runtime_root)
        registry_path = root / "artifacts" / "full-build" / "dataset_registry.json"
        progress_path = root / "progress.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
        progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.is_file() else None
        stages = {}
        for stage in STAGES:
            path = root / "stages" / stage / "stage_state.json"
            stages[stage] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"status": "not_started"}
        return {
            "run_id": root.name,
            "runtime_root": str(root),
            "dataset_id": registry.get("dataset_id"),
            "progress": progress,
            "stages": stages,
        }

    def abort_stage(self, stage: str, *, reason: str) -> dict[str, Any]:
        """Close an interrupted stage without deleting its immutable inputs."""
        existing = self.stage_state(stage)
        if existing.get("status") != "running":
            raise ValueError(f"only a running stage can be aborted: {stage}")
        aborted = self._state(
            stage,
            "aborted",
            existing.get("input_hashes", {}),
            existing.get("artifacts", {}),
            started_at=str(existing.get("started_at", _timestamp())),
            ended_at=_timestamp(),
            failure_details={"type": "AbortedStage", "message": str(reason)},
        )
        self._write_json(self._state_path(stage), aborted)
        self._write_progress(aborted)
        self._append_stage_log(stage, "aborted", aborted)
        return aborted

    def recover_stale_stages(self, *, max_idle_seconds: int, now: str | None = None) -> list[str]:
        """Mark abandoned running stages as timeouts without touching their artifacts."""
        current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        recovered = []
        for stage in STAGES:
            existing = self._load_state(stage)
            if not existing or existing.get("status") != "running":
                continue
            heartbeat = str(existing.get("heartbeat_at") or existing.get("started_at") or "")
            try:
                idle_seconds = (current - datetime.fromisoformat(heartbeat)).total_seconds()
            except ValueError:
                idle_seconds = float("inf")
            if idle_seconds <= max(0, int(max_idle_seconds)):
                continue
            timeout = self._state(
                stage,
                "timeout",
                existing.get("input_hashes", {}),
                existing.get("artifacts", {}),
                started_at=str(existing.get("started_at", _timestamp())),
                ended_at=current.isoformat(),
                failure_details={"type": "StageTimeout", "message": f"heartbeat_idle_seconds={int(idle_seconds)}"},
            )
            self._write_json(self._state_path(stage), timeout)
            self._write_progress(timeout)
            self._append_stage_log(stage, "timeout", timeout)
            recovered.append(stage)
        return recovered

    def _run_stage(self, stage: str, inputs: dict[str, str], states: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        started = _timestamp()
        running = self._state(stage, "running", inputs, {}, started_at=started)
        self._write_json(self._state_path(stage), running)
        self._write_progress(running)
        self._append_stage_log(stage, "started", running)
        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_until_stopped,
            args=(stage, stop_heartbeat),
            name=f"ml-heartbeat-{stage}",
            daemon=True,
        )
        heartbeat.start()
        previous_alarm = self._start_stage_timer(stage)
        try:
            artifacts = {name: state.get("artifacts", {}) for name, state in states.items()}
            output = dict(self.services[stage](self.config, self.runtime_root, artifacts) or {})
            if output.get("quality_ready") is False:
                blocking_codes = tuple(str(code) for code in output.get("blocking_codes", ("quality_gate_blocked",)))
                raise TrainingBlockedError(blocking_codes)
            if stage == "dev-train":
                frozen = str(output.get("frozen_model_sha", "")).strip()
                if not frozen:
                    raise ValueError("dev-train service must return frozen_model_sha")
                manifest = dict(output.get("frozen_model_manifest") or {"frozen_model_sha": frozen})
                if str(manifest.get("frozen_model_sha", "")).strip() != frozen:
                    raise ValueError("frozen model manifest SHA does not match dev-train output")
                self._write_json(self.runtime_root / "frozen_model_manifest.json", manifest)
            complete = self._state(stage, "complete", inputs, output, started_at=started, ended_at=_timestamp())
            self._write_json(self._state_path(stage), complete)
            self._write_progress(complete)
            self._append_stage_log(stage, "complete", complete)
            return complete
        except TimeoutError as error:
            timeout = self._state(
                stage,
                "timeout",
                inputs,
                {},
                started_at=started,
                ended_at=_timestamp(),
                failure_details={"type": "StageTimeout", "message": str(error)},
            )
            self._write_json(self._state_path(stage), timeout)
            self._write_progress(timeout)
            self._append_stage_log(stage, "timeout", timeout)
            raise
        except Exception as error:
            blocked = self._state(
                stage,
                "blocked",
                inputs,
                {},
                started_at=started,
                ended_at=_timestamp(),
                failure_details={"type": type(error).__name__, "message": str(error)},
            )
            self._write_json(self._state_path(stage), blocked)
            self._write_progress(blocked)
            self._append_stage_log(stage, "blocked", blocked)
            raise
        finally:
            self._stop_stage_timer(previous_alarm)
            stop_heartbeat.set()
            heartbeat.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))

    def _heartbeat_until_stopped(self, stage: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval_seconds):
            state = self._load_state(stage)
            if state is None or state.get("status") != "running":
                return
            state["heartbeat_at"] = _timestamp()
            state["peak_rss_bytes"] = _peak_rss_bytes()
            self._write_json(self._state_path(stage), state)
            self._write_progress(state)

    def _start_stage_timer(self, stage: str):
        timeout = float(self.stage_timeouts_seconds.get(stage, 0))
        if timeout <= 0 or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
            return None
        previous = signal.getsignal(signal.SIGALRM)

        def raise_timeout(_signal_number, _frame):
            raise TimeoutError(f"stage={stage} exceeded timeout_seconds={timeout}")

        signal.signal(signal.SIGALRM, raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        return previous

    @staticmethod
    def _stop_stage_timer(previous) -> None:
        if previous is None or not hasattr(signal, "SIGALRM"):
            return
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    def _input_hashes(self, stage: str, states: Mapping[str, dict[str, Any]]) -> dict[str, str]:
        hashes = {"config_sha256": str(self.config.sha256)}
        for upstream in STAGES[: STAGES.index(stage)]:
            state = states.get(upstream) or self._load_state(upstream)
            if state is None or state.get("status") != "complete":
                raise TrainingBlockedError((f"upstream_{upstream}_incomplete",))
            hashes[f"upstream:{upstream}"] = _sha256_bytes(_canonical_json(state))
        return hashes

    def _is_reusable(self, state: dict[str, Any] | None, inputs: Mapping[str, str]) -> bool:
        return bool(
            state
            and state.get("status") == "complete"
            and state.get("input_hashes") == dict(inputs)
            and state.get("output_hashes") == _output_hashes(state.get("artifacts", {}))
        )

    def _require_frozen_sha(self, provided: str | None) -> None:
        path = self.runtime_root / "frozen_model_manifest.json"
        if not path.is_file():
            raise FrozenModelMismatchError("frozen_model_manifest.json is required before final-evaluate")
        expected = str(json.loads(path.read_text(encoding="utf-8")).get("frozen_model_sha", "")).strip()
        if not expected or provided != expected:
            raise FrozenModelMismatchError("final-evaluate requires the exact frozen model SHA")

    def _require_formal_stage_inputs(self, stage: str) -> None:
        if stage not in FORMAL_DOWNSTREAM_STAGES:
            return
        blocking_codes = []
        if not (self.runtime_root / "manifests" / "full-build.json").is_file():
            blocking_codes.append("upstream_full-build_manifest_missing")
        if not (self.runtime_root / "artifacts" / "full-build" / "dataset_registry.json").is_file():
            blocking_codes.append("full_build_dataset_unregistered")
        if blocking_codes:
            raise TrainingBlockedError(tuple(blocking_codes))

    def _state(
        self,
        stage: str,
        status: str,
        input_hashes: Mapping[str, str],
        artifacts: Mapping[str, Any],
        *,
        started_at: str,
        ended_at: str | None = None,
        failure_details: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "status": status,
            "input_hashes": dict(sorted(input_hashes.items())),
            "output_hashes": _output_hashes(artifacts),
            "artifacts": dict(artifacts),
            "started_at": started_at,
            "ended_at": ended_at,
            "heartbeat_at": _timestamp() if status == "running" else ended_at,
            "pid": os.getpid(),
            "peak_rss_bytes": _peak_rss_bytes(),
            "failure_details": dict(failure_details) if failure_details else None,
        }

    def _state_path(self, stage: str) -> Path:
        return self.runtime_root / "stages" / stage / "stage_state.json"

    def _write_progress(self, state: Mapping[str, Any]) -> None:
        stage = str(state.get("stage") or "")
        started_at = str(state.get("started_at") or "")
        timeout_seconds = self.stage_timeouts_seconds.get(stage)
        estimated_remaining_seconds = None
        if state.get("status") == "running" and timeout_seconds and started_at:
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds()
                estimated_remaining_seconds = max(0, int(float(timeout_seconds) - elapsed))
            except ValueError:
                estimated_remaining_seconds = None
        progress = {
            "run_id": self.runtime_root.name,
            "dataset_id": self._dataset_id(),
            "stage": state.get("stage"),
            "status": state.get("status"),
            "substep": state.get("stage"),
            "started_at": state.get("started_at"),
            "heartbeat_at": state.get("heartbeat_at"),
            "ended_at": state.get("ended_at"),
            "pid": state.get("pid"),
            "peak_rss_bytes": state.get("peak_rss_bytes"),
            "current_partition": None,
            "processed_rows": None,
            "total_rows": None,
            "estimated_remaining_seconds": estimated_remaining_seconds,
            "retry_count": 0,
            "failure_details": state.get("failure_details"),
        }
        self._write_json(self.runtime_root / "progress.json", progress)

    def _dataset_id(self) -> str | None:
        path = self.runtime_root / "artifacts" / "full-build" / "dataset_registry.json"
        if not path.is_file():
            return None
        try:
            return str(json.loads(path.read_text(encoding="utf-8")).get("dataset_id") or "") or None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _append_stage_log(self, stage: str, event: str, state: Mapping[str, Any]) -> None:
        path = self._state_path(stage).parent / "stage.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": _timestamp(),
            "event": event,
            "status": state.get("status"),
            "stage": stage,
            "pid": state.get("pid"),
            "failure_details": state.get("failure_details"),
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")

    def _load_state(self, stage: str) -> dict[str, Any] | None:
        path = self._state_path(stage)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    @staticmethod
    def _write_json(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, default=str) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".stage-", suffix=".tmp", delete=False) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _output_hashes(artifacts: Mapping[str, Any]) -> dict[str, str]:
    hashes = {"artifacts_sha256": _sha256_bytes(_canonical_json(artifacts))} if artifacts else {}
    for name, value in artifacts.items():
        path = Path(value) if isinstance(value, str) else None
        if path and path.is_file():
            hashes[f"artifact:{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _peak_rss_bytes() -> int | None:
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if os.name == "posix" and "darwin" in os.sys.platform else peak * 1024)
