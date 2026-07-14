"""Immutable research contract for the full-market ranking reset."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


REQUIRED_BASELINES = (
    "random",
    "adjusted_return_20d",
    "adjusted_return_60d",
    "amount_ascending",
    "amount_descending",
    "registered_single_feature",
)
ALLOWED_MODEL_FAMILIES = ("linear_scorecard", "lightgbm_lambdarank")
RESEARCH_STATUS_FIELDS = (
    "engineering_valid",
    "research_design_valid",
    "model_gate_passed",
    "production_candidate",
)


@dataclass(frozen=True)
class RankingResearchContract:
    dataset_id: str
    run_id: str
    feature_blocks: tuple[tuple[str, tuple[str, ...]], ...]
    source_config_sha256: str = ""
    signal_timing: str = "after_close"
    horizon: int = 10
    minimum_listing_sessions: int = 120
    commission_per_side: float = 0.0003
    slippage_per_side: float = 0.001
    outer_folds: int = 5
    embargo_sessions: int = 20
    minimum_inner_fit_dates: int = 60
    minimum_inner_early_stop_dates: int = 20
    minimum_inner_selection_dates: int = 20
    required_baselines: tuple[str, ...] = REQUIRED_BASELINES
    model_families: tuple[str, ...] = ALLOWED_MODEL_FAMILIES
    seeds: tuple[int, ...] = (17, 42, 73)
    maximum_feature_count: int = 60
    rss_soft_limit_gb: float = 12.0
    rss_abort_gb: float = 13.0
    future_holdout_status: str = "sealed"
    archive_format: str = "tar.gz"
    delete_rebuildable_after_verify: bool = True

    def validate(self) -> None:
        if not self.dataset_id or not self.run_id:
            raise ValueError("dataset_id and run_id must not be empty")
        if self.signal_timing != "after_close" or self.horizon != 10:
            raise ValueError("signal_timing must be after_close and horizon must be 10")
        if self.minimum_listing_sessions < 120:
            raise ValueError("minimum_listing_sessions must be at least 120")
        if self.commission_per_side < 0 or self.slippage_per_side < 0:
            raise ValueError("execution costs must not be negative")
        if self.outer_folds != 5 or self.embargo_sessions < self.horizon:
            raise ValueError("outer_folds must be 5 and embargo_sessions must cover the horizon")
        if self.minimum_inner_fit_dates < 60:
            raise ValueError("minimum_inner_fit_dates must be at least 60")
        if self.minimum_inner_early_stop_dates < 20:
            raise ValueError("minimum_inner_early_stop_dates must be at least 20")
        if self.minimum_inner_selection_dates < 20:
            raise ValueError("minimum_inner_selection_dates must be at least 20")
        missing_baselines = sorted(set(REQUIRED_BASELINES) - set(self.required_baselines))
        if missing_baselines:
            raise ValueError("required_baselines missing: " + ", ".join(missing_baselines))
        unsupported_models = sorted(set(self.model_families) - set(ALLOWED_MODEL_FAMILIES))
        if unsupported_models or not self.model_families:
            raise ValueError("model_families contain unsupported or empty values")
        if not self.feature_blocks:
            raise ValueError("feature_blocks must not be empty")
        names = [name for name, _ in self.feature_blocks]
        features = [feature for _, block in self.feature_blocks for feature in block]
        if any(not name or not block for name, block in self.feature_blocks):
            raise ValueError("feature_blocks must have non-empty names and schemas")
        if len(names) != len(set(names)) or len(features) != len(set(features)):
            raise ValueError("feature_blocks must not contain duplicate names or features")
        if len(features) > self.maximum_feature_count or self.maximum_feature_count > 60:
            raise ValueError("maximum_feature_count must not exceed 60")
        if not self.seeds:
            raise ValueError("seeds must not be empty")
        if self.rss_soft_limit_gb <= 0 or self.rss_soft_limit_gb > 12.0:
            raise ValueError("rss_soft_limit_gb must be in (0, 12]")
        if self.rss_abort_gb <= self.rss_soft_limit_gb or self.rss_abort_gb > 13.0:
            raise ValueError("rss_abort_gb must be greater than soft limit and at most 13")
        if self.future_holdout_status != "sealed":
            raise ValueError("future_holdout_status must remain sealed")
        if self.archive_format != "tar.gz":
            raise ValueError("archive_format must be tar.gz")

    def canonical_payload(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def sha256(self) -> str:
        payload = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def contract_from_mapping(
    value: Mapping[str, Any], *, source_config_sha256: str = ""
) -> RankingResearchContract:
    run = _mapping(value, "run")
    execution = _mapping(value, "execution")
    sample = _mapping(value, "sample")
    splits = _mapping(value, "splits")
    models = _mapping(value, "models")
    features = _mapping(value, "features")
    resources = _mapping(value, "resources")
    artifacts = _mapping(value, "artifacts")
    blocks = _mapping(features, "blocks")
    contract = RankingResearchContract(
        dataset_id=str(run.get("dataset_id", "")),
        run_id=str(run.get("id", "")),
        source_config_sha256=source_config_sha256,
        signal_timing=str(execution.get("signal_timing", "")),
        horizon=int(execution.get("horizon", 0)),
        minimum_listing_sessions=int(sample.get("minimum_listing_sessions", 0)),
        commission_per_side=float(execution.get("commission_per_side", -1)),
        slippage_per_side=float(execution.get("slippage_per_side", -1)),
        outer_folds=int(splits.get("outer_folds", 0)),
        embargo_sessions=int(splits.get("embargo_sessions", 0)),
        minimum_inner_fit_dates=int(splits.get("minimum_inner_fit_dates", 0)),
        minimum_inner_early_stop_dates=int(splits.get("minimum_inner_early_stop_dates", 0)),
        minimum_inner_selection_dates=int(splits.get("minimum_inner_selection_dates", 0)),
        required_baselines=tuple(str(item) for item in _sequence(value, "baselines")),
        model_families=tuple(str(item) for item in _sequence(models, "families")),
        seeds=tuple(int(item) for item in _sequence(models, "seeds")),
        maximum_feature_count=int(features.get("maximum_count", 0)),
        feature_blocks=tuple(
            (str(name), tuple(str(feature) for feature in _as_sequence(schema, f"features.blocks.{name}")))
            for name, schema in sorted(blocks.items())
        ),
        rss_soft_limit_gb=float(resources.get("rss_soft_limit_gb", 0)),
        rss_abort_gb=float(resources.get("rss_abort_gb", 0)),
        future_holdout_status=str(run.get("future_holdout_status", "")),
        archive_format=str(artifacts.get("archive_format", "")),
        delete_rebuildable_after_verify=bool(
            artifacts.get("delete_rebuildable_after_verify", False)
        ),
    )
    contract.validate()
    return contract


def validate_inner_date_roles(
    contract: RankingResearchContract,
    fit_dates: Sequence[str],
    early_stop_dates: Sequence[str],
    selection_dates: Sequence[str],
    outer_validation_dates: Sequence[str],
) -> None:
    contract.validate()
    roles = {
        "fit": tuple(str(item) for item in fit_dates),
        "early_stop": tuple(str(item) for item in early_stop_dates),
        "selection": tuple(str(item) for item in selection_dates),
        "outer_validation": tuple(str(item) for item in outer_validation_dates),
    }
    minimums = {
        "fit": contract.minimum_inner_fit_dates,
        "early_stop": contract.minimum_inner_early_stop_dates,
        "selection": contract.minimum_inner_selection_dates,
    }
    for name, minimum in minimums.items():
        if len(set(roles[name])) < minimum:
            raise ValueError(f"minimum_inner_{name}_dates requires at least {minimum} unique dates")
    for name, values in roles.items():
        if not values or len(values) != len(set(values)):
            raise ValueError(f"{name} dates must be non-empty and unique")
    role_names = tuple(roles)
    for index, left in enumerate(role_names):
        for right in role_names[index + 1 :]:
            if set(roles[left]) & set(roles[right]):
                raise ValueError("inner and outer date roles must be disjoint")
    if not (
        max(roles["fit"]) < min(roles["early_stop"])
        and max(roles["early_stop"]) < min(roles["selection"])
        and max(roles["selection"]) < min(roles["outer_validation"])
    ):
        raise ValueError("inner and outer date roles must be chronological")


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    result = value.get(key)
    if not isinstance(result, Mapping):
        raise ValueError(f"missing mapping: {key}")
    return result


def _sequence(value: Mapping[str, Any], key: str) -> Sequence[Any]:
    return _as_sequence(value.get(key), key)


def _as_sequence(value: Any, key: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"missing array: {key}")
    return value
