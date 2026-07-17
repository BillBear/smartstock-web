"""Offline evidence gates for reusable full-market ML training samples.

The certificate deliberately has no dependency on the production recommender.
It accepts normalized evidence assembled from immutable research artifacts and
returns a deterministic audit result.  A blocked certificate is still useful:
it records why the dataset must not be used for a formal model experiment.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from .features import FeatureLeakageError, assert_leak_free_schema


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECURITY_COVERAGE = frozenset({"listing", "delisting", "st", "suspension", "industry"})
_GROUP_ALIASES = {
    "cross_section_moneyflow": "moneyflow",
}


@dataclass(frozen=True)
class CertificationConfig:
    """Immutable policy for certifying an offline research sample."""

    dataset_id: str
    minimum_coverage: float
    minimum_feature_coverage: float
    minimum_listing_sessions: int
    production_integration_allowed: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CertificationConfig":
        dataset_id = str(raw.get("dataset_id", "")).strip()
        if not dataset_id:
            raise ValueError("dataset_id is required")
        try:
            minimum_coverage = float(raw["minimum_coverage"])
            minimum_feature_coverage = float(raw["minimum_feature_coverage"])
            minimum_listing_sessions = int(raw["minimum_listing_sessions"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("certification coverage and listing thresholds are required") from exc
        if not 0.0 < minimum_coverage <= 1.0:
            raise ValueError("minimum_coverage must be in (0, 1]")
        if not 0.0 < minimum_feature_coverage <= 1.0:
            raise ValueError("minimum_feature_coverage must be in (0, 1]")
        if minimum_listing_sessions < 120:
            raise ValueError("minimum_listing_sessions must be at least 120")
        if bool(raw.get("production_integration_allowed", False)):
            raise ValueError("production integration is forbidden for a training sample certificate")
        return cls(
            dataset_id=dataset_id,
            minimum_coverage=minimum_coverage,
            minimum_feature_coverage=minimum_feature_coverage,
            minimum_listing_sessions=minimum_listing_sessions,
            production_integration_allowed=False,
        )


def certify_training_sample(
    config: CertificationConfig,
    evidence: Mapping[str, Any],
    selected_features: Sequence[str],
) -> dict[str, Any]:
    """Evaluate the research-data contract without mutating any artifact."""
    blocking: set[str] = set()
    feature_names = [str(name) for name in selected_features]

    _check_input_hashes(evidence.get("input_hashes"), blocking)
    _check_panel(config, _mapping(evidence.get("panel")), blocking)
    _check_labels(_mapping(evidence.get("labels")), blocking)
    _check_security_state(_mapping(evidence.get("security_state")), blocking)
    _check_features(config, _mapping(evidence.get("quality")), _mapping(evidence.get("features")), feature_names, blocking)
    _check_splits(_mapping(evidence.get("splits")), blocking)

    return {
        "dataset_id": config.dataset_id,
        "status": "certified_research_sample" if not blocking else "blocked",
        "blocking_codes": sorted(blocking),
        "production_integration_allowed": False,
        "selected_features": feature_names,
        "input_hashes": dict(_mapping(evidence.get("input_hashes"))),
        "checks": {
            "panel": not any(code.startswith("panel:") for code in blocking),
            "labels": not any(code.startswith("labels:") for code in blocking),
            "security_state": not any(code.startswith("security_state:") for code in blocking),
            "features": not any(code.startswith(("features:", "feature_group_disabled:")) for code in blocking),
            "splits": not any(code.startswith("splits:") for code in blocking),
        },
    }


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _check_input_hashes(raw_hashes: object, blocking: set[str]) -> None:
    hashes = _mapping(raw_hashes)
    for name in ("dataset_registry", "full_build_manifest", "label_report", "split_plan"):
        value = str(hashes.get(name, "")).lower()
        if not _SHA256_RE.fullmatch(value):
            blocking.add(f"inputs:hash_missing_or_invalid:{name}")


def _check_panel(config: CertificationConfig, panel: Mapping[str, Any], blocking: set[str]) -> None:
    if not bool(panel.get("ready")):
        blocking.add("panel:not_ready")
    if int(panel.get("row_count", 0) or 0) <= 0:
        blocking.add("panel:empty")
    if int(panel.get("date_count", 0) or 0) <= 0:
        blocking.add("panel:no_trade_dates")
    if int(panel.get("symbol_count", 0) or 0) <= 0:
        blocking.add("panel:no_symbols")
    if int(panel.get("duplicate_key_count", 0) or 0) != 0:
        blocking.add("panel:duplicate_trade_date_symbol")
    coverage = _number(panel.get("required_date_coverage"))
    if coverage is None or coverage < config.minimum_coverage:
        blocking.add("panel:required_date_coverage_below_threshold")


def _check_labels(labels: Mapping[str, Any], blocking: set[str]) -> None:
    if labels.get("signal_time") != "after_close":
        blocking.add("labels:signal_time_not_after_close")
    if labels.get("entry_time") != "next_session_open":
        blocking.add("labels:entry_time_not_next_session_open")
    if int(labels.get("eligible_ambiguous_path_count", 0) or 0) != 0:
        blocking.add("labels:ambiguous_path_training_rows")

    canonical: dict[str, float] = {}
    for item in _sequence_of_mappings(labels.get("canonical_daily")):
        date = str(item.get("trade_date", ""))
        eligible = _number(item.get("eligible_count"))
        strong = _number(item.get("grade_3_or_higher_count"))
        if not date or eligible is None or strong is None or eligible <= 0:
            blocking.add("labels:canonical_daily_invalid")
            continue
        canonical[date] = strong / eligible
    if not canonical:
        blocking.add("labels:canonical_daily_missing")
        return
    for item in _sequence_of_mappings(labels.get("secondary_daily")):
        date = str(item.get("trade_date", ""))
        secondary = _number(item.get("alpha_top10_prevalence"))
        if date not in canonical:
            blocking.add(f"labels:secondary_date_not_canonical:{date or 'missing'}")
        elif secondary is None or abs(canonical[date] - secondary) > 1e-12:
            blocking.add(f"labels:secondary_daily_reconciliation_failed:{date}")


def _check_security_state(security: Mapping[str, Any], blocking: set[str]) -> None:
    provenance = security.get("provenance")
    if not isinstance(provenance, Mapping):
        blocking.add("security_state:point_in_time_provenance_missing")
    else:
        sha = str(provenance.get("sha256", "")).lower()
        covered = {str(item) for item in provenance.get("covers", [])}
        if not _SHA256_RE.fullmatch(sha) or not _SECURITY_COVERAGE.issubset(covered):
            blocking.add("security_state:point_in_time_provenance_missing")
    if int(security.get("eligible_status_violation_count", 0) or 0) != 0:
        blocking.add("security_state:ineligible_rows_present")
    if int(security.get("listing_age_nonmonotonic_count", 0) or 0) != 0:
        blocking.add("security_state:listing_age_nonmonotonic")


def _check_features(
    config: CertificationConfig,
    quality: Mapping[str, Any],
    features: Mapping[str, Any],
    selected_features: Sequence[str],
    blocking: set[str],
) -> None:
    try:
        assert_leak_free_schema(selected_features)
    except FeatureLeakageError:
        blocking.add("features:post_signal_schema")

    disabled_groups = {_normalize_group(item) for item in quality.get("disabled_feature_groups", [])}
    coverage = _mapping(features.get("coverage"))
    groups = _mapping(features.get("groups"))
    for feature in selected_features:
        feature_coverage = _number(coverage.get(feature))
        group = groups.get(feature)
        if feature_coverage is None or not isinstance(group, str) or not group:
            blocking.add(f"features:unknown_or_unprofiled:{feature}")
            continue
        if feature_coverage < config.minimum_feature_coverage:
            threshold = _threshold_token(config.minimum_feature_coverage)
            blocking.add(f"features:coverage_below_{threshold}:{feature}")
        normalized_group = _normalize_group(group)
        if normalized_group in disabled_groups:
            blocking.add(f"feature_group_disabled:{normalized_group}")


def _check_splits(splits: Mapping[str, Any], blocking: set[str]) -> None:
    development_dates = {str(value) for value in splits.get("development_dates", []) if str(value)}
    final_dates = {str(value) for value in splits.get("final_dates", []) if str(value)}
    if not development_dates or not final_dates:
        blocking.add("splits:development_or_final_dates_missing")
    if development_dates & final_dates:
        blocking.add("splits:development_final_dates_overlap")
    a_symbols = {str(value) for value in splits.get("A_symbols", []) if str(value)}
    c_symbols = {str(value) for value in splits.get("C_symbols", []) if str(value)}
    if not a_symbols or not c_symbols:
        blocking.add("splits:A_or_C_symbols_missing")
    if a_symbols & c_symbols:
        blocking.add("splits:A_C_symbols_overlap")
    if not bool(splits.get("final_holdout_reserved")):
        blocking.add("splits:final_holdout_not_reserved")


def _sequence_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_group(value: object) -> str:
    name = str(value).strip()
    return _GROUP_ALIASES.get(name, name)


def _threshold_token(value: float) -> str:
    return f"{value:.12g}".replace(".", "_")
