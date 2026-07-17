"""Read immutable ML artifacts and write a research sample certificate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .sample_certification import CertificationConfig, certify_training_sample


_REGISTRY_REQUIRED_PATHS = {
    "full_build_manifest": Path("manifests/full-build.json"),
    "quality_report": Path("artifacts/full-build/quality_report_v3.json"),
    "label_report": Path("artifacts/full-build/label_report_v3.json"),
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
) -> dict[str, Any]:
    """Certify one immutable research dataset and atomically preserve the result."""
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
