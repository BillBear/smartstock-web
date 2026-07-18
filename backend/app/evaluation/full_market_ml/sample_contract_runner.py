"""Verified raw-source provenance for immutable ML sample contracts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping

import pyarrow.parquet as pq

from .sample_contracts import (
    build_feature_availability_contract,
    build_label_contract,
    build_sample_contract,
)


_SHA256_HEX_LENGTH = 64
_SOURCE_SPECS = (
    ("listing", "stock_basic", "L", (("ts_code", "list_date"),)),
    ("delisting", "stock_basic", "D", (("ts_code", "list_date", "delist_date"),)),
    ("pending_listing", "stock_basic", "P", (("ts_code", "list_date"),)),
    ("st", "namechange", None, (("ts_code", "name", "start_date", "end_date"),)),
    ("trading_calendar", "trade_cal", None, (("cal_date", "is_open"),)),
    ("suspension", "suspend_d", None, (("ts_code", "trade_date"), ("ts_code", "suspend_date", "resume_date"))),
)
_INDUSTRY_SOURCE_SPECS = (
    ("industry_classification", "index_classify", None, (("index_code", "industry_name"),)),
    ("industry_membership", "index_member_all", None, (("l1_code", "ts_code", "in_date", "out_date"),)),
)


def build_security_state_provenance(
    raw_manifest: Mapping[str, Any], raw_root: str | Path
) -> dict[str, Any]:
    """Hash and schema-check all source partitions used for PIT state fields."""
    root = Path(raw_root).expanduser().resolve()
    partitions = _partitions(raw_manifest)
    industry_enabled = bool(raw_manifest.get("industry_relative_enabled", False))
    specs = _SOURCE_SPECS + (_INDUSTRY_SOURCE_SPECS if industry_enabled else ())
    sources: list[dict[str, Any]] = []
    blocking: set[str] = set()
    for role, endpoint, key, alternatives in specs:
        selected = _select_partitions(partitions, endpoint, key)
        if not selected:
            expected = endpoint if key is None else f"{endpoint}:{key}"
            raise ValueError(f"security-state provenance is missing required source: {expected}")
        for record in selected:
            path = _verified_partition_path(root, record)
            columns = tuple(pq.ParquetFile(path).schema.names)
            required = _first_matching_columns(columns, alternatives)
            if required is None:
                missing = sorted(set(alternatives[0]) - set(columns))
                for column in missing:
                    blocking.add(f"security_state:missing_columns:{role}:{column}")
            sources.append(
                {
                    "role": role,
                    "endpoint": endpoint,
                    "key": str(record.get("key", "")),
                    "path": str(record["path"]),
                    "sha256": str(record["sha256"]).lower(),
                    "row_count": int(record.get("row_count", 0) or 0),
                    "columns": list(columns),
                    "required_columns": list(required if required is not None else alternatives[0]),
                }
            )
    covers = {"listing", "delisting", "st", "suspension"}
    if industry_enabled:
        covers.add("industry")
    payload: dict[str, Any] = {
        "security_state_provenance_version": "pit_sources_v1",
        "covers": sorted(covers),
        "industry_relative_enabled": industry_enabled,
        "sources": sorted(sources, key=lambda item: (item["role"], item["path"])),
        "blocking_codes": sorted(blocking),
        "validation_status": "verified" if not blocking else "blocked",
    }
    return _with_sha256(payload)


def derive_sample_contract(
    *,
    asset_root: str | Path,
    dataset_id: str,
    label_run_root: str | Path,
    output_root: str | Path,
    raw_root: str | Path | None = None,
    minimum_feature_coverage: float = 0.95,
    derivation_policy_sha256: str = "",
) -> dict[str, Any]:
    """Create one immutable sample contract from already collected research assets."""
    root = Path(asset_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"sample contract output already exists: {output}")
    dataset_root = root / "datasets" / dataset_id
    registry_path = dataset_root / "artifacts" / "full-build" / "dataset_registry_v3.json"
    registry = _load_json(registry_path)
    if registry.get("dataset_id") != dataset_id:
        raise ValueError("dataset registry does not match requested dataset_id")
    registry_sha = _sha256_file(registry_path)

    dataset_paths = {
        "full_build_manifest": Path("manifests/full-build.json"),
        "quality_report": Path("artifacts/full-build/quality_report_v3.json"),
        "label_report": Path("artifacts/full-build/label_report_v3.json"),
        "split_plan": Path("artifacts/full-build/split_plan_v3.json"),
    }
    source_hashes = {"dataset_registry": registry_sha}
    if derivation_policy_sha256:
        _require_sha256("derivation policy", derivation_policy_sha256)
        source_hashes["derivation_policy"] = derivation_policy_sha256.lower()
    loaded: dict[str, dict[str, Any]] = {}
    for name, relative in dataset_paths.items():
        path = dataset_root / relative
        _verify_registry_file(registry, path, relative)
        source_hashes[name] = _sha256_file(path)
        loaded[name] = _load_json(path)

    source_manifest_path = dataset_root / "source_manifest.json"
    source_manifest = _load_json(source_manifest_path)
    if source_manifest.get("verification_status") != "verified":
        raise ValueError("source manifest is not verified")
    feature_audit_path = dataset_root / "artifacts" / "feature-audit" / "report_v3.json"
    _verify_source_manifest_file(source_manifest, feature_audit_path, Path("artifacts/feature-audit/report_v3.json"))
    source_hashes["feature_audit"] = _sha256_file(feature_audit_path)

    raw_manifest_sha = str(_mapping(registry.get("payload")).get("raw_manifest_sha256", "")).lower()
    _require_sha256("dataset raw manifest", raw_manifest_sha)
    resolved_raw_root = (
        Path(raw_root).expanduser().resolve()
        if raw_root is not None
        else root / "raw" / f"raw_{raw_manifest_sha[:16]}"
    )
    raw_manifest_path = resolved_raw_root / "manifests" / "full-build.json"
    if _sha256_file(raw_manifest_path) != raw_manifest_sha:
        raise ValueError("raw collection manifest hash does not match dataset registry")
    raw_manifest = _load_json(raw_manifest_path)
    source_hashes["raw_manifest"] = raw_manifest_sha

    label_root = Path(label_run_root).expanduser().resolve() / "artifacts" / "label-audit"
    label_manifest_path = label_root / "label_manifest.json"
    label_report_path = label_root / "label_objective_report.json"
    label_manifest = _load_json(label_manifest_path)
    label_audit = _load_json(label_report_path)
    _verify_label_artifacts(label_root / "labels", label_manifest)
    _verify_label_binding(label_manifest, label_audit, dataset_id, registry_sha)
    source_hashes["label_manifest"] = _sha256_file(label_manifest_path)
    source_hashes["label_objective_report"] = _sha256_file(label_report_path)

    label_input = dict(label_audit)
    label_input["observed_path_ambiguity_count"] = loaded["label_report"].get("path_ambiguity_count_10d", 0)
    label_contract = build_label_contract(
        label_input,
        str(label_manifest["contract_sha256"]),
        registry_sha,
    )
    security_provenance = build_security_state_provenance(raw_manifest, resolved_raw_root)
    feature_availability = build_feature_availability_contract(
        loaded["quality_report"], _load_json(feature_audit_path), minimum_feature_coverage
    )
    sample_contract = build_sample_contract(
        dataset_id,
        source_hashes,
        label_contract,
        security_provenance,
        feature_availability,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_json_atomic(temporary / "label_contract.json", label_contract)
        _write_json_atomic(temporary / "security_state_provenance.json", security_provenance)
        _write_json_atomic(temporary / "feature_availability_contract.json", feature_availability)
        _write_json_atomic(temporary / "sample_contract.json", sample_contract)
        _write_json_atomic(
            temporary / "run_manifest.json",
            {
                "dataset_id": dataset_id,
                "derivation_type": "full_market_sample_contract",
                "source_hashes": source_hashes,
                "sample_contract_sha256": sample_contract["sha256"],
                "production_integration_allowed": False,
            },
        )
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            for child in sorted(temporary.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            temporary.rmdir()
    return {
        "sample_contract_path": str(output / "sample_contract.json"),
        "label_contract_path": str(output / "label_contract.json"),
        "security_state_provenance_path": str(output / "security_state_provenance.json"),
        "feature_availability_contract_path": str(output / "feature_availability_contract.json"),
        "status": security_provenance["validation_status"],
    }


def _partitions(raw_manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = raw_manifest.get("partitions")
    if not isinstance(value, list):
        raise ValueError("raw collection manifest has no partitions array")
    adopted: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if item.get("status") != "adopted":
            continue
        if not str(item.get("endpoint", "")).strip() or not str(item.get("path", "")).strip():
            continue
        _require_sha256("raw partition", item.get("sha256"))
        adopted.append(item)
    return adopted


def _select_partitions(
    partitions: Iterable[Mapping[str, Any]], endpoint: str, key: str | None
) -> list[Mapping[str, Any]]:
    selected = [item for item in partitions if item.get("endpoint") == endpoint]
    if key is not None:
        selected = [item for item in selected if str(item.get("key", "")) == key]
    return sorted(selected, key=lambda item: (str(item.get("key", "")), str(item.get("path", ""))))


def _verified_partition_path(root: Path, record: Mapping[str, Any]) -> Path:
    relative = Path(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid raw partition path: {relative}")
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError(f"raw partition is unavailable: {relative}")
    expected = str(record["sha256"]).lower()
    observed = _sha256_file(path)
    if observed != expected:
        raise ValueError(f"raw partition hash mismatch: {relative}")
    return path


def _first_matching_columns(
    columns: tuple[str, ...], alternatives: tuple[tuple[str, ...], ...]
) -> tuple[str, ...] | None:
    available = set(columns)
    return next((candidate for candidate in alternatives if set(candidate).issubset(available)), None)


def _with_sha256(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result["sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def _require_sha256(label: str, value: object) -> None:
    text = str(value).strip().lower()
    if len(text) != _SHA256_HEX_LENGTH or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} hash must be a SHA256")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required sample-contract source is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"sample-contract source must be a JSON object: {path}")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _verify_registry_file(registry: Mapping[str, Any], path: Path, relative: Path) -> None:
    expected = _manifest_hash(registry.get("files"), relative, "dataset registry")
    if not path.is_file() or _sha256_file(path) != expected:
        raise ValueError(f"dataset registry hash mismatch: {relative}")


def _verify_source_manifest_file(source_manifest: Mapping[str, Any], path: Path, relative: Path) -> None:
    expected = _manifest_hash(source_manifest.get("files"), relative, "source manifest")
    if not path.is_file() or _sha256_file(path) != expected:
        raise ValueError(f"source manifest hash mismatch: {relative}")


def _manifest_hash(records: object, relative: Path, label: str) -> str:
    if not isinstance(records, list):
        raise ValueError(f"{label} files are missing")
    expected = next(
        (
            str(item.get("sha256", "")).lower()
            for item in records
            if isinstance(item, Mapping) and item.get("path") == str(relative)
        ),
        "",
    )
    _require_sha256(f"{label} required file {relative}", expected)
    return expected


def _verify_label_artifacts(label_root: Path, manifest: Mapping[str, Any]) -> None:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("label manifest has no files")
    for record in files:
        if not isinstance(record, Mapping):
            raise ValueError("label manifest file record is invalid")
        relative = Path(str(record.get("path", "")))
        if not relative.name or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("label manifest contains invalid path")
        path = label_root / relative
        expected = str(record.get("sha256", "")).lower()
        _require_sha256("label shard", expected)
        if not path.is_file() or _sha256_file(path) != expected:
            raise ValueError(f"label shard hash mismatch: {relative}")


def _verify_label_binding(
    manifest: Mapping[str, Any], report: Mapping[str, Any], dataset_id: str, registry_sha: str
) -> None:
    for label, value in (("label manifest", manifest), ("label report", report)):
        if value.get("dataset_id") != dataset_id:
            raise ValueError(f"{label} dataset_id does not match")
        if str(value.get("dataset_registry_sha256", "")).lower() != registry_sha.lower():
            raise ValueError(f"{label} dataset registry hash does not match")
        _require_sha256(f"{label} contract", value.get("contract_sha256"))
    if manifest.get("contract_sha256") != report.get("contract_sha256"):
        raise ValueError("label manifest and report contract hashes do not match")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)
