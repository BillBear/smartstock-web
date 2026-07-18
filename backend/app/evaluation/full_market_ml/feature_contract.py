"""One point-in-time feature contract for offline research and online scoring.

The contract intentionally wraps the existing leak-free full-market builder
instead of reimplementing technical indicators in the service layer.  An online
caller must therefore supply the same normalized panel and source provenance as
the offline experiment before a model artifact can be considered reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Literal, Mapping, Sequence

import numpy as np
import pandas as pd

from .features import CORE_FEATURE_SPECS, FeatureSpec, build_features_for_date


FEATURE_CONTRACT_VERSION = "full_market_online_parity_v2"
MINIMUM_CORE_FOLD_COVERAGE = 0.95
PARITY_TOLERANCE = 1e-8
MONEYFLOW_MINIMUM_COVERAGE = 0.95


class FeatureContractError(ValueError):
    """Raised when a model input violates the registered feature contract."""


class SourceFreshnessError(FeatureContractError):
    """Raised when online data is too old for the requested signal date."""


@dataclass(frozen=True)
class RegisteredFeature:
    name: str
    group: str
    source: str
    formula: str
    lookback_sessions: int
    availability: Literal["required", "optional"]
    allowed_quality: Sequence[str]
    adjusted_status: str
    missing_policy: str


@dataclass(frozen=True)
class FeatureContract:
    version: str
    features: tuple[RegisteredFeature, ...]
    disabled_groups: tuple[str, ...]
    minimum_fold_coverage: float = MINIMUM_CORE_FOLD_COVERAGE
    parity_tolerance: float = PARITY_TOLERANCE

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(feature.name for feature in self.features)

    @property
    def required_feature_names(self) -> tuple[str, ...]:
        return tuple(feature.name for feature in self.features if feature.availability == "required")

    @property
    def required_sources(self) -> tuple[str, ...]:
        return tuple(sorted({feature.source for feature in self.features if feature.availability == "required" and feature.source != "derived"}))

    @property
    def registered_sources(self) -> tuple[str, ...]:
        """All non-derived sources, including optional fields that may be selected later."""
        return tuple(sorted({feature.source for feature in self.features if feature.source != "derived"}))

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "disabled_groups": list(self.disabled_groups),
            "minimum_fold_coverage": self.minimum_fold_coverage,
            "parity_tolerance": self.parity_tolerance,
            "features": [
                {
                    "name": feature.name,
                    "group": feature.group,
                    "source": feature.source,
                    "formula": feature.formula,
                    "lookback_sessions": feature.lookback_sessions,
                    "availability": feature.availability,
                    "allowed_quality": list(feature.allowed_quality),
                    "adjusted_status": feature.adjusted_status,
                    "missing_policy": feature.missing_policy,
                }
                for feature in self.features
            ],
        }

    def sha256(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def source_freshness_limit(self, source: str) -> tuple[str, int]:
        """Return the contract's maximum age as ``(unit, value)``.

        Daily observations must be current or one session stale.  Fundamentals
        and shareholder records are not core features today, but their limits
        are registered here so later experimental blocks cannot silently use
        a weaker point-in-time rule.
        """
        if source in {"daily", "daily+adj_factor", "daily_basic", "moneyflow", "moneyflow+daily"}:
            return ("sessions", 1)
        if source in {"fina_indicator", "financial_indicator", "shareholder"}:
            return ("calendar_days", 180)
        return ("calendar_days", 180)


@dataclass(frozen=True)
class FeatureCoverageResult:
    coverage_by_fold: Mapping[str, Mapping[str, float]]
    passed: bool


_OPTIONAL_GROUPS = {"valuation_liquidity"}


def build_full_market_feature_contract(
    *,
    moneyflow_coverage: float,
    include_moneyflow: bool = False,
) -> FeatureContract:
    """Build the frozen core schema from explicit offline feature definitions.

    News has no entry in ``CORE_FEATURE_SPECS`` and cannot be registered here.
    Money flow needs observed field coverage, not an imputed proxy.  The current
    two-year asset's 94.92% coverage misses the 95% gate, so it remains disabled.
    """
    if not 0.0 <= float(moneyflow_coverage) <= 1.0:
        raise FeatureContractError("moneyflow coverage must be between zero and one")
    if include_moneyflow and moneyflow_coverage < MONEYFLOW_MINIMUM_COVERAGE:
        raise FeatureContractError(
            "moneyflow coverage is below the observed-only contract gate: "
            f"actual={moneyflow_coverage:.4f} required={MONEYFLOW_MINIMUM_COVERAGE:.4f}"
        )

    features: list[RegisteredFeature] = []
    for spec in CORE_FEATURE_SPECS:
        if "moneyflow" in spec.feature_group and not include_moneyflow:
            continue
        if "news" in spec.name.lower() or "news" in spec.source_endpoint.lower():
            raise FeatureContractError(f"news cannot enter the core contract: {spec.name}")
        features.append(_registered_feature(spec))
    disabled_groups = () if include_moneyflow else ("moneyflow",)
    return FeatureContract(
        version=FEATURE_CONTRACT_VERSION,
        features=tuple(features),
        disabled_groups=disabled_groups,
    )


def build_features_as_of(
    rows: pd.DataFrame,
    *,
    as_of_date: str,
    contract: FeatureContract,
) -> pd.DataFrame:
    """Build the contract matrix from normalized full-market rows as of one date."""
    _assert_feature_schema(contract)
    matrix = build_features_for_date(
        None,
        rows,
        as_of_date,
        feature_schema=contract.feature_names,
    )
    return matrix.loc[:, ["trade_date", "symbol", *contract.feature_names]].copy()


def assert_contract_coverage(
    matrix: pd.DataFrame,
    contract: FeatureContract,
    *,
    folds: Mapping[str, Sequence[str]],
) -> FeatureCoverageResult:
    """Reject a contract if any required feature falls below coverage in a fold."""
    required = {"trade_date", *contract.required_feature_names}
    missing = sorted(required - set(matrix.columns))
    if missing:
        raise FeatureContractError("feature matrix missing registered core columns: " + ", ".join(missing))
    coverage_by_fold: dict[str, dict[str, float]] = {}
    failures: list[str] = []
    for fold_name, dates in folds.items():
        selected = matrix.loc[matrix["trade_date"].astype(str).isin({str(value) for value in dates})]
        if selected.empty:
            raise FeatureContractError(f"feature coverage fold has no rows: {fold_name}")
        coverage: dict[str, float] = {}
        for feature in contract.required_feature_names:
            values = pd.to_numeric(selected[feature], errors="coerce")
            value = float(np.isfinite(values).mean())
            coverage[feature] = value
            if value < contract.minimum_fold_coverage:
                failures.append(f"{fold_name}:{feature}={value:.4f}")
        coverage_by_fold[str(fold_name)] = coverage
    if failures:
        raise FeatureContractError(
            "registered core feature coverage below "
            f"{contract.minimum_fold_coverage:.2%}: " + ", ".join(failures)
        )
    return FeatureCoverageResult(coverage_by_fold=coverage_by_fold, passed=True)


def validate_online_provenance(
    rows: pd.DataFrame,
    *,
    as_of_date: str,
    contract: FeatureContract,
    source_as_of_dates: Mapping[str, str],
    source_qualities: Mapping[str, str],
) -> None:
    """Check source quality and point-in-time freshness before online scoring."""
    as_of = _parse_date(as_of_date, "as_of_date")
    sessions = tuple(sorted({str(value) for value in pd.to_datetime(rows["trade_date"], errors="coerce").dropna().dt.strftime("%Y-%m-%d") if value <= as_of.isoformat()}))
    if as_of.isoformat() not in sessions:
        raise SourceFreshnessError(f"online panel has no signal-date rows: {as_of.isoformat()}")
    for source in contract.registered_sources:
        quality = source_qualities.get(source)
        if quality != "valid-with-rows":
            raise FeatureContractError(f"source quality is not eligible for {source}: {quality or 'missing'}")
        raw_date = source_as_of_dates.get(source)
        if raw_date is None:
            raise SourceFreshnessError(f"missing source as-of date for {source}")
        source_date = _parse_date(raw_date, f"source_as_of_dates[{source}]")
        if source_date > as_of:
            raise SourceFreshnessError(f"source {source} is dated after the signal date")
        unit, maximum = contract.source_freshness_limit(source)
        if unit == "sessions":
            if source_date.isoformat() not in sessions:
                raise SourceFreshnessError(f"source {source} as-of date is absent from the online session calendar")
            age = len([session for session in sessions if source_date.isoformat() < session <= as_of.isoformat()])
        else:
            age = (as_of - source_date).days
        if age > maximum:
            raise SourceFreshnessError(
                f"source {source} is stale: age={age} {unit}, maximum={maximum}"
            )


def _registered_feature(spec: FeatureSpec) -> RegisteredFeature:
    availability: Literal["required", "optional"] = "optional" if spec.feature_group in _OPTIONAL_GROUPS else "required"
    return RegisteredFeature(
        name=spec.name,
        group=spec.feature_group,
        source=spec.source_endpoint,
        formula=_session_semantic_formula(spec),
        lookback_sessions=spec.earliest_lookback,
        availability=availability,
        allowed_quality=("valid-with-rows",),
        adjusted_status=spec.adjusted_status,
        missing_policy=spec.missing_policy,
    )


def _assert_feature_schema(contract: FeatureContract) -> None:
    if not contract.features:
        raise FeatureContractError("feature contract cannot be empty")
    duplicates = sorted({name for name in contract.feature_names if contract.feature_names.count(name) > 1})
    if duplicates:
        raise FeatureContractError("feature contract has duplicate names: " + ", ".join(duplicates))
    if any("news" in name.lower() for name in contract.feature_names):
        raise FeatureContractError("news features are prohibited from the core contract")
    if "moneyflow" in contract.disabled_groups and any("moneyflow" in feature.group for feature in contract.features):
        raise FeatureContractError("disabled moneyflow features cannot be registered")


def _session_semantic_formula(spec: FeatureSpec) -> str:
    if spec.earliest_lookback <= 0:
        return spec.formula
    return f"{spec.formula}; requires consecutive market-session history"


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise SourceFreshnessError(f"{label} must be an ISO-8601 date") from error
