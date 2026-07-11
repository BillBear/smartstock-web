"""Persistent, auditable collection manifests for full-market ML inputs."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PartitionRecord:
    endpoint: str
    key: str
    path: str
    row_count: int
    schema: str
    sha256: str
    status: str = "collected"


@dataclass
class CollectionManifest:
    stage: str
    config_sha256: str
    request_pacing_seconds: float
    partitions: list[PartitionRecord] = field(default_factory=list)
    endpoint_errors: dict[str, int] = field(default_factory=dict)
    blocking_codes: list[str] = field(default_factory=list)
    optional_failures: list[str] = field(default_factory=list)
    industry_relative_enabled: bool = True
    attempt_history: list[dict[str, str]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.blocking_codes

    def partition(self, endpoint: str, key: str) -> PartitionRecord:
        for record in self.partitions:
            if record.endpoint == endpoint and record.key == key:
                return record
        raise KeyError(f"partition not found: {endpoint}/{key}")

    def partition_status(self, endpoint: str, key: str) -> str:
        return self.partition(endpoint, key).status

    def replace_partition(self, record: PartitionRecord) -> None:
        self.partitions = [
            existing
            for existing in self.partitions
            if not (existing.endpoint == record.endpoint and existing.key == record.key)
        ]
        self.partitions.append(record)
        self.attempt_history.append({"endpoint": record.endpoint, "key": record.key, "status": record.status})

    def mark_endpoint_error(self, endpoint: str, *, core: bool, optional_group: str | None = None) -> None:
        self.endpoint_errors[endpoint] = self.endpoint_errors.get(endpoint, 0) + 1
        if core:
            code = f"{endpoint}_collection_failed"
            if code not in self.blocking_codes:
                self.blocking_codes.append(code)
        elif optional_group and optional_group not in self.optional_failures:
            self.optional_failures.append(optional_group)

    def add_blocking_code(self, code: str) -> None:
        if code not in self.blocking_codes:
            self.blocking_codes.append(code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "config_sha256": self.config_sha256,
            "request_pacing_seconds": self.request_pacing_seconds,
            "partitions": [asdict(partition) for partition in self.partitions],
            "endpoint_errors": self.endpoint_errors,
            "blocking_codes": self.blocking_codes,
            "optional_failures": self.optional_failures,
            "industry_relative_enabled": self.industry_relative_enabled,
            "attempt_history": self.attempt_history,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CollectionManifest":
        return cls(
            stage=str(value["stage"]),
            config_sha256=str(value["config_sha256"]),
            request_pacing_seconds=float(value.get("request_pacing_seconds", 0)),
            partitions=[PartitionRecord(**partition) for partition in value.get("partitions", [])],
            endpoint_errors={str(key): int(count) for key, count in value.get("endpoint_errors", {}).items()},
            blocking_codes=[str(code) for code in value.get("blocking_codes", [])],
            optional_failures=[str(name) for name in value.get("optional_failures", [])],
            industry_relative_enabled=bool(value.get("industry_relative_enabled", True)),
            attempt_history=[dict(event) for event in value.get("attempt_history", [])],
        )


def manifest_path(runtime_root: Path, stage: str) -> Path:
    return runtime_root / "manifests" / f"{stage}.json"


def load_manifest(runtime_root: Path, stage: str, config_sha256: str, request_pacing_seconds: float) -> CollectionManifest:
    path = manifest_path(runtime_root, stage)
    if not path.exists():
        return CollectionManifest(stage=stage, config_sha256=config_sha256, request_pacing_seconds=request_pacing_seconds)
    manifest = CollectionManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    if (
        manifest.stage != stage
        or manifest.config_sha256 != config_sha256
        or manifest.request_pacing_seconds != request_pacing_seconds
    ):
        raise ValueError("collection manifest does not match the immutable stage/config snapshot")
    return manifest


def save_manifest(runtime_root: Path, manifest: CollectionManifest) -> None:
    path = manifest_path(runtime_root, manifest.stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".manifest-", suffix=".tmp", delete=False) as temporary_file:
        temporary_file.write(encoded)
        temporary_file.flush()
        os.fsync(temporary_file.fileno())
        temporary_path = Path(temporary_file.name)
    os.replace(temporary_path, path)
