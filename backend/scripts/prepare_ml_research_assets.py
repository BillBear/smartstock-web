#!/usr/bin/env python3
"""Copy ML research inputs into a stable, verified workspace-level asset root."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


class AssetIntegrityError(ValueError):
    """Raised when an immutable source or stable copy fails checksum validation."""


def prepare_assets(
    source_roots: Sequence[Path], asset_root: Path, minimum_free_gb: int = 50
) -> dict[str, Any]:
    sources = tuple(Path(path).expanduser().resolve() for path in source_roots)
    destination_root = Path(asset_root).expanduser().resolve()
    if not sources:
        raise ValueError("at least one source root is required")
    missing = [str(path) for path in sources if not path.is_dir()]
    if missing:
        raise FileNotFoundError("asset source is missing: " + ", ".join(missing))
    free_bytes = shutil.disk_usage(destination_root.parent if destination_root.parent.exists() else destination_root.anchor).free
    required_bytes = max(0, int(minimum_free_gb)) * 1024**3
    if free_bytes < required_bytes:
        raise OSError(
            f"free disk below required threshold: available={free_bytes} required={required_bytes}"
        )

    destination_root.mkdir(parents=True, exist_ok=True)
    copied_sources = []
    dataset_ids = []
    all_existing = True
    for source in sources:
        descriptor = _describe_source(source)
        if descriptor["role"] == "dataset":
            dataset_ids.append(descriptor["asset_id"])
        result = _copy_or_verify_source(source, destination_root, descriptor)
        copied_sources.append(result)
        all_existing = all_existing and result["status"] == "verified_existing"

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "verified_existing" if all_existing else "copied_and_verified",
        "dataset_id": dataset_ids[0] if dataset_ids else None,
        "source_count": len(copied_sources),
        "file_count": sum(int(item["file_count"]) for item in copied_sources),
        "total_bytes": sum(int(item["total_bytes"]) for item in copied_sources),
        "sources": copied_sources,
        "verification_status": "verified",
    }
    _write_json_atomic(destination_root / "asset_manifest.json", manifest)
    return manifest


def _describe_source(source: Path) -> dict[str, Any]:
    registry_candidates = (
        source / "artifacts" / "full-build" / "dataset_registry_v3.json",
        source / "artifacts" / "full-build" / "dataset_registry.json",
    )
    registry_path = next((path for path in registry_candidates if path.is_file()), None)
    if registry_path:
        registry = _load_json(registry_path)
        asset_id = str(registry.get("dataset_id") or "").strip()
        if not asset_id:
            raise AssetIntegrityError(f"dataset registry has no dataset_id: {registry_path}")
        evidence = _registered_evidence(source, registry, registry_path)
        return {"role": "dataset", "category": "datasets", "asset_id": asset_id, "files": evidence}

    experiment_manifest = source / "experiment_manifest.json"
    if experiment_manifest.is_file():
        manifest_sha = _sha256_file(experiment_manifest)
        return {
            "role": "experiment",
            "category": "experiments",
            "asset_id": "label_split_" + manifest_sha[:16],
            "files": _directory_evidence(source),
        }

    raw_manifest = source / "manifests" / "full-build.json"
    if raw_manifest.is_file() and (source / "raw").is_dir():
        manifest_sha = _sha256_file(raw_manifest)
        paths = [path for path in (source / "raw").rglob("*") if path.is_file()]
        paths.extend(path for path in (source / "manifests").rglob("*") if path.is_file())
        return {
            "role": "raw",
            "category": "raw",
            "asset_id": "raw_" + manifest_sha[:16],
            "files": _paths_evidence(source, paths),
        }

    evidence = _directory_evidence(source)
    source_sha = _sha256_json(evidence)
    return {
        "role": "source",
        "category": "sources",
        "asset_id": "source_" + source_sha[:16],
        "files": evidence,
    }


def _registered_evidence(source: Path, registry: dict[str, Any], registry_path: Path) -> list[dict[str, Any]]:
    entries = registry.get("files")
    if not isinstance(entries, list) or not entries:
        raise AssetIntegrityError(f"dataset registry has no file evidence: {registry_path}")
    evidence = []
    for item in entries:
        if not isinstance(item, dict):
            raise AssetIntegrityError(f"dataset registry has an invalid file entry: {registry_path}")
        relative = Path(str(item.get("path", "")))
        path = source / relative
        expected = str(item.get("sha256", ""))
        if not relative.parts or not path.is_file():
            raise AssetIntegrityError(f"registered asset is missing: {relative}")
        actual = _sha256_file(path)
        if actual != expected:
            raise AssetIntegrityError(f"registered asset sha256 mismatch: {relative}")
        evidence.append({"path": str(relative), "bytes": path.stat().st_size, "sha256": actual})
    registry_relative = registry_path.relative_to(source)
    if str(registry_relative) not in {item["path"] for item in evidence}:
        evidence.append(_file_evidence(registry_path, source))
    return sorted(evidence, key=lambda item: item["path"])


def _copy_or_verify_source(source: Path, asset_root: Path, descriptor: dict[str, Any]) -> dict[str, Any]:
    destination = asset_root / descriptor["category"] / descriptor["asset_id"]
    expected_files = descriptor["files"]
    if destination.exists():
        _verify_destination(destination, expected_files)
        status = "verified_existing"
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".copy-", dir=destination.parent))
        try:
            for item in expected_files:
                relative = Path(item["path"])
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, target)
            _write_json_atomic(
                temporary / "source_manifest.json",
                {
                    "schema_version": 1,
                    "role": descriptor["role"],
                    "asset_id": descriptor["asset_id"],
                    "source_path": str(source),
                    "files": expected_files,
                    "verification_status": "verified",
                },
            )
            _verify_destination(temporary, expected_files)
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        status = "copied_and_verified"
    return {
        "role": descriptor["role"],
        "asset_id": descriptor["asset_id"],
        "source_path": str(source),
        "destination": str(destination),
        "status": status,
        "file_count": len(expected_files),
        "total_bytes": sum(int(item["bytes"]) for item in expected_files),
        "evidence_sha256": _sha256_json(expected_files),
    }


def _verify_destination(destination: Path, expected_files: list[dict[str, Any]]) -> None:
    for item in expected_files:
        path = destination / item["path"]
        if not path.is_file():
            raise AssetIntegrityError(f"stable asset is missing: {item['path']}")
        if path.stat().st_size != int(item["bytes"]) or _sha256_file(path) != item["sha256"]:
            raise AssetIntegrityError(f"stable asset sha256 mismatch: {item['path']}")


def _directory_evidence(root: Path) -> list[dict[str, Any]]:
    return _paths_evidence(root, (path for path in root.rglob("*") if path.is_file()))


def _paths_evidence(root: Path, paths) -> list[dict[str, Any]]:
    return sorted((_file_evidence(path, root) for path in set(paths)), key=lambda item: item["path"])


def _file_evidence(path: Path, root: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".asset-", suffix=".tmp", delete=False) as handle:
        json.dump(value, handle, ensure_ascii=True, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--minimum-free-gb", type=int, default=50)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = prepare_assets(
        [Path(path) for path in args.source],
        Path(args.asset_root),
        minimum_free_gb=args.minimum_free_gb,
    )
    print(f"status={result['status']}")
    print(f"dataset_id={result['dataset_id']}")
    print(f"sha256={result['verification_status'].upper()}")
    print(f"file_count={result['file_count']}")
    print(f"total_bytes={result['total_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
