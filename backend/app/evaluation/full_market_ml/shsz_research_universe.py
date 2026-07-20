"""Read-only certification for the SH/SZ-only full-market research universe."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Mapping

import pandas as pd
import pyarrow.parquet as pq

from .tushare_training_field_lineage_audit import DETAILED_MONEYFLOW_AMOUNT_FIELDS


ALLOWED_EXCHANGES = ("SH", "SZ")
MINIMUM_COVERAGE = 0.95


class SHSZResearchUniverseError(ValueError):
    """Raised when immutable raw evidence cannot define the research universe."""


def certify_shsz_research_universe(*, source_run_root: str | Path, code_commit: str) -> dict[str, object]:
    """Certify a new SH/SZ research contract without changing the source run.

    Historical active-universe coverage is calculated before any feature or
    symbol normalization stage.  The result is evidence for a later rebuild,
    not an authorization to train or change a production universe.
    """
    root = Path(source_run_root).expanduser().resolve()
    manifest_path = root / "manifests" / "full-build.json"
    manifest = _read_manifest(manifest_path)
    records = _records_by_endpoint(manifest)
    stock_basic = _read_stock_basic(root, records.get("stock_basic", ()))
    daily_records = _records_by_key(records.get("daily", ()), "daily")
    moneyflow_records = _records_by_key(records.get("moneyflow", ()), "moneyflow")
    if not daily_records:
        raise SHSZResearchUniverseError("full-build manifest has no daily partitions")
    if stock_basic.empty:
        raise SHSZResearchUniverseError("full-build manifest has no usable stock_basic rows")

    expected_by_date = _historical_expected_symbols(stock_basic, tuple(sorted(daily_records)))
    blocking_codes: set[str] = set()
    excluded: dict[str, set[str]] = defaultdict(set)
    unresolved_daily_master_symbols: set[str] = set()
    daily_coverage: list[dict[str, object]] = []
    all_shsz_symbols: set[str] = set()

    for trade_date, daily_record in sorted(daily_records.items()):
        daily_codes = _read_codes(root, daily_record, "daily")
        for code in daily_codes:
            suffix = _exchange(code)
            if suffix not in ALLOWED_EXCHANGES:
                excluded[suffix].add(code)
        raw_shsz_observed = {code for code in daily_codes if _exchange(code) in ALLOWED_EXCHANGES}
        if len(raw_shsz_observed) != len([code for code in daily_codes if _exchange(code) in ALLOWED_EXCHANGES]):
            blocking_codes.add("duplicate_shsz_daily_symbol")
        expected = expected_by_date[trade_date]
        unresolved = raw_shsz_observed - expected
        # A daily row absent from the static L/D/P master has no defensible
        # listing-age or historical-status contract. It is explicitly excluded
        # from this research universe, not silently included or used as a
        # reason to lower expected-universe coverage.
        observed = raw_shsz_observed & expected
        missing = expected - observed
        unresolved_daily_master_symbols.update(unresolved)
        coverage = len(observed) / len(expected) if expected else 0.0
        if coverage < MINIMUM_COVERAGE:
            blocking_codes.add("daily_historical_coverage_below_0_95")

        moneyflow = _read_moneyflow(root, moneyflow_records.get(trade_date))
        covered = 0
        null_detailed = 0
        missing_moneyflow = 0
        for code in observed:
            values = moneyflow.get(code)
            if values is None:
                missing_moneyflow += 1
            elif any(pd.isna(values[field]) for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS):
                null_detailed += 1
            else:
                covered += 1
        detailed_coverage = covered / len(observed) if observed else 0.0
        if detailed_coverage < MINIMUM_COVERAGE:
            blocking_codes.add("detailed_moneyflow_coverage_below_0_95")
        all_shsz_symbols.update(observed)
        daily_coverage.append(
            {
                "trade_date": trade_date,
                "historical_expected_count": len(expected),
                "raw_shsz_daily_count": len(raw_shsz_observed),
                "daily_observed_count": len(observed),
                "daily_historical_coverage": coverage,
                "unresolved_daily_master_count": len(unresolved),
                "missing_daily_symbol_count": len(missing),
                "detailed_moneyflow_covered_count": covered,
                "missing_moneyflow_symbol_count": missing_moneyflow,
                "null_detailed_moneyflow_count": null_detailed,
                "detailed_moneyflow_coverage": detailed_coverage,
            }
        )

    status = "complete_research_universe_certified" if not blocking_codes else "blocked_research_universe_contract"
    return {
        "schema_version": 1,
        "status": status,
        "research_ready": not blocking_codes,
        "production_integration_allowed": False,
        "universe_id": "shsz_a_share_v1",
        "allowed_exchanges": list(ALLOWED_EXCHANGES),
        "minimum_daily_historical_coverage": MINIMUM_COVERAGE,
        "minimum_detailed_moneyflow_coverage": MINIMUM_COVERAGE,
        "code_commit": str(code_commit),
        "source": {
            "run_root": str(root),
            "full_build_manifest_sha256": _sha256(manifest_path),
            "daily_partition_count": len(daily_records),
            "stock_basic_partition_count": len(records.get("stock_basic", ())),
        },
        "trade_date_count": len(daily_coverage),
        "symbol_count": len(all_shsz_symbols),
        "excluded_exchange_counts": {exchange: len(symbols) for exchange, symbols in sorted(excluded.items())},
        "unresolved_daily_master_symbols": sorted(unresolved_daily_master_symbols),
        "blocking_codes": sorted(blocking_codes),
        "daily_coverage": daily_coverage,
        "interpretation": (
            "This SH/SZ-only contract is a research-universe certificate. It does not alter the "
            "production universe, authorize model training, or relax any feature gate."
        ),
    }


def _read_manifest(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        raise SHSZResearchUniverseError(f"full-build manifest is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or not isinstance(value.get("partitions"), list):
        raise SHSZResearchUniverseError("full-build manifest has invalid partitions")
    return value


def _records_by_endpoint(manifest: Mapping[str, object]) -> dict[str, tuple[Mapping[str, object], ...]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for value in manifest["partitions"]:
        if not isinstance(value, Mapping):
            raise SHSZResearchUniverseError("full-build manifest has invalid partition record")
        endpoint = str(value.get("endpoint", ""))
        if not endpoint:
            raise SHSZResearchUniverseError("full-build manifest partition has no endpoint")
        grouped[endpoint].append(value)
    return {endpoint: tuple(values) for endpoint, values in grouped.items()}


def _records_by_key(records: tuple[Mapping[str, object], ...], endpoint: str) -> dict[str, Mapping[str, object]]:
    keyed: dict[str, Mapping[str, object]] = {}
    for record in records:
        key = str(record.get("key", ""))
        if not key:
            raise SHSZResearchUniverseError(f"{endpoint} partition has no key")
        if key in keyed:
            raise SHSZResearchUniverseError(f"duplicate {endpoint} partition key: {key}")
        keyed[key] = record
    return keyed


def _read_stock_basic(root: Path, records: tuple[Mapping[str, object], ...]) -> pd.DataFrame:
    frames = []
    for record in records:
        if record.get("status") == "failed":
            raise SHSZResearchUniverseError("stock_basic partition failed")
        frame = _read_columns(root, record, ("ts_code", "list_date", "delist_date", "list_status"), "stock_basic")
        if not frame.empty:
            frames.append(frame)
    values = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts_code", "list_date", "delist_date", "list_status"])
    if values.empty:
        return values
    values["ts_code"] = values["ts_code"].map(_canonical_code)
    values = values.loc[values["ts_code"].map(_exchange).isin(ALLOWED_EXCHANGES)].copy()
    values["list_date"] = values["list_date"].map(_date_text)
    values["delist_date"] = values["delist_date"].map(_date_text)
    if values["ts_code"].duplicated().any():
        raise SHSZResearchUniverseError("duplicate SH/SZ stock_basic ts_code")
    return values


def _historical_expected_symbols(stock_basic: pd.DataFrame, trade_dates: tuple[str, ...]) -> dict[str, set[str]]:
    expected: dict[str, set[str]] = {}
    for trade_date in trade_dates:
        active = stock_basic.loc[
            stock_basic["list_date"].le(_date_text(trade_date))
            & (stock_basic["delist_date"].eq("") | stock_basic["delist_date"].ge(_date_text(trade_date))),
            "ts_code",
        ]
        expected[trade_date] = set(active.tolist())
        if not expected[trade_date]:
            raise SHSZResearchUniverseError(f"historical SH/SZ universe is empty: {trade_date}")
    return expected


def _read_codes(root: Path, record: Mapping[str, object], endpoint: str) -> list[str]:
    if record.get("status") == "failed":
        raise SHSZResearchUniverseError(f"{endpoint} partition failed: {record.get('key')}")
    frame = _read_columns(root, record, ("ts_code",), endpoint)
    return [_canonical_code(value) for value in frame["ts_code"].tolist()]


def _read_moneyflow(root: Path, record: Mapping[str, object] | None) -> dict[str, Mapping[str, object]]:
    if record is None or record.get("status") == "failed":
        return {}
    frame = _read_columns(root, record, ("ts_code", *DETAILED_MONEYFLOW_AMOUNT_FIELDS), "moneyflow")
    frame["ts_code"] = frame["ts_code"].map(_canonical_code)
    if frame["ts_code"].duplicated().any():
        raise SHSZResearchUniverseError(f"duplicate moneyflow ts_code: {record.get('key')}")
    return {str(row["ts_code"]): {field: row[field] for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS} for _, row in frame.iterrows()}


def _read_columns(root: Path, record: Mapping[str, object], columns: tuple[str, ...], endpoint: str) -> pd.DataFrame:
    path = _partition_path(root, record)
    available = set(pq.ParquetFile(path).schema_arrow.names)
    missing = sorted(set(columns) - available)
    if missing:
        if endpoint == "stock_basic" and set(missing).issubset({"delist_date", "list_status"}):
            frame = pq.read_table(path, columns=[column for column in columns if column in available]).to_pandas()
            for column in missing:
                frame[column] = ""
            return frame.loc[:, columns]
        raise SHSZResearchUniverseError(f"{endpoint} partition is missing columns: {', '.join(missing)}")
    return pq.read_table(path, columns=list(columns)).to_pandas()


def _partition_path(root: Path, record: Mapping[str, object]) -> Path:
    raw = str(record.get("path", ""))
    path = (root / raw).resolve()
    if root not in path.parents or not path.is_file():
        raise SHSZResearchUniverseError(f"partition path is unavailable or escapes source root: {raw}")
    return path


def _canonical_code(value: object) -> str:
    code = str(value).strip().upper()
    if not code or "." not in code:
        raise SHSZResearchUniverseError(f"invalid ts_code: {value}")
    return code


def _exchange(code: str) -> str:
    return code.rsplit(".", 1)[1]


def _date_text(value: object) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as error:
        raise SHSZResearchUniverseError(f"invalid date: {value}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
