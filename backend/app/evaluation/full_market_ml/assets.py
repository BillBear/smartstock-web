"""Immutable dataset registration and verified external backup for ML research."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_ASSET_PATHS = {
    "collection_manifest": Path("manifests/full-build.json"),
    "dataset": Path("artifacts/full-build/dataset.parquet"),
    "split_plan": Path("artifacts/full-build/split_plan.json"),
    "quality_report": Path("artifacts/full-build/quality_report.json"),
}
_BACKUP_PATHS = (
    Path("raw"),
    Path("panel/stage=full-build"),
    Path("artifacts/full-build"),
    Path("artifacts/feature-audit"),
    Path("artifacts/dev-train"),
    Path("manifests/full-build.json"),
    Path("frozen_model_manifest.json"),
)


def build_dataset_registry(
    runtime_root: str | Path,
    *,
    code_revision: str,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic registry record without modifying research data."""
    root = Path(runtime_root)
    manifest = _load_json(root / _ASSET_PATHS["collection_manifest"])
    split = _load_json(root / _ASSET_PATHS["split_plan"])
    assets = {name: _file_evidence(root / relative) for name, relative in _ASSET_PATHS.items()}
    label_schema_sha256 = _sha256_json(_label_schema(root / _ASSET_PATHS["dataset"]))
    feature_schema_sha256 = _sha256_json(_feature_schema(root))
    payload = {
        "raw_manifest_sha256": assets["collection_manifest"]["sha256"],
        "config_sha256": str(manifest.get("config_sha256", "")),
        "code_revision": str(code_revision),
        "feature_schema_sha256": feature_schema_sha256,
        "label_schema_sha256": label_schema_sha256,
    }
    registry = {
        "dataset_id": "fm_" + _sha256_json(payload)[:20],
        **payload,
        "split_sha256": str(split.get("split_sha256", "")),
        "trade_dates": list(manifest.get("trade_cal_open_dates", ())),
        "assets": assets,
        "environment": {"python_version": sys.version.split()[0], **dict(environment or {})},
    }
    return registry


def write_dataset_registry(runtime_root: str | Path, registry: Mapping[str, Any]) -> Path:
    """Persist the registry next to immutable artifacts using atomic replacement."""
    path = Path(runtime_root) / "artifacts" / "full-build" / "dataset_registry.json"
    _write_json_atomic(path, dict(registry))
    return path


def backup_dataset_assets(
    runtime_root: str | Path,
    backup_root: str | Path,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy required reproducibility assets to a verified, atomic backup directory."""
    source = Path(runtime_root)
    destination_root = Path(backup_root)
    dataset_id = str(registry["dataset_id"])
    destination_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{dataset_id}-", dir=destination_root))
    try:
        for relative in _BACKUP_PATHS:
            original = source / relative
            if not original.exists():
                continue
            copied = temporary / relative
            if original.is_dir():
                shutil.copytree(original, copied, ignore=shutil.ignore_patterns(".panel-*", "*.tmp"))
            else:
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, copied)
        registry_path = temporary / "dataset_registry.json"
        _write_json_atomic(registry_path, dict(registry))
        files = [_file_evidence(path, relative_to=temporary) for path in sorted(temporary.rglob("*")) if path.is_file()]
        verification = {
            "dataset_id": dataset_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files),
            "total_bytes": sum(item["bytes"] for item in files),
            "verification_status": "verified",
            "files": files,
        }
        _write_json_atomic(temporary / "backup_manifest.json", verification)
        destination = destination_root / dataset_id
        if destination.exists():
            raise FileExistsError(f"backup already exists for immutable dataset: {dataset_id}")
        os.replace(temporary, destination)
        return verification
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_dataset_backup(backup_root: str | Path, registry: Mapping[str, Any]) -> dict[str, Any]:
    """Verify that immutable base data exists in an external backup before final fitting."""
    dataset_id = str(registry["dataset_id"])
    destination = Path(backup_root) / dataset_id
    manifest_path = destination / "backup_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"verified dataset backup manifest is required: {manifest_path}")
    manifest = _load_json(manifest_path)
    if manifest.get("dataset_id") != dataset_id or manifest.get("verification_status") != "verified":
        raise ValueError("dataset backup manifest does not match the immutable dataset registry")
    _verify_backup_manifest_files(destination, manifest)
    files = {str(item.get("path")): str(item.get("sha256")) for item in manifest.get("files", ()) if isinstance(item, Mapping)}
    for asset in registry.get("assets", {}).values():
        source_path = Path(str(asset.get("path", "")))
        expected_sha = str(asset.get("sha256", ""))
        relative = _backup_relative_asset_path(source_path)
        if not relative or files.get(relative) != expected_sha:
            raise ValueError(f"dataset backup is missing verified asset: {relative or source_path}")
    return manifest


def backup_stage_assets(
    runtime_root: str | Path,
    backup_root: str | Path,
    registry: Mapping[str, Any],
    *,
    stage: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Back up one immutable model/evaluation stage below an already verified dataset."""
    if not stage or not artifact_id:
        raise ValueError("stage and artifact_id are required for derived artifact backup")
    verify_dataset_backup(backup_root, registry)
    source = Path(runtime_root) / "artifacts" / stage
    destination = Path(backup_root) / str(registry["dataset_id"]) / "derived" / stage / str(artifact_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        manifest_path = destination / "backup_manifest.json"
        if not manifest_path.is_file():
            raise FileExistsError(f"derived artifact backup exists without a manifest: {destination}")
        existing = _load_json(manifest_path)
        if (
            existing.get("dataset_id") != str(registry["dataset_id"])
            or existing.get("stage") != stage
            or existing.get("artifact_id") != str(artifact_id)
            or existing.get("verification_status") != "verified"
        ):
            raise ValueError(f"derived artifact backup does not match the requested immutable artifact: {destination}")
        _verify_backup_manifest_files(destination, existing)
        return existing
    if not source.is_dir():
        raise FileNotFoundError(f"stage artifact directory is missing: {source}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{artifact_id}-", dir=destination.parent))
    try:
        copied = temporary / "artifacts" / stage
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, copied, ignore=shutil.ignore_patterns("*.tmp"))
        files = [_file_evidence(path, relative_to=temporary) for path in sorted(temporary.rglob("*")) if path.is_file()]
        verification = {
            "dataset_id": str(registry["dataset_id"]),
            "stage": stage,
            "artifact_id": str(artifact_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files),
            "total_bytes": sum(item["bytes"] for item in files),
            "verification_status": "verified",
            "files": files,
        }
        _write_json_atomic(temporary / "backup_manifest.json", verification)
        os.replace(temporary, destination)
        return verification
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _feature_schema(root: Path) -> Any:
    path = root / "panel" / "stage=full-build" / "feature_contract.json"
    return _load_json(path) if path.is_file() else {}


def _backup_relative_asset_path(source_path: Path) -> str | None:
    """Map registered run paths to their stable relative location inside a backup."""
    parts = source_path.parts
    for marker in ("manifests", "artifacts"):
        if marker in parts:
            return str(Path(*parts[parts.index(marker):]))
    return None


def _verify_backup_manifest_files(destination: Path, manifest: Mapping[str, Any]) -> None:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("backup manifest has no file checksum list")
    for item in files:
        if not isinstance(item, Mapping):
            raise ValueError("backup manifest has an invalid file checksum entry")
        relative = str(item.get("path", ""))
        expected_sha = str(item.get("sha256", ""))
        path = destination / relative
        if not relative or not path.is_file():
            raise ValueError(f"backup manifest file is missing: {relative}")
        if _sha256_file(path) != expected_sha:
            raise ValueError(f"backup manifest checksum mismatch: {relative}")


def _label_schema(dataset_path: Path) -> dict[str, list[str]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:  # pragma: no cover - the ML environment supplies pyarrow.
        raise RuntimeError("pyarrow is required to register full-market datasets") from error
    columns = pq.ParquetFile(dataset_path).schema.names
    return {"label_columns": sorted(column for column in columns if column.startswith(("label_", "future_", "mfe_", "mae_", "tp_", "sl_")))}


def _file_evidence(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(relative_to)) if relative_to else str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".asset-", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
