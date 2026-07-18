"""Verified raw-source provenance for immutable ML sample contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow.parquet as pq


_SHA256_HEX_LENGTH = 64
_SOURCE_SPECS = (
    ("listing", "stock_basic", "L", (("ts_code", "list_date"),)),
    ("delisting", "stock_basic", "D", (("ts_code", "list_date", "delist_date"),)),
    ("pending_listing", "stock_basic", "P", (("ts_code", "list_date"),)),
    ("st", "namechange", None, (("ts_code", "name", "start_date", "end_date"),)),
    ("trading_calendar", "trade_cal", None, (("cal_date", "is_open"),)),
    ("suspension", "suspend_d", None, (("ts_code", "trade_date"), ("ts_code", "suspend_date", "resume_date"))),
)
_INDUSTRY_SOURCE_SPECS = (
    ("industry_classification", "index_classify", None, (("index_code", "industry_name"),)),
    ("industry_membership", "index_member_all", None, (("l1_code", "ts_code", "in_date", "out_date"),)),
)


def build_security_state_provenance(
    raw_manifest: Mapping[str, Any], raw_root: str | Path
) -> dict[str, Any]:
    """Hash and schema-check all source partitions used for PIT state fields."""
    root = Path(raw_root).expanduser().resolve()
    partitions = _partitions(raw_manifest)
    industry_enabled = bool(raw_manifest.get("industry_relative_enabled", False))
    specs = _SOURCE_SPECS + (_INDUSTRY_SOURCE_SPECS if industry_enabled else ())
    sources: list[dict[str, Any]] = []
    blocking: set[str] = set()
    for role, endpoint, key, alternatives in specs:
        selected = _select_partitions(partitions, endpoint, key)
        if not selected:
            expected = endpoint if key is None else f"{endpoint}:{key}"
            raise ValueError(f"security-state provenance is missing required source: {expected}")
        for record in selected:
            path = _verified_partition_path(root, record)
            columns = tuple(pq.ParquetFile(path).schema.names)
            required = _first_matching_columns(columns, alternatives)
            if required is None:
                missing = sorted(set(alternatives[0]) - set(columns))
                for column in missing:
                    blocking.add(f"security_state:missing_columns:{role}:{column}")
            sources.append(
                {
                    "role": role,
                    "endpoint": endpoint,
                    "key": str(record.get("key", "")),
                    "path": str(record["path"]),
                    "sha256": str(record["sha256"]).lower(),
                    "row_count": int(record.get("row_count", 0) or 0),
                    "columns": list(columns),
                    "required_columns": list(required if required is not None else alternatives[0]),
                }
            )
    covers = {"listing", "delisting", "st", "suspension"}
    if industry_enabled:
        covers.add("industry")
    payload: dict[str, Any] = {
        "security_state_provenance_version": "pit_sources_v1",
        "covers": sorted(covers),
        "industry_relative_enabled": industry_enabled,
        "sources": sorted(sources, key=lambda item: (item["role"], item["path"])),
        "blocking_codes": sorted(blocking),
        "validation_status": "verified" if not blocking else "blocked",
    }
    return _with_sha256(payload)


def _partitions(raw_manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = raw_manifest.get("partitions")
    if not isinstance(value, list):
        raise ValueError("raw collection manifest has no partitions array")
    adopted: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if item.get("status") != "adopted":
            continue
        if not str(item.get("endpoint", "")).strip() or not str(item.get("path", "")).strip():
            continue
        _require_sha256("raw partition", item.get("sha256"))
        adopted.append(item)
    return adopted


def _select_partitions(
    partitions: Iterable[Mapping[str, Any]], endpoint: str, key: str | None
) -> list[Mapping[str, Any]]:
    selected = [item for item in partitions if item.get("endpoint") == endpoint]
    if key is not None:
        selected = [item for item in selected if str(item.get("key", "")) == key]
    return sorted(selected, key=lambda item: (str(item.get("key", "")), str(item.get("path", ""))))


def _verified_partition_path(root: Path, record: Mapping[str, Any]) -> Path:
    relative = Path(str(record["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid raw partition path: {relative}")
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError(f"raw partition is unavailable: {relative}")
    expected = str(record["sha256"]).lower()
    observed = _sha256_file(path)
    if observed != expected:
        raise ValueError(f"raw partition hash mismatch: {relative}")
    return path


def _first_matching_columns(
    columns: tuple[str, ...], alternatives: tuple[tuple[str, ...], ...]
) -> tuple[str, ...] | None:
    available = set(columns)
    return next((candidate for candidate in alternatives if set(candidate).issubset(available)), None)


def _with_sha256(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result["sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def _require_sha256(label: str, value: object) -> None:
    text = str(value).strip().lower()
    if len(text) != _SHA256_HEX_LENGTH or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} hash must be a SHA256")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
