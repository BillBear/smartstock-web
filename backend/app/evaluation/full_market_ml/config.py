from __future__ import annotations

import calendar
import hashlib
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


_REQUIRED_SECTIONS = ("dates", "sample", "splits", "training", "resources", "collection")


@dataclass(frozen=True)
class DatesConfig:
    signal_start: str
    signal_end: str
    holdout_start: str
    holdout_end: str


@dataclass(frozen=True)
class SampleConfig:
    minimum_daily_symbols: int


@dataclass(frozen=True)
class SplitsConfig:
    embargo_trade_days: int
    walk_forward_folds: int


@dataclass(frozen=True)
class TrainingConfig:
    seeds: tuple[int, ...]


@dataclass(frozen=True)
class ResourcesConfig:
    memory_limit_gb: float


@dataclass(frozen=True)
class CollectionConfig:
    request_pacing_seconds: float
    namechange_history_start: str


@dataclass(frozen=True)
class FullMarketMLConfig:
    dates: DatesConfig
    sample: SampleConfig
    splits: SplitsConfig
    training: TrainingConfig
    resources: ResourcesConfig
    collection: CollectionConfig
    sha256: str


def config_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_full_market_ml_config(path: str | Path) -> FullMarketMLConfig:
    config_path = Path(path)
    config_bytes = config_path.read_bytes()
    config_digest = hashlib.sha256(config_bytes).hexdigest()
    raw_config = tomllib.loads(config_bytes.decode("utf-8"))

    _require_sections(raw_config)
    dates = _load_dates(_section(raw_config, "dates"))
    sample = SampleConfig(minimum_daily_symbols=_integer(raw_config, "sample", "minimum_daily_symbols"))
    splits = SplitsConfig(
        embargo_trade_days=_integer(raw_config, "splits", "embargo_trade_days"),
        walk_forward_folds=_integer(raw_config, "splits", "walk_forward_folds"),
    )
    training = TrainingConfig(seeds=_integer_tuple(raw_config, "training", "seeds"))
    resources = ResourcesConfig(memory_limit_gb=_number(raw_config, "resources", "memory_limit_gb"))
    collection = CollectionConfig(
        request_pacing_seconds=_number(raw_config, "collection", "request_pacing_seconds"),
        namechange_history_start=_string(_section(raw_config, "collection"), "collection", "namechange_history_start"),
    )

    _validate_dates(dates)
    if splits.walk_forward_folds < 5:
        raise ValueError("walk_forward_folds must be at least 5")
    if resources.memory_limit_gb > 12:
        raise ValueError("memory_limit_gb must not exceed 12")
    if collection.request_pacing_seconds <= 0:
        raise ValueError("request_pacing_seconds must be greater than zero")
    if _parse_date("collection.namechange_history_start", collection.namechange_history_start) > _parse_date(
        "signal_start", dates.signal_start
    ):
        raise ValueError("collection.namechange_history_start must be on or before signal_start")

    return FullMarketMLConfig(
        dates=dates,
        sample=sample,
        splits=splits,
        training=training,
        resources=resources,
        collection=collection,
        sha256=config_digest,
    )


def _require_sections(raw_config: dict[str, Any]) -> None:
    for name in _REQUIRED_SECTIONS:
        if name not in raw_config or not isinstance(raw_config[name], dict):
            raise ValueError(f"missing required section: {name}")


def _section(raw_config: dict[str, Any], section: str) -> dict[str, Any]:
    value = raw_config[section]
    if not isinstance(value, dict):
        raise ValueError(f"missing required section: {section}")
    return value


def _load_dates(raw_dates: dict[str, Any]) -> DatesConfig:
    return DatesConfig(
        signal_start=_string(raw_dates, "dates", "signal_start"),
        signal_end=_string(raw_dates, "dates", "signal_end"),
        holdout_start=_string(raw_dates, "dates", "holdout_start"),
        holdout_end=_string(raw_dates, "dates", "holdout_end"),
    )


def _string(section: dict[str, Any], section_name: str, key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{section_name}.{key} must be a string")
    return value


def _integer(raw_config: dict[str, Any], section: str, key: str) -> int:
    value = _section(raw_config, section).get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{section}.{key} must be an integer")
    return value


def _integer_tuple(raw_config: dict[str, Any], section: str, key: str) -> tuple[int, ...]:
    value = _section(raw_config, section).get(key)
    if not isinstance(value, list) or any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise ValueError(f"{section}.{key} must be an array of integers")
    return tuple(value)


def _number(raw_config: dict[str, Any], section: str, key: str) -> float:
    value = _section(raw_config, section).get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{section}.{key} must be a number")
    return float(value)


def _validate_dates(dates: DatesConfig) -> None:
    signal_start = _parse_date("signal_start", dates.signal_start)
    signal_end = _parse_date("signal_end", dates.signal_end)
    holdout_start = _parse_date("holdout_start", dates.holdout_start)
    holdout_end = _parse_date("holdout_end", dates.holdout_end)

    if signal_start >= signal_end:
        raise ValueError("signal_start must be before signal_end")
    if holdout_start >= holdout_end:
        raise ValueError("holdout_start must be before holdout_end")
    if holdout_start < signal_start or holdout_end > signal_end:
        raise ValueError("holdout dates must be within the signal period")
    if holdout_end < _add_calendar_month(holdout_start):
        raise ValueError("holdout period must be at least one calendar month")


def _parse_date(name: str, value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 date") from error


def _add_calendar_month(value: date) -> date:
    year = value.year + (value.month == 12)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
