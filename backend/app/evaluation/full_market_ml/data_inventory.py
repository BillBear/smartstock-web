"""Read-only inventory of immutable full-market TuShare endpoint assets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REQUIRED_R4A_FIELDS = {
    "daily": {"open", "high", "low", "close", "vol", "amount"},
    "daily_basic": {"turnover_rate", "volume_ratio", "total_mv", "circ_mv", "pe_ttm", "pb"},
    "moneyflow": {
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
    },
    "stk_limit": {"up_limit", "down_limit"},
    "index_daily": {"close", "pct_chg", "amount"},
    "index_member_all": {"index_code", "con_code", "in_date", "out_date"},
}

_FIELD_ALIASES = {
    "index_member_all": {
        "index_code": ("index_code", "l1_code"),
        "con_code": ("con_code", "ts_code"),
        "in_date": ("in_date",),
        "out_date": ("out_date",),
    }
}
_CORE_ENDPOINTS = ("daily", "daily_basic", "stk_limit", "index_daily", "index_member_all")
_EQUITY_DATE_ENDPOINTS = ("daily_basic", "moneyflow", "stk_limit")
_CORE_MINIMUM_COVERAGE = 0.95
_MONEYFLOW_MINIMUM_COVERAGE = 0.90


def audit_source_fields(raw_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Report actual schemas and per-date coverage without fetching or mutation."""
    root = Path(raw_root).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"raw asset root is missing: {root}")
    if not manifest_file.is_file():
        raise FileNotFoundError(f"collection manifest is missing: {manifest_file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("collection manifest must be a JSON object")
    expected_dates = tuple(sorted({_date_key(value) for value in manifest.get("trade_cal_open_dates", []) if _date_key(value)}))
    partitions = manifest.get("partitions", [])
    if not isinstance(partitions, list):
        raise ValueError("collection manifest partitions must be a list")
    partition_index = _partition_index(partitions)
    endpoint_root = root / "raw" if (root / "raw").is_dir() else root
    daily_files = _daily_files(endpoint_root)
    daily_counts = {
        date: _partition_row_count(path, partition_index.get("daily", {}))
        for date, path in daily_files.items()
    }
    daily_symbol_cache: dict[str, frozenset[str]] = {}

    report: dict[str, Any] = {
        "schema_version": 1,
        "manifest_sha256": _sha256_file(manifest_file),
        "expected_trade_date_count": len(expected_dates),
        "expected_trade_dates": list(expected_dates),
    }
    for endpoint, required_fields in REQUIRED_R4A_FIELDS.items():
        report[endpoint] = _audit_endpoint(
            endpoint_root,
            endpoint,
            required_fields,
            expected_dates,
            partition_index.get(endpoint, {}),
            daily_counts,
            daily_files,
            daily_symbol_cache,
        )

    blocking = [
        f"{endpoint}_not_ready"
        for endpoint in _CORE_ENDPOINTS
        if report[endpoint]["status"] != "ready"
    ]
    experimental = []
    if report["moneyflow"]["status"] != "ready":
        experimental.append("moneyflow")
    report["blocking_codes"] = blocking
    report["experimental_only_blocks"] = experimental
    report["r4a_ready"] = not blocking
    return report


def resolve_raw_asset_root(asset_root: Path) -> tuple[Path, Path]:
    """Resolve the verified raw source from the workspace asset manifest."""
    root = Path(asset_root).expanduser().resolve()
    manifest_path = root / "asset_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"asset manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("verification_status") != "verified":
        raise ValueError("asset manifest is not verified")
    raw_sources = [item for item in manifest.get("sources", []) if item.get("role") == "raw"]
    if len(raw_sources) != 1:
        raise ValueError("asset manifest must contain exactly one verified raw source")
    source = raw_sources[0]
    if source.get("status") not in {"copied_and_verified", "verified_existing"}:
        raise ValueError("raw source is not verified")
    raw_root = Path(str(source["destination"])).expanduser().resolve()
    collection_manifest = raw_root / "manifests" / "full-build.json"
    return raw_root, collection_manifest


def _audit_endpoint(
    endpoint_root: Path,
    endpoint: str,
    required_fields: set[str],
    expected_dates: tuple[str, ...],
    partition_rows: dict[str, dict[str, Any]],
    daily_counts: dict[str, int],
    daily_files: dict[str, Path],
    daily_symbol_cache: dict[str, frozenset[str]],
) -> dict[str, Any]:
    directory = endpoint_root / f"endpoint={endpoint}"
    files = sorted(directory.rglob("*.parquet")) if directory.is_dir() else []
    if not files:
        return _empty_endpoint_report(required_fields)

    schema_sets = [set(pq.read_schema(path).names) for path in files]
    available = set.intersection(*schema_sets) if schema_sets else set()
    aliases = _FIELD_ALIASES.get(endpoint, {})
    resolved = {}
    missing = []
    for field in sorted(required_fields):
        candidates = aliases.get(field, (field,))
        actual = next((candidate for candidate in candidates if candidate in available), None)
        if actual is None:
            missing.append(field)
        else:
            resolved[field] = actual

    observed_dates = tuple(
        sorted(
            {
                date
                for date in (_partition_date(path) for path in files)
                if date is not None
            }
        )
    )
    expected = set(expected_dates)
    if endpoint == "index_member_all":
        partition_coverage = 1.0
    else:
        partition_coverage = (
            len(expected & set(observed_dates)) / len(expected)
            if expected
            else (1.0 if files else 0.0)
        )
    minimum_coverage, median_coverage = _endpoint_row_coverage(
        endpoint,
        files,
        expected_dates,
        daily_counts,
        daily_files,
        daily_symbol_cache,
        resolved,
    )
    minimum_required = (
        _MONEYFLOW_MINIMUM_COVERAGE if endpoint == "moneyflow" else _CORE_MINIMUM_COVERAGE
    )
    if missing:
        status = "partial_fields"
    elif partition_coverage < minimum_required or minimum_coverage < minimum_required:
        status = "insufficient_coverage"
    else:
        status = "ready"
    return {
        "status": status,
        "required_fields": sorted(required_fields),
        "available_fields": sorted(available),
        "missing_fields": missing,
        "resolved_fields": resolved,
        "file_count": len(files),
        "row_count": int(sum(_partition_row_count(path, partition_rows) for path in files)),
        "schema_variant_count": len({tuple(sorted(schema)) for schema in schema_sets}),
        "observed_trade_date_count": len(observed_dates),
        "partition_date_coverage": float(partition_coverage),
        "minimum_date_coverage": float(minimum_coverage),
        "median_date_coverage": float(median_coverage),
        "minimum_required_coverage": minimum_required,
    }


def _endpoint_row_coverage(
    endpoint: str,
    files: list[Path],
    expected_dates: tuple[str, ...],
    daily_counts: dict[str, int],
    daily_files: dict[str, Path],
    daily_symbol_cache: dict[str, frozenset[str]],
    resolved: dict[str, str],
) -> tuple[float, float]:
    if endpoint == "index_member_all":
        return _industry_membership_coverage(
            files, expected_dates, daily_counts, daily_files, daily_symbol_cache, resolved
        )
    if endpoint not in _EQUITY_DATE_ENDPOINTS:
        observed = {_partition_date(path) for path in files}
        values = [1.0 if date in observed else 0.0 for date in expected_dates]
        return _coverage_summary(values, fallback=1.0)

    file_by_date = {_partition_date(path): path for path in files if _partition_date(path)}
    values = []
    for date in expected_dates:
        path = file_by_date.get(date)
        daily_path = daily_files.get(date)
        if path is None or daily_path is None:
            values.append(0.0)
            continue
        daily_symbols = _daily_symbols(date, daily_path, daily_symbol_cache)
        endpoint_symbols = _read_symbols(path)
        values.append(
            len(daily_symbols & endpoint_symbols) / len(daily_symbols)
            if daily_symbols
            else 0.0
        )
    return _coverage_summary(values, fallback=0.0)


def _industry_membership_coverage(
    files: list[Path],
    expected_dates: tuple[str, ...],
    daily_counts: dict[str, int],
    daily_files: dict[str, Path],
    daily_symbol_cache: dict[str, frozenset[str]],
    resolved: dict[str, str],
) -> tuple[float, float]:
    required = {"con_code", "in_date", "out_date"}
    if not required.issubset(resolved) or not daily_counts:
        return (1.0, 1.0) if files else (0.0, 0.0)
    members = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[resolved["con_code"], resolved["in_date"], resolved["out_date"]],
            )
            for path in files
        ],
        ignore_index=True,
    )
    members["_symbol"] = members[resolved["con_code"]].astype("string")
    members["_in"] = members[resolved["in_date"]].map(_date_key)
    members["_out"] = members[resolved["out_date"]].map(_date_key)
    values = []
    for date in expected_dates:
        daily_path = daily_files.get(date)
        if daily_counts.get(date, 0) <= 0 or daily_path is None:
            values.append(0.0)
            continue
        active = members["_in"].le(date) & (members["_out"].eq("") | members["_out"].ge(date))
        active_symbols = set(members.loc[active, "_symbol"].dropna().astype(str))
        daily_symbols = _daily_symbols(date, daily_path, daily_symbol_cache)
        values.append(
            len(active_symbols & daily_symbols) / len(daily_symbols)
            if daily_symbols
            else 0.0
        )
    return _coverage_summary(values, fallback=0.0)


def _daily_files(endpoint_root: Path) -> dict[str, Path]:
    directory = endpoint_root / "endpoint=daily"
    if not directory.is_dir():
        return {}
    return {
        date: path
        for path in directory.rglob("*.parquet")
        if (date := _partition_date(path)) is not None
    }


def _daily_symbols(
    date: str, path: Path, cache: dict[str, frozenset[str]]
) -> frozenset[str]:
    if date not in cache:
        cache[date] = frozenset(_read_symbols(path))
    return cache[date]


def _read_symbols(path: Path) -> set[str]:
    names = set(pq.read_schema(path).names)
    column = "ts_code" if "ts_code" in names else ("symbol" if "symbol" in names else "")
    if not column:
        return set()
    return set(pd.read_parquet(path, columns=[column])[column].dropna().astype(str))


def _partition_index(partitions: list[Any]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for item in partitions:
        if not isinstance(item, dict):
            continue
        endpoint = str(item.get("endpoint", ""))
        key = _date_key(item.get("key"))
        path = str(item.get("path", ""))
        if endpoint and (key or path):
            result.setdefault(endpoint, {})[key or path] = item
    return result


def _partition_row_count(path: Path, partition_rows: dict[str, dict[str, Any]]) -> int:
    date = _partition_date(path)
    item = partition_rows.get(date or "", {})
    value = item.get("row_count")
    if value is not None:
        return int(value)
    return int(pq.ParquetFile(path).metadata.num_rows)


def _partition_date(path: Path) -> str | None:
    for part in path.parts:
        if part.startswith("trade_date="):
            value = _date_key(part.split("=", 1)[1])
            return value or None
    return None


def _date_key(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else ""


def _coverage_summary(values: list[float], *, fallback: float) -> tuple[float, float]:
    if not values:
        return fallback, fallback
    array = np.asarray(values, dtype=float)
    return float(array.min()), float(np.median(array))


def _empty_endpoint_report(required_fields: set[str]) -> dict[str, Any]:
    return {
        "status": "missing_endpoint",
        "required_fields": sorted(required_fields),
        "available_fields": [],
        "missing_fields": sorted(required_fields),
        "resolved_fields": {},
        "file_count": 0,
        "row_count": 0,
        "schema_variant_count": 0,
        "observed_trade_date_count": 0,
        "partition_date_coverage": 0.0,
        "minimum_date_coverage": 0.0,
        "median_date_coverage": 0.0,
        "minimum_required_coverage": 0.0,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
