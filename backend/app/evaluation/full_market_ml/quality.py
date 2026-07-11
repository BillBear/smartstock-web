"""Blocking, read-only data-quality gates for full-market ML training inputs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from .collector import CORE_DAILY_ENDPOINTS
from .config import FullMarketMLConfig


PRIMARY_KEY = ("trade_date", "symbol")
REQUIRED_COLUMNS = (
    "trade_date",
    "symbol",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "valid_ohlc",
    "listing_age_trade_days",
    "industry_l1",
)
REQUIRED_VALUE_COLUMNS = REQUIRED_COLUMNS[2:]
CORE_JOIN_COLUMNS = ("valid_ohlc", "listing_age_trade_days")
REQUIRED_BOARDS = ("MAIN", "CHINEXT", "STAR")
OPTIONAL_MONEYFLOW_COLUMNS = ("net_mf_amount", "net_mf_vol", "moneyflow")
OPTIONAL_MONEYFLOW_MINIMUM_COVERAGE = 0.95
READY_PARTITION_STATUSES = ("collected", "reused", "adopted")


class TrainingBlockedError(RuntimeError):
    """Raised when immutable input evidence is insufficient to start training."""

    def __init__(self, blocking_codes: tuple[str, ...]):
        self.blocking_codes = blocking_codes
        super().__init__("training blocked: " + ", ".join(blocking_codes))


@dataclass(frozen=True)
class QualityReport:
    """Serializable audit outcome. This object never mutates panel data."""

    blocking_codes: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    disabled_feature_groups: tuple[str, ...]
    duplicate_key_count: int
    per_date_universe_count: dict[str, int]
    required_date_coverage: float
    expected_trade_dates: tuple[str, ...]
    observed_trade_dates: tuple[str, ...]
    missingness: dict[str, float]
    join_coverage: dict[str, float]
    listing_coverage: float
    board_coverage: dict[str, float]
    per_date_board_coverage: dict[str, dict[str, float]]
    industry_coverage: float
    moneyflow_coverage: float | None
    sample_estimates: dict[str, int]
    raw_valid_row_count: int
    row_count: int

    @property
    def ready(self) -> bool:
        return not self.blocking_codes

    def require_ready(self) -> None:
        if not self.ready:
            raise TrainingBlockedError(self.blocking_codes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blocking_codes": list(self.blocking_codes),
            "exclusion_reasons": list(self.exclusion_reasons),
            "disabled_feature_groups": list(self.disabled_feature_groups),
            "duplicate_key_count": self.duplicate_key_count,
            "per_date_universe_count": self.per_date_universe_count,
            "required_date_coverage": self.required_date_coverage,
            "expected_trade_dates": list(self.expected_trade_dates),
            "observed_trade_dates": list(self.observed_trade_dates),
            "missingness": self.missingness,
            "join_coverage": self.join_coverage,
            "listing_coverage": self.listing_coverage,
            "board_coverage": self.board_coverage,
            "per_date_board_coverage": self.per_date_board_coverage,
            "industry_coverage": self.industry_coverage,
            "moneyflow_coverage": self.moneyflow_coverage,
            "sample_estimates": self.sample_estimates,
            "raw_valid_row_count": self.raw_valid_row_count,
            "row_count": self.row_count,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True)

    def to_csv_rows(self) -> list[dict[str, Any]]:
        """Return flat rows suitable for a later CSV writer without performing I/O."""
        rows = [{"record_type": "summary", **self.to_dict()}]
        rows.extend(
            {"record_type": "date", "trade_date": trade_date, "universe_count": count}
            for trade_date, count in self.per_date_universe_count.items()
        )
        return rows


def audit_panel_quality(config: FullMarketMLConfig, panel_dataset: pd.DataFrame, manifest: Any) -> QualityReport:
    """Audit immutable panel rows and collection evidence before features or labels run."""
    panel = _panel_frame(panel_dataset)
    blocking_codes: set[str] = set()
    exclusions: set[str] = set()
    disabled_groups: set[str] = set()

    manifest_codes, manifest_gate_codes, expected_dates, manifest_disabled = _manifest_evidence(config, manifest)
    if manifest is None:
        blocking_codes.add("manifest_missing")
        exclusions.add("manifest:missing")
    elif manifest_codes:
        blocking_codes.add("manifest_not_ready")
        exclusions.update(f"manifest:{code}" for code in manifest_codes)
    blocking_codes.update(manifest_gate_codes)
    exclusions.update(f"manifest_gate:{code}" for code in manifest_gate_codes)
    disabled_groups.update(manifest_disabled)

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in panel]
    if missing_columns:
        blocking_codes.add("required_columns_missing")
        exclusions.update(f"missing_column:{column}" for column in missing_columns)
    panel = panel.copy()
    for column in REQUIRED_COLUMNS:
        if column not in panel:
            panel[column] = pd.NA
    panel["trade_date"] = panel["trade_date"].map(_date_text)
    panel["symbol"] = panel["symbol"].astype("string").fillna("").str.split(".", regex=False).str[0].str.zfill(6)

    duplicate_key_count = int(panel.duplicated(list(PRIMARY_KEY), keep="first").sum())
    if duplicate_key_count:
        blocking_codes.add("duplicate_primary_keys")
        exclusions.add("duplicate:trade_date,symbol")

    missingness = {column: _missing_ratio(panel[column]) for column in REQUIRED_VALUE_COLUMNS}
    required_value_columns = tuple(
        column for column in REQUIRED_VALUE_COLUMNS if column != "industry_l1" or "industry_relative" not in disabled_groups
    )
    if any(missingness[column] > 0 for column in required_value_columns):
        blocking_codes.add("required_feature_missingness")
        exclusions.update(f"missing:{column}" for column in required_value_columns if missingness[column] > 0)

    valid_rows = _valid_ohlc(panel)
    raw_valid_row_count = int(valid_rows.sum())
    if raw_valid_row_count != len(panel):
        blocking_codes.add("invalid_ohlc")
        exclusions.add("invalid:adjusted_ohlc")

    join_coverage = {column: _non_missing_ratio(panel[column]) for column in CORE_JOIN_COLUMNS}
    if any(coverage < 1.0 for coverage in join_coverage.values()):
        blocking_codes.add("required_join_coverage_incomplete")
        exclusions.update(f"join_missing:{column}" for column, coverage in join_coverage.items() if coverage < 1.0)

    observed_dates = tuple(sorted(date for date in panel["trade_date"].unique() if date))
    expected_date_set = set(expected_dates)
    observed_date_set = set(observed_dates)
    required_date_coverage = len(expected_date_set & observed_date_set) / len(expected_date_set) if expected_date_set else 0.0
    if not expected_date_set or required_date_coverage < 1.0:
        blocking_codes.add("required_date_coverage_incomplete")
        exclusions.update(f"missing_date:{date}" for date in sorted(expected_date_set - observed_date_set))

    per_date_universe_count = {
        str(trade_date): int(count)
        for trade_date, count in panel.groupby("trade_date", dropna=False)["symbol"].nunique().items()
        if trade_date
    }
    insufficient_dates = [
        date for date in expected_dates if per_date_universe_count.get(date, 0) < config.sample.minimum_daily_symbols
    ]
    if insufficient_dates:
        blocking_codes.add("minimum_daily_universe_not_met")
        exclusions.update(f"minimum_daily_symbols:{date}" for date in insufficient_dates)

    listing_coverage = float(pd.to_numeric(panel["listing_age_trade_days"], errors="coerce").ge(20).mean()) if len(panel) else 0.0
    if listing_coverage <= 0.0:
        blocking_codes.add("listing_coverage_incomplete")
        exclusions.add("listing_age:below_20_sessions")

    board_coverage = _board_coverage(panel["symbol"])
    if any(board_coverage[board] <= 0.0 for board in REQUIRED_BOARDS):
        blocking_codes.add("board_coverage_incomplete")
        exclusions.update(f"board_missing:{board}" for board in REQUIRED_BOARDS if board_coverage[board] <= 0.0)
    per_date_board_coverage = {
        trade_date: _board_coverage(panel.loc[panel["trade_date"] == trade_date, "symbol"])
        for trade_date in expected_dates
    }
    incomplete_board_dates = [
        trade_date
        for trade_date, coverage in per_date_board_coverage.items()
        if any(coverage[board] <= 0.0 for board in REQUIRED_BOARDS)
    ]
    if incomplete_board_dates:
        blocking_codes.add("daily_board_coverage_incomplete")
        exclusions.update(f"daily_board_missing:{trade_date}:{board}" for trade_date in incomplete_board_dates for board in REQUIRED_BOARDS if per_date_board_coverage[trade_date][board] <= 0.0)

    industry_coverage = _non_missing_ratio(panel["industry_l1"])
    if "industry_relative" not in disabled_groups and industry_coverage < 1.0:
        blocking_codes.add("industry_coverage_incomplete")
        exclusions.add("industry_missing")

    moneyflow_coverage = _moneyflow_coverage(panel)
    if moneyflow_coverage is None or moneyflow_coverage < OPTIONAL_MONEYFLOW_MINIMUM_COVERAGE:
        disabled_groups.add("moneyflow")

    sample_estimates = _sample_estimates(panel, valid_rows)
    if sample_estimates["estimated_labeled_rows"] <= 0:
        blocking_codes.add("insufficient_training_samples")
        exclusions.add("sample_estimate:zero_labeled_rows")

    return QualityReport(
        blocking_codes=tuple(sorted(blocking_codes)),
        exclusion_reasons=tuple(sorted(exclusions)),
        disabled_feature_groups=tuple(sorted(disabled_groups)),
        duplicate_key_count=duplicate_key_count,
        per_date_universe_count=dict(sorted(per_date_universe_count.items())),
        required_date_coverage=required_date_coverage,
        expected_trade_dates=tuple(sorted(expected_date_set)),
        observed_trade_dates=observed_dates,
        missingness=missingness,
        join_coverage=join_coverage,
        listing_coverage=listing_coverage,
        board_coverage=board_coverage,
        per_date_board_coverage=per_date_board_coverage,
        industry_coverage=industry_coverage,
        moneyflow_coverage=moneyflow_coverage,
        sample_estimates=sample_estimates,
        raw_valid_row_count=raw_valid_row_count,
        row_count=len(panel),
    )


def _panel_frame(panel_dataset: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel_dataset, pd.DataFrame):
        raise TypeError("panel_dataset must be a pandas DataFrame")
    return panel_dataset


def _manifest_evidence(
    config: FullMarketMLConfig, manifest: Any
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], set[str]]:
    if manifest is None:
        return (), (), (), set()
    if isinstance(manifest, Mapping):
        blocking = tuple(str(code) for code in manifest.get("blocking_codes", ()))
        partitions = manifest.get("partitions", ())
        industry_enabled = bool(manifest.get("industry_relative_enabled", True))
        optional_failures = {str(group) for group in manifest.get("optional_failures", ())}
        config_sha256 = str(manifest.get("config_sha256", ""))
        open_dates = manifest.get("trade_cal_open_dates")
    else:
        blocking = tuple(str(code) for code in getattr(manifest, "blocking_codes", ()))
        partitions = getattr(manifest, "partitions", ())
        industry_enabled = bool(getattr(manifest, "industry_relative_enabled", True))
        optional_failures = {str(group) for group in getattr(manifest, "optional_failures", ())}
        config_sha256 = str(getattr(manifest, "config_sha256", ""))
        open_dates = getattr(manifest, "trade_cal_open_dates", None)
    gate_codes: set[str] = set()
    if config_sha256 != config.sha256:
        gate_codes.add("manifest_config_mismatch")
    if not isinstance(open_dates, (list, tuple, set)):
        gate_codes.add("trade_cal_open_sessions_missing")
        open_dates = ()
    dates = tuple(
        sorted(
            {
                date
                for value in open_dates
                if (date := _date_text(value)) and config.dates.signal_start <= date <= config.dates.signal_end
            }
        )
    )
    if not dates:
        gate_codes.add("trade_cal_open_sessions_missing")
    records_by_endpoint: dict[str, dict[str, str]] = {}
    seen_partition_keys: set[tuple[str, str]] = set()
    for partition in partitions:
        endpoint = partition.get("endpoint") if isinstance(partition, Mapping) else getattr(partition, "endpoint", None)
        key = partition.get("key") if isinstance(partition, Mapping) else getattr(partition, "key", None)
        status = partition.get("status", "collected") if isinstance(partition, Mapping) else getattr(partition, "status", "collected")
        key_date = _date_text(key)
        if endpoint and key_date:
            endpoint_name = str(endpoint)
            partition_key = (endpoint_name, key_date)
            if partition_key in seen_partition_keys and endpoint_name in {*CORE_DAILY_ENDPOINTS, "trade_cal"}:
                gate_codes.add("duplicate_manifest_evidence")
            seen_partition_keys.add(partition_key)
            records_by_endpoint.setdefault(endpoint_name, {})[key_date] = str(status)
    trade_cal_status = records_by_endpoint.get("trade_cal", {})
    if any(trade_cal_status.get(date) not in READY_PARTITION_STATUSES for date in dates):
        gate_codes.add("trade_cal_manifest_incomplete")
    for endpoint in CORE_DAILY_ENDPOINTS:
        endpoint_status = records_by_endpoint.get(endpoint, {})
        if dates and not endpoint_status:
            gate_codes.add(f"{endpoint}_manifest_missing")
        elif any(endpoint_status.get(date) == "failed" for date in dates):
            gate_codes.add(f"{endpoint}_manifest_failed")
        elif any(endpoint_status.get(date) not in READY_PARTITION_STATUSES for date in dates):
            gate_codes.add(f"{endpoint}_manifest_incomplete")
    disabled = set() if industry_enabled else {"industry_relative"}
    if "historical_industry" in optional_failures:
        disabled.add("industry_relative")
    if "moneyflow" in optional_failures:
        disabled.add("moneyflow")
    return tuple(sorted(set(blocking))), tuple(sorted(gate_codes)), dates, disabled


def _valid_ohlc(panel: pd.DataFrame) -> pd.Series:
    values = panel[["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"]].apply(pd.to_numeric, errors="coerce")
    reported_validity = panel["valid_ohlc"].eq(True)
    return (
        reported_validity
        & values.gt(0).all(axis=1)
        & values["adjusted_high"].ge(values["adjusted_low"])
        & values["adjusted_high"].ge(values[["adjusted_open", "adjusted_close"]].max(axis=1))
        & values["adjusted_low"].le(values[["adjusted_open", "adjusted_close"]].min(axis=1))
    )


def _sample_estimates(panel: pd.DataFrame, valid_rows: pd.Series) -> dict[str, int]:
    listed = pd.to_numeric(panel["listing_age_trade_days"], errors="coerce").ge(20)
    eligible = valid_rows & listed
    if "is_st" in panel:
        eligible &= ~panel["is_st"].eq(True)
    if "is_suspended" in panel:
        eligible &= ~panel["is_suspended"].eq(True)
    tradeable = panel["entry_tradeable"].eq(True) if "entry_tradeable" in panel else pd.Series(True, index=panel.index)
    labeled = eligible & tradeable
    return {
        "panel_rows": int(len(panel)),
        "eligible_signal_rows": int(eligible.sum()),
        "entry_tradeable_rows": int(tradeable.sum()),
        "estimated_labeled_rows": int(labeled.sum()),
    }


def _board_coverage(symbols: pd.Series) -> dict[str, float]:
    values = symbols.astype("string").fillna("")
    count = len(values)
    if not count:
        return {board: 0.0 for board in REQUIRED_BOARDS}
    return {
        "MAIN": float((~values.str.startswith(("300", "301", "688", "689"))).mean()),
        "CHINEXT": float(values.str.startswith(("300", "301")).mean()),
        "STAR": float(values.str.startswith(("688", "689")).mean()),
    }


def _moneyflow_coverage(panel: pd.DataFrame) -> float | None:
    columns = [column for column in OPTIONAL_MONEYFLOW_COLUMNS if column in panel]
    if not columns:
        return None
    return float(panel[columns].notna().all(axis=1).mean()) if len(panel) else 0.0


def _missing_ratio(values: pd.Series) -> float:
    return float(values.isna().mean()) if len(values) else 1.0


def _non_missing_ratio(values: pd.Series) -> float:
    return 1.0 - _missing_ratio(values)


def _date_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    digits = "".join(character for character in str(value) if character.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else ""
