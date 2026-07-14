"""Verified local compression for superseded ML research process assets."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from typing import Any, Iterable


MANIFEST_NAME = "archive_manifest.json"


def archive_research_paths(
    source_root: str | Path,
    source_paths: Iterable[str | Path],
    archive_path: str | Path,
    *,
    delete_after_verify: bool = False,
) -> dict[str, Any]:
    """Archive selected descendants and delete them only after full checksum verification."""
    root = Path(source_root).resolve()
    sources = tuple(Path(path).resolve() for path in source_paths)
    if not sources:
        raise ValueError("at least one research process path is required")
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(f"research process path is missing: {source}")
        if source == root or root not in source.parents:
            raise ValueError(f"research process path must be below source root: {source}")
    target = Path(archive_path).resolve()
    if target.exists():
        raise FileExistsError(f"research archive already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    files = _collect_files(root, sources)
    manifest = {
        "schema_version": 1,
        "source_root_name": root.name,
        "verification_status": "pending",
        "file_count": len(files),
        "total_bytes": sum(item[1] for item in files.values()),
        "files": [
            {"path": path, "bytes": evidence[1], "sha256": evidence[0]}
            for path, evidence in sorted(files.items())
        ],
    }
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}-", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
    target_created = False
    deletion_started = False
    try:
        with tarfile.open(temporary, mode="w:gz", compresslevel=6) as archive:
            for relative in sorted(files):
                archive.add(root / relative, arcname=relative, recursive=False)
            payload = (json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size = len(payload)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(payload))
        os.replace(temporary, target)
        target_created = True
        verified = verify_research_archive(target)
        sidecar = target.with_suffix(target.suffix + ".manifest.json")
        _write_json_atomic(sidecar, verified)
        if delete_after_verify:
            deletion_started = True
            for source in sorted(sources, key=lambda path: len(path.parts), reverse=True):
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
        return verified
    except BaseException:
        temporary.unlink(missing_ok=True)
        if target_created and not deletion_started:
            target.unlink(missing_ok=True)
            target.with_suffix(target.suffix + ".manifest.json").unlink(missing_ok=True)
        raise


def verify_research_archive(archive_path: str | Path) -> dict[str, Any]:
    """Read every archived file and compare it with the embedded SHA256 manifest."""
    path = Path(archive_path).resolve()
    archive_sha256 = _sha256(path)
    sidecar = path.with_suffix(path.suffix + ".manifest.json")
    if sidecar.is_file():
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
        if recorded.get("archive_sha256") != archive_sha256:
            raise ValueError("research archive checksum differs from verified sidecar")
    with tarfile.open(path, mode="r:gz") as archive:
        names = archive.getnames()
        if len(names) != len(set(names)) or MANIFEST_NAME not in names:
            raise ValueError("research archive has duplicate members or no manifest")
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe research archive member: {name}")
        manifest_file = archive.extractfile(MANIFEST_NAME)
        if manifest_file is None:
            raise ValueError("research archive manifest cannot be read")
        manifest = json.loads(manifest_file.read().decode("utf-8"))
        expected = {str(item["path"]): item for item in manifest.get("files", ())}
        actual_names = set(names) - {MANIFEST_NAME}
        if actual_names != set(expected):
            raise ValueError("research archive members do not match manifest")
        for name, evidence in expected.items():
            member = archive.extractfile(name)
            if member is None:
                raise ValueError(f"research archive member cannot be read: {name}")
            payload = member.read()
            if len(payload) != int(evidence["bytes"]):
                raise ValueError(f"research archive byte count mismatch: {name}")
            if hashlib.sha256(payload).hexdigest() != str(evidence["sha256"]):
                raise ValueError(f"research archive checksum mismatch: {name}")
    result = dict(manifest)
    result["verification_status"] = "verified"
    result["archive_sha256"] = archive_sha256
    result["archive_bytes"] = path.stat().st_size
    return result


def _collect_files(root: Path, sources: tuple[Path, ...]) -> dict[str, tuple[str, int]]:
    files: dict[str, tuple[str, int]] = {}
    for source in sources:
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if relative in files:
                continue
            files[relative] = (_sha256(path), path.stat().st_size)
    if not files:
        raise ValueError("research process paths contain no regular files")
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)
