"""Read immutable ML artifacts and write a research sample certificate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .sample_certification import CertificationConfig, certify_training_sample
from .static_security_state import load_static_security_state_asset


_REGISTRY_REQUIRED_PATHS = {
    "full_build_manifest": Path("manifests/full-build.json"),
    "quality_report": Path("artifacts/full-build/quality_report_v3.json"),
    "label_report": Path("artifacts/full-build/label_report_v3.json"),
    "split_plan": Path("artifacts/full-build/split_plan_v3.json"),
}
_COMPOSITE_REGISTRY_REQUIRED_PATHS = {
    "full_build_manifest": Path("manifests/full-build.json"),
    "quality_report": Path("artifacts/full-build/quality_report_v3.json"),
    "split_plan": Path("artifacts/full-build/split_plan_v3.json"),
}
_SOURCE_MANIFEST_REQUIRED_PATHS = {
    "feature_audit": Path("artifacts/feature-audit/report_v3.json"),
    "candidate_manifest": Path("artifacts/dev-train-v3/candidate_manifest.json"),
}


def run_certification(
    *,
    config_path: str | Path,
    asset_root: str | Path,
    output_root: str | Path,
    secondary_label_audit_path: str | Path | None = None,
    security_provenance_path: str | Path | None = None,
    sample_contract_path: str | Path | None = None,
) -> dict[str, Any]:
    """Certify one immutable research dataset and atomically preserve the result."""
    if sample_contract_path is not None:
        if secondary_label_audit_path is not None or security_provenance_path is not None:
            raise ValueError("composite certification does not accept legacy evidence paths")
        return _run_composite_certification(
            config_path=Path(config_path),
            asset_root=Path(asset_root),
            output_root=Path(output_root),
            sample_contract_path=Path(sample_contract_path),
        )
    config = CertificationConfig.from_mapping(_load_json(Path(config_path)))
    root = Path(asset_root)
    dataset_root = root / "datasets" / config.dataset_id
    registry_path = dataset_root / "artifacts" / "full-build" / "dataset_registry_v3.json"
    registry = _load_json(registry_path)
    if registry.get("dataset_id") != config.dataset_id:
        raise ValueError("dataset registry does not match certification config")

    input_hashes = {"dataset_registry": _sha256_file(registry_path)}
    for name, relative in _REGISTRY_REQUIRED_PATHS.items():
        path = dataset_root / relative
        _verify_registry_file(registry, path, relative)
        input_hashes[name] = _sha256_file(path)
    source_manifest_path = dataset_root / "source_manifest.json"
    source_manifest = _load_json(source_manifest_path)
    if source_manifest.get("verification_status") != "verified":
        raise ValueError("source manifest is not verified")
    input_hashes["source_manifest"] = _sha256_file(source_manifest_path)
    for name, relative in _SOURCE_MANIFEST_REQUIRED_PATHS.items():
        path = dataset_root / relative
        _verify_source_manifest_file(source_manifest, path, relative)
        input_hashes[name] = _sha256_file(path)

    quality = _load_json(dataset_root / "artifacts" / "full-build" / "quality_report_v3.json")
    labels = _load_json(dataset_root / "artifacts" / "full-build" / "label_report_v3.json")
    splits = _load_json(dataset_root / "artifacts" / "full-build" / "split_plan_v3.json")
    feature_audit = _load_json(dataset_root / _SOURCE_MANIFEST_REQUIRED_PATHS["feature_audit"])
    candidate = _load_json(dataset_root / _SOURCE_MANIFEST_REQUIRED_PATHS["candidate_manifest"])
    secondary = _load_optional_json(secondary_label_audit_path)
    security = _load_optional_json(security_provenance_path)
    if secondary_label_audit_path is not None:
        input_hashes["secondary_label_audit"] = _sha256_file(Path(secondary_label_audit_path))
    if security_provenance_path is not None:
        input_hashes["security_provenance"] = _sha256_file(Path(security_provenance_path))

    evidence = {
        "input_hashes": input_hashes,
        "panel": _panel_evidence(quality),
        "quality": {"disabled_feature_groups": quality.get("disabled_feature_groups", [])},
        "labels": _label_evidence(labels, secondary),
        "security_state": _security_evidence(security),
        "features": _feature_evidence(feature_audit),
        "splits": _split_evidence(splits),
    }
    certificate = certify_training_sample(config, evidence, _selected_features(candidate))
    certificate["schema_version"] = 1
    certificate["source_artifacts"] = {
        "dataset_root": f"datasets/{config.dataset_id}",
        "candidate_manifest": str(_SOURCE_MANIFEST_REQUIRED_PATHS["candidate_manifest"]),
        "secondary_label_audit_supplied": secondary_label_audit_path is not None,
        "security_provenance_supplied": security_provenance_path is not None,
    }
    certificate["evidence_summary"] = {
        "label_daily_overlap_count": len(_as_list(secondary.get("daily"))),
        "disabled_feature_groups": quality.get("disabled_feature_groups", []),
    }
    certificate_path = _write_certificate(Path(output_root), config.dataset_id, certificate)
    return {"certificate": certificate, "certificate_path": str(certificate_path)}


def _run_composite_certification(
    *,
    config_path: Path,
    asset_root: Path,
    output_root: Path,
    sample_contract_path: Path,
) -> dict[str, Any]:
    config = CertificationConfig.from_mapping(_load_json(config_path))
    contract = _load_json(sample_contract_path)
    _verify_payload_hash(contract, "sample contract")
    if contract.get("sample_contract_version") != "full_market_sample_v1":
        raise ValueError("unsupported sample contract version")
    if contract.get("dataset_id") != config.dataset_id:
        raise ValueError("sample contract does not match certification config")
    if bool(contract.get("production_integration_allowed", False)):
        raise ValueError("sample contract must forbid production integration")

    dataset_root = asset_root / "datasets" / config.dataset_id
    registry_path = dataset_root / "artifacts" / "full-build" / "dataset_registry_v3.json"
    registry = _load_json(registry_path)
    if registry.get("dataset_id") != config.dataset_id:
        raise ValueError("dataset registry does not match certification config")
    input_hashes = {"dataset_registry": _sha256_file(registry_path)}
    loaded: dict[str, dict[str, Any]] = {}
    for name, relative in _COMPOSITE_REGISTRY_REQUIRED_PATHS.items():
        path = dataset_root / relative
        _verify_registry_file(registry, path, relative)
        input_hashes[name] = _sha256_file(path)
        loaded[name] = _load_json(path)
    _verify_contract_source_hashes(contract, input_hashes)

    components = _load_contract_components(sample_contract_path.parent, contract)
    input_hashes["sample_contract"] = str(contract["sha256"])
    label_contract = components["label_contract"]
    security_provenance = components["security_state_provenance"]
    feature_availability = components["feature_availability_contract"]
    contract_source_hashes = contract.get("source_hashes")
    if not isinstance(contract_source_hashes, Mapping):
        raise ValueError("sample contract source_hashes are missing")
    _verify_declared_security_sources(asset_root, contract_source_hashes, security_provenance)
    selected_features = _selected_available_features(feature_availability)
    evidence = {
        "certification_mode": "composite_contract",
        "input_hashes": input_hashes,
        "panel": _panel_evidence(loaded["quality_report"]),
        "quality": {"disabled_feature_groups": feature_availability.get("disabled_feature_groups", [])},
        "labels": label_contract,
        "security_state": _security_evidence(security_provenance),
        "features": _feature_availability_evidence(feature_availability),
        "splits": _split_evidence(loaded["split_plan"]),
    }
    certificate = certify_training_sample(config, evidence, selected_features)
    certificate["schema_version"] = 2
    certificate["source_artifacts"] = {
        "dataset_root": f"datasets/{config.dataset_id}",
        "sample_contract": str(sample_contract_path),
        "legacy_candidate_manifest_used": False,
    }
    certificate["evidence_summary"] = {
        "labelable_dates": len(_as_list(label_contract.get("primary_daily"))),
        "disabled_feature_groups": feature_availability.get("disabled_feature_groups", []),
        "available_feature_count": len(selected_features),
        "security_state_validation": security_provenance.get("validation_status"),
    }
    certificate_path = _write_certificate(output_root, config.dataset_id, certificate)
    return {"certificate": certificate, "certificate_path": str(certificate_path)}


def _panel_evidence(quality: Mapping[str, Any]) -> dict[str, Any]:
    per_date = quality.get("per_date_universe_count", {})
    if not isinstance(per_date, Mapping):
        per_date = {}
    counts = [int(value) for value in per_date.values() if _is_int_like(value)]
    return {
        "ready": bool(quality.get("ready")),
        "row_count": int(quality.get("row_count", 0) or 0),
        "date_count": len(counts),
        "symbol_count": max(counts, default=0),
        "duplicate_key_count": int(quality.get("duplicate_key_count", 0) or 0),
        "required_date_coverage": quality.get("required_date_coverage"),
    }


def _label_evidence(labels: Mapping[str, Any], secondary: Mapping[str, Any]) -> dict[str, Any]:
    canonical_daily = []
    for row in _as_list(labels.get("daily_relevance_distribution_10d")):
        if not isinstance(row, Mapping):
            continue
        try:
            eligible_count = int(row.get("eligible_count", 0) or 0)
        except (TypeError, ValueError):
            eligible_count = 0
        if eligible_count <= 0:
            continue
        canonical_daily.append(
            {
                "trade_date": row.get("trade_date"),
                "eligible_count": eligible_count,
                "grade_3_or_higher_count": row.get("grade_3_or_higher_count"),
            }
        )
    return {
        "signal_time": secondary.get("signal_time"),
        "entry_time": secondary.get("entry_time"),
        # The legacy report only contains all-row ambiguity, not the subset
        # that remained eligible for training. Treat that missing distinction
        # as an evidence gap instead of falsely asserting contaminated rows.
        "eligible_ambiguous_path_count": labels.get("eligible_ambiguous_path_count_10d"),
        "canonical_daily": canonical_daily,
        "secondary_daily": _as_list(secondary.get("daily")),
    }


def _feature_evidence(feature_audit: Mapping[str, Any]) -> dict[str, Any]:
    coverage_by_feature: dict[str, float] = {}
    groups: dict[str, str] = {}
    for row in _as_list(feature_audit.get("coverage")):
        if not isinstance(row, Mapping):
            continue
        feature = row.get("feature")
        group = row.get("feature_group")
        coverage = row.get("coverage")
        if not isinstance(feature, str) or not isinstance(group, str):
            continue
        try:
            value = float(coverage)
        except (TypeError, ValueError):
            continue
        coverage_by_feature[feature] = min(coverage_by_feature.get(feature, 1.0), value)
        groups[feature] = group
    return {"coverage": coverage_by_feature, "groups": groups}


def _feature_availability_evidence(contract: Mapping[str, Any]) -> dict[str, Any]:
    coverage: dict[str, float] = {}
    groups: dict[str, str] = {}
    raw_coverage = contract.get("feature_coverage")
    if isinstance(raw_coverage, Mapping):
        for feature, row in raw_coverage.items():
            if not isinstance(row, Mapping):
                continue
            try:
                coverage[str(feature)] = float(row.get("minimum_fold_coverage"))
            except (TypeError, ValueError):
                continue
            group = row.get("feature_group")
            if isinstance(group, str):
                groups[str(feature)] = group
    return {"coverage": coverage, "groups": groups, "validation_status": contract.get("validation_status")}


def _security_evidence(provenance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provenance": dict(provenance) if provenance else None,
        "eligible_status_violation_count": provenance.get("eligible_status_violation_count", 0),
        "listing_age_nonmonotonic_count": provenance.get("listing_age_nonmonotonic_count", 0),
    }


def _split_evidence(splits: Mapping[str, Any]) -> dict[str, Any]:
    quadrants = splits.get("quadrants", {})
    if not isinstance(quadrants, Mapping):
        quadrants = {}
    return {
        "development_dates": _as_list(splits.get("development_dates")),
        "final_dates": _as_list(splits.get("final_dates")),
        "A_symbols": _as_list(quadrants.get("A_dev_train_symbols")),
        "C_symbols": _as_list(quadrants.get("C_dev_unseen_symbols")),
        "final_holdout_reserved": bool(splits.get("development_dates")) and bool(splits.get("final_dates")),
    }


def _selected_features(candidate: Mapping[str, Any]) -> list[str]:
    selected = candidate.get("selected_features")
    if not isinstance(selected, list) or not selected or not all(isinstance(value, str) for value in selected):
        raise ValueError("candidate manifest must contain a non-empty selected_features list")
    return list(selected)


def _selected_available_features(contract: Mapping[str, Any]) -> list[str]:
    selected = contract.get("allowed_features")
    if not isinstance(selected, list) or not selected or not all(isinstance(value, str) for value in selected):
        raise ValueError("feature availability contract must contain non-empty allowed_features")
    if contract.get("validation_status") != "verified":
        raise ValueError("feature availability contract is not verified")
    return list(selected)


def _load_contract_components(root: Path, contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = contract.get("components")
    if not isinstance(records, Mapping):
        raise ValueError("sample contract components are missing")
    result: dict[str, dict[str, Any]] = {}
    for name in ("label_contract", "security_state_provenance", "feature_availability_contract"):
        record = records.get(name)
        if not isinstance(record, Mapping):
            raise ValueError(f"sample contract component is missing: {name}")
        relative = Path(str(record.get("path", "")))
        if not relative.name or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"sample contract component path is invalid: {name}")
        payload = _load_json(root / relative)
        _verify_payload_hash(payload, name)
        if payload.get("sha256") != record.get("sha256"):
            raise ValueError(f"sample contract component hash mismatch: {name}")
        result[name] = payload
    return result


def _verify_contract_source_hashes(contract: Mapping[str, Any], observed: Mapping[str, str]) -> None:
    source_hashes = contract.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ValueError("sample contract source_hashes are missing")
    for name, actual in observed.items():
        if str(source_hashes.get(name, "")).lower() != actual.lower():
            raise ValueError(f"sample contract source hash mismatch: {name}")


def _verify_declared_security_sources(
    asset_root: Path, source_hashes: Mapping[str, Any], provenance: Mapping[str, Any]
) -> None:
    sources = _as_list(provenance.get("sources"))
    if not sources:
        return
    contexts: dict[str, tuple[Path, str, dict[str, str], str]] = {}
    for record in sources:
        if not isinstance(record, Mapping):
            raise ValueError("security provenance source record is invalid")
        asset_kind = str(record.get("asset_kind", "raw_collection"))
        if asset_kind not in contexts:
            contexts[asset_kind] = _security_source_context(asset_root, source_hashes, asset_kind)
        root, manifest_sha, registered, label = contexts[asset_kind]
        declared_manifest_sha = str(record.get("asset_manifest_sha256", "")).lower()
        if declared_manifest_sha and declared_manifest_sha != manifest_sha:
            raise ValueError(f"security provenance source manifest hash mismatch: {asset_kind}")
        if asset_kind == "static_security_state" and declared_manifest_sha != manifest_sha:
            raise ValueError("static security provenance source manifest hash is required")
        relative = Path(str(record.get("path", "")))
        expected = str(record.get("sha256", "")).lower()
        if not relative.name or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("security provenance source path is invalid")
        if registered.get(str(relative)) != expected:
            raise ValueError(f"security provenance source is not registered in {label}: {relative}")
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"security provenance source is unavailable: {relative}")
        if _sha256_file(path) != expected:
            raise ValueError(f"security provenance source hash mismatch: {relative}")


def _security_source_context(
    asset_root: Path, source_hashes: Mapping[str, Any], asset_kind: str
) -> tuple[Path, str, dict[str, str], str]:
    if asset_kind == "raw_collection":
        raw_manifest_sha = _required_sha256(source_hashes.get("raw_manifest"), "sample contract raw_manifest")
        root = (asset_root / "raw" / f"raw_{raw_manifest_sha[:16]}").resolve()
        manifest_path = root / "manifests" / "full-build.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"raw collection manifest is unavailable: {manifest_path}")
        if _sha256_file(manifest_path) != raw_manifest_sha:
            raise ValueError("raw collection manifest hash does not match sample contract")
        manifest = _load_json(manifest_path)
        registered = {
            str(item.get("path", "")): str(item.get("sha256", "")).lower()
            for item in _as_list(manifest.get("partitions"))
            if isinstance(item, Mapping) and item.get("status") == "adopted"
        }
        return root, raw_manifest_sha, registered, "raw collection manifest"
    if asset_kind == "static_security_state":
        manifest_sha = _required_sha256(
            source_hashes.get("static_security_state_manifest"),
            "sample contract static_security_state_manifest",
        )
        root = (asset_root / "security-state" / f"security_{manifest_sha[:16]}").resolve()
        asset = load_static_security_state_asset(root)
        if asset.manifest_sha256 != manifest_sha:
            raise ValueError("static security manifest hash does not match sample contract")
        registered = {
            str(item.get("path", "")): str(item.get("sha256", "")).lower()
            for item in _as_list(asset.manifest.get("partitions"))
            if isinstance(item, Mapping) and str(item.get("status", "")).startswith("valid-")
        }
        return root, manifest_sha, registered, "static security manifest"
    raise ValueError(f"unsupported security provenance asset_kind: {asset_kind}")


def _required_sha256(value: object, label: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} hash is required for security provenance")
    return text


def _verify_payload_hash(payload: Mapping[str, Any], label: str) -> None:
    expected = str(payload.get("sha256", "")).lower()
    value = dict(payload)
    value.pop("sha256", None)
    observed = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    if expected != observed:
        raise ValueError(f"{label} hash is invalid")


def _verify_registry_file(registry: Mapping[str, Any], path: Path, relative: Path) -> None:
    expected = None
    for record in _as_list(registry.get("files")):
        if isinstance(record, Mapping) and record.get("path") == str(relative):
            expected = str(record.get("sha256", ""))
            break
    if expected is None:
        raise ValueError(f"dataset registry is missing required file: {relative}")
    if not path.is_file() or _sha256_file(path) != expected:
        raise ValueError(f"manifest hash mismatch: {relative}")


def _verify_source_manifest_file(source_manifest: Mapping[str, Any], path: Path, relative: Path) -> None:
    expected = None
    for record in _as_list(source_manifest.get("files")):
        if isinstance(record, Mapping) and record.get("path") == str(relative):
            expected = str(record.get("sha256", ""))
            break
    if expected is None:
        raise ValueError(f"source manifest is missing required file: {relative}")
    if not path.is_file() or _sha256_file(path) != expected:
        raise ValueError(f"source manifest hash mismatch: {relative}")


def _write_certificate(output_root: Path, dataset_id: str, certificate: Mapping[str, Any]) -> Path:
    digest = hashlib.sha256(json.dumps(dict(certificate), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    destination = output_root / dataset_id / digest[:16] / "certificate.json"
    if destination.exists():
        existing = _load_json(destination)
        if existing != dict(certificate):
            raise ValueError(f"certificate path collision with different content: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, prefix=".certificate-", suffix=".tmp", delete=False) as temporary:
        json.dump(dict(certificate), temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, destination)
    return destination


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"required certification artifact is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"certification artifact must be a JSON object: {path}")
    return value


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    return {} if path is None else _load_json(Path(path))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_int_like(value: object) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False
