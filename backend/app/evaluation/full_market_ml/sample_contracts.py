"""Immutable evidence contracts for full-market ML sample quality."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


_SHA256_HEX_LENGTH = 64
_GROUP_ALIASES = {"cross_section_moneyflow": "moneyflow"}


def build_label_contract(
    label_audit: Mapping[str, Any],
    contract_sha256: str,
    dataset_registry_sha256: str,
) -> dict[str, Any]:
    """Define the ranking objective without conflating it with path diagnostics."""
    _require_sha256("research contract", contract_sha256)
    _require_sha256("dataset registry", dataset_registry_sha256)
    primary_daily = _normalise_primary_daily(label_audit.get("daily"))
    if not primary_daily:
        raise ValueError("primary label audit has no labelable dates")
    path_ambiguity_count = _nonnegative_int(
        label_audit.get("primary_path_ambiguity_count", label_audit.get("path_ambiguity_count", 0)),
        "primary_path_ambiguity_count",
    )
    path_eligible_ambiguity_count = _nonnegative_int(
        label_audit.get("path_label_eligible_ambiguous_count", 0),
        "path_label_eligible_ambiguous_count",
    )
    observed_path_ambiguity_count = _nonnegative_int(
        label_audit.get("observed_path_ambiguity_count", path_ambiguity_count),
        "observed_path_ambiguity_count",
    )
    payload: dict[str, Any] = {
        "label_contract_version": "alpha_risk_10d_v1",
        "primary_label": {
            "column": "alpha_relevance_grade_10d",
            "objective": "cross_sectional_alpha",
            "positive_column": "alpha_top10_10d",
        },
        "auxiliary_risk_labels": [
            {"column": "severe_negative_10d", "objective": "downside_path"},
            {"column": "sl_before_tp_10d", "objective": "stop_before_take_profit"},
            {"column": "future_limit_down_count_10d", "objective": "limit_down_risk"},
            {"column": "mae_10d", "objective": "maximum_adverse_excursion"},
        ],
        "signal_time": "after_close",
        "entry_time": "next_session_open",
        "horizon_sessions": 10,
        "primary_daily": primary_daily,
        "primary_path_ambiguity_count": path_ambiguity_count,
        "observed_path_ambiguity_count": observed_path_ambiguity_count,
        "path_label_eligible_ambiguous_count": path_eligible_ambiguity_count,
        "source_hashes": {
            "research_contract": contract_sha256.lower(),
            "dataset_registry": dataset_registry_sha256.lower(),
        },
    }
    return _with_sha256(payload)


def build_feature_availability_contract(
    quality_report: Mapping[str, Any],
    feature_audit: Mapping[str, Any],
    minimum_coverage: float = 0.95,
) -> dict[str, Any]:
    """Fail closed for features lacking stable OOF-fold coverage."""
    if not 0.0 < float(minimum_coverage) <= 1.0:
        raise ValueError("minimum feature coverage must be in (0, 1]")
    disabled_groups = sorted(
        {_normalise_group(value) for value in _sequence(quality_report.get("disabled_feature_groups"))}
    )
    observed: dict[str, dict[str, Any]] = {}
    for raw in _sequence(feature_audit.get("coverage")):
        if not isinstance(raw, Mapping):
            raise ValueError("feature audit coverage row must be an object")
        feature = str(raw.get("feature", "")).strip()
        group = _normalise_group(raw.get("feature_group", ""))
        if not feature or not group:
            raise ValueError("feature audit coverage row requires feature and feature_group")
        coverage = _probability(raw.get("coverage"), f"coverage:{feature}")
        record = observed.setdefault(
            feature,
            {"feature_group": group, "fold_coverage": [], "minimum_coverage": coverage},
        )
        if record["feature_group"] != group:
            raise ValueError(f"feature audit assigns multiple groups to {feature}")
        record["fold_coverage"].append(coverage)
        record["minimum_coverage"] = min(float(record["minimum_coverage"]), coverage)

    allowed: list[str] = []
    rejected: dict[str, dict[str, Any]] = {}
    feature_coverage: dict[str, dict[str, Any]] = {}
    for feature, record in sorted(observed.items()):
        group = str(record["feature_group"])
        observed_minimum = float(record["minimum_coverage"])
        feature_coverage[feature] = {
            "feature_group": group,
            "minimum_fold_coverage": observed_minimum,
            "fold_count": len(record["fold_coverage"]),
        }
        if group in disabled_groups:
            rejected[feature] = {"reason": f"feature_group_disabled:{group}", **feature_coverage[feature]}
        elif observed_minimum < float(minimum_coverage):
            rejected[feature] = {
                "reason": f"coverage_below_{_threshold_token(float(minimum_coverage))}",
                **feature_coverage[feature],
            }
        else:
            allowed.append(feature)

    payload: dict[str, Any] = {
        "feature_availability_contract_version": "oof_coverage_v1",
        "minimum_feature_coverage": float(minimum_coverage),
        "disabled_feature_groups": disabled_groups,
        "allowed_features": allowed,
        "rejected_features": rejected,
        "feature_coverage": feature_coverage,
        "validation_status": "verified",
    }
    return _with_sha256(payload)


def build_sample_contract(
    dataset_id: str,
    source_hashes: Mapping[str, Any],
    label_contract: Mapping[str, Any],
    security_state_provenance: Mapping[str, Any],
    feature_availability_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind immutable components into one research-only sample admission input."""
    normalized_dataset_id = str(dataset_id).strip()
    if not normalized_dataset_id:
        raise ValueError("sample contract dataset_id is required")
    normalized_hashes: dict[str, str] = {}
    for name in ("dataset_registry", "full_build_manifest", "quality_report", "split_plan"):
        value = source_hashes.get(name)
        _require_sha256(f"sample contract source {name}", value)
        normalized_hashes[name] = str(value).lower()
    for name, value in source_hashes.items():
        if name not in normalized_hashes:
            _require_sha256(f"sample contract source {name}", value)
            normalized_hashes[str(name)] = str(value).lower()
    component_payloads = {
        "label_contract": label_contract,
        "security_state_provenance": security_state_provenance,
        "feature_availability_contract": feature_availability_contract,
    }
    components: dict[str, dict[str, str]] = {}
    for name, payload in component_payloads.items():
        component_hash = payload.get("sha256") if isinstance(payload, Mapping) else None
        _require_sha256(f"sample contract component {name}", component_hash)
        components[name] = {"path": f"{name}.json", "sha256": str(component_hash).lower()}
    return _with_sha256(
        {
            "sample_contract_version": "full_market_sample_v1",
            "dataset_id": normalized_dataset_id,
            "source_hashes": dict(sorted(normalized_hashes.items())),
            "components": components,
            "production_integration_allowed": False,
        }
    )


def _normalise_primary_daily(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("primary label audit daily must be an array")
    result: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("primary label daily row must be an object")
        trade_date = str(raw.get("trade_date", "")).strip()
        if not trade_date:
            raise ValueError("primary label daily row has no trade_date")
        if trade_date in seen_dates:
            raise ValueError(f"duplicate primary label date: {trade_date}")
        seen_dates.add(trade_date)
        eligible_count = _nonnegative_int(raw.get("eligible_count"), f"eligible_count:{trade_date}")
        if eligible_count <= 0:
            raise ValueError(f"primary label eligible_count must be positive: {trade_date}")
        prevalence = _probability(raw.get("alpha_top10_prevalence"), f"alpha_top10_prevalence:{trade_date}")
        grade_rate = _probability(raw.get("grade_3_or_higher_rate"), f"grade_3_or_higher_rate:{trade_date}")
        result.append(
            {
                "trade_date": trade_date,
                "eligible_count": eligible_count,
                "alpha_top10_prevalence": prevalence,
                "grade_3_or_higher_rate": grade_rate,
            }
        )
    return result


def _sequence(value: object) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return list(value)


def _with_sha256(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result["sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def _require_sha256(label: str, value: object) -> None:
    text = str(value).strip().lower()
    if len(text) != _SHA256_HEX_LENGTH or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} hash must be a SHA256")


def _nonnegative_int(value: object, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if result < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return result


def _probability(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be between 0 and 1") from exc
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return result


def _normalise_group(value: object) -> str:
    group = str(value).strip()
    return _GROUP_ALIASES.get(group, group)


def _threshold_token(value: float) -> str:
    return f"{value:.12g}".replace(".", "_")
