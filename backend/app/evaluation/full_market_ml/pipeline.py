"""Resumable, hash-verified orchestration for the full-market ML workflow.

This module owns stage state only.  Collection, quality, feature, training, and
evaluation decisions remain in their established modules or injected adapters.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
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
    "final-holdout-evaluate",
)


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

    def __init__(self, config: Any, runtime_root: str | Path, services: Mapping[str, StageService]):
        self.config = config
        self.runtime_root = Path(runtime_root)
        self.services = dict(services)
        missing = [stage for stage in STAGES if stage not in self.services]
        if missing:
            raise ValueError("missing pipeline stage services: " + ", ".join(missing))

    def run(self, stage: str, *, resume: bool = False, frozen_model_sha: str | None = None) -> PipelineRunResult:
        if stage not in STAGES:
            raise ValueError("stage must be one of " + ", ".join(STAGES))
        if frozen_model_sha is not None and stage not in {"final-evaluate", "final-holdout-evaluate"}:
            raise ValueError("frozen_model_sha is only accepted for final evaluation stages")

        states: dict[str, dict[str, Any]] = {}
        reused: list[str] = []
        for current in STAGES[: STAGES.index(stage) + 1]:
            inputs = self._input_hashes(current, states)
            existing = self._load_state(current)
            if self._is_reusable(existing, inputs) and (resume or current != stage):
                states[current] = existing
                reused.append(current)
                continue
            if existing and existing.get("status") == "complete":
                raise ValueError(f"stage already complete: {current}; rerun with resume")

            if current in {"final-evaluate", "final-holdout-evaluate"}:
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

    def _run_stage(self, stage: str, inputs: dict[str, str], states: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        started = _timestamp()
        running = self._state(stage, "running", inputs, {}, started_at=started)
        self._write_json(self._state_path(stage), running)
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
            return complete
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
            raise

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
            "peak_rss_bytes": _peak_rss_bytes(),
            "failure_details": dict(failure_details) if failure_details else None,
        }

    def _state_path(self, stage: str) -> Path:
        return self.runtime_root / "stages" / stage / "stage_state.json"

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
