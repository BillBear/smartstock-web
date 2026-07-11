"""Resumable raw TuShare collection for the offline full-market ML pipeline."""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq

from .config import FullMarketMLConfig
from .manifests import CollectionManifest, PartitionRecord, load_manifest, manifest_path, save_manifest


CORE_DAILY_ENDPOINTS = ("daily", "daily_basic", "adj_factor", "stk_limit", "suspend_d")
CARDINALITY_GATED_ENDPOINTS = ("daily", "daily_basic", "adj_factor", "stk_limit")
CORE_STATIC_ENDPOINTS = ("namechange",)
INDEX_CODES = ("000001.SH", "000300.SH", "000905.SH", "399006.SZ")
RETRY_DELAYS_SECONDS = (1, 2, 4, 8)


def collect_full_market_raw(
    config: FullMarketMLConfig,
    client: Any,
    runtime_root: str | Path,
    stage: str,
    resume: bool = True,
) -> CollectionManifest:
    """Collect immutable raw partitions and return their persisted audit manifest."""
    root = Path(runtime_root)
    root.mkdir(parents=True, exist_ok=True)
    if not resume and ((root / "raw").exists() or manifest_path(root, stage).exists()):
        raise ValueError("existing stage/raw content requires a new stage identifier")

    manifest = (
        load_manifest(root, stage, config.sha256, config.collection.request_pacing_seconds)
        if resume
        else CollectionManifest(stage, config.sha256, config.collection.request_pacing_seconds)
    )
    # These describe the current collection attempt; failures remain in endpoint_errors/history.
    manifest.blocking_codes = []
    manifest.optional_failures = []
    manifest.industry_relative_enabled = True
    save_manifest(root, manifest)

    calendar_rows = _collect_trade_calendar(root, manifest, client, config, resume)
    open_dates = [str(row["cal_date"]) for row in calendar_rows if str(row.get("is_open")) == "1" and row.get("cal_date")]
    for trade_date in sorted(set(open_dates)):
        for endpoint in CORE_DAILY_ENDPOINTS:
            rows = _collect_partition(
                root,
                manifest,
                endpoint,
                trade_date,
                _raw_path(endpoint, trade_date),
                lambda endpoint=endpoint, trade_date=trade_date: _records(
                    _request(lambda: getattr(client, endpoint)(trade_date=trade_date), config.collection.request_pacing_seconds)
                ),
                core=True,
                resume=resume,
            )
            if endpoint in CARDINALITY_GATED_ENDPOINTS:
                _enforce_minimum_rows(root, manifest, endpoint, trade_date, config, rows)
        _collect_partition(
            root,
            manifest,
            "moneyflow",
            trade_date,
            _raw_path("moneyflow", trade_date),
            lambda trade_date=trade_date: _records(
                _request(lambda: client.moneyflow(trade_date=trade_date), config.collection.request_pacing_seconds)
            ),
            core=False,
            optional_group="moneyflow",
            resume=resume,
        )
        _collect_partition(
            root,
            manifest,
            "index_dailybasic",
            trade_date,
            _raw_path("index_dailybasic", trade_date),
            lambda trade_date=trade_date: _records(
                _request(lambda: client.index_dailybasic(trade_date=trade_date), config.collection.request_pacing_seconds)
            ),
            core=False,
            optional_group="index_dailybasic",
            resume=resume,
        )
        _collect_partition(
            root,
            manifest,
            "index_daily",
            trade_date,
            _raw_path("index_daily", trade_date),
            lambda trade_date=trade_date: _index_daily_rows(client, trade_date, config.collection.request_pacing_seconds),
            core=True,
            resume=resume,
        )

    for list_status in ("L", "D", "P"):
        _collect_partition(
            root,
            manifest,
            "stock_basic",
            list_status,
            _stock_basic_path(list_status),
            lambda list_status=list_status: _records(
                _request(lambda: client.stock_basic(list_status=list_status), config.collection.request_pacing_seconds)
            ),
            core=True,
            resume=resume,
        )
    for endpoint in CORE_STATIC_ENDPOINTS:
        _collect_partition(
            root,
            manifest,
            endpoint,
            "static",
            _static_path(endpoint),
            lambda endpoint=endpoint: _records(
                _request(
                    lambda: getattr(client, endpoint)(
                        start_date=_compact(config.dates.signal_start), end_date=_compact(config.dates.signal_end)
                    ),
                    config.collection.request_pacing_seconds,
                )
            ),
            core=True,
            resume=resume,
        )
    _collect_historical_industry(root, manifest, client, resume, config.collection.request_pacing_seconds)
    save_manifest(root, manifest)
    return manifest


def _collect_trade_calendar(
    root: Path, manifest: CollectionManifest, client: Any, config: FullMarketMLConfig, resume: bool
) -> list[dict[str, Any]]:
    expected_dates = _calendar_dates(config.dates.signal_start, config.dates.signal_end)
    if resume:
        reused = [_existing_partition(root, manifest, "trade_cal", trade_date) for trade_date in expected_dates]
        if all(reused):
            for partition in reused:
                partition.status = "reused"
                manifest.replace_partition(partition)
                save_manifest(root, manifest)
            return [row for partition in reused for row in _read_records(root / partition.path)]
    try:
        rows = _records(
            _request(
                lambda: client.trade_cal(
                    exchange="", start_date=_compact(config.dates.signal_start), end_date=_compact(config.dates.signal_end)
                ),
                config.collection.request_pacing_seconds,
            )
        )
    except Exception:
        manifest.mark_endpoint_error("trade_cal", core=True)
        manifest.add_blocking_code("trade_cal_incomplete")
        save_manifest(root, manifest)
        return []
    by_date = {str(row["cal_date"]): row for row in rows if row.get("cal_date")}
    if set(by_date) != set(expected_dates):
        manifest.add_blocking_code("trade_cal_incomplete")
        save_manifest(root, manifest)
    for trade_date, row in by_date.items():
        _collect_partition(root, manifest, "trade_cal", trade_date, _raw_path("trade_cal", trade_date), lambda row=row: [row], core=True, resume=resume)
    if not [row for row in rows if str(row.get("is_open")) == "1"]:
        manifest.add_blocking_code("trade_cal_no_open_dates")
        save_manifest(root, manifest)
    return rows


def _collect_historical_industry(
    root: Path, manifest: CollectionManifest, client: Any, resume: bool, pacing_seconds: float
) -> None:
    classifications = _collect_partition(
        root,
        manifest,
        "index_classify",
        "SW2021-L1",
        _static_path("index_classify"),
        lambda: _records(_request(lambda: client.index_classify(level="L1", src="SW2021"), pacing_seconds)),
        core=False,
        optional_group="historical_industry",
        resume=resume,
    )
    codes = [str(row["index_code"]) for row in classifications if row.get("index_code")]
    _collect_partition(
        root,
        manifest,
        "index_member_all",
        "SW2021-L1",
        _static_path("index_member_all"),
        lambda: [
            row
            for code in codes
            for row in _records(_request(lambda code=code: client.index_member_all(l1_code=code), pacing_seconds))
        ],
        core=False,
        optional_group="historical_industry",
        resume=resume,
    )
    manifest.industry_relative_enabled = "historical_industry" not in manifest.optional_failures
    save_manifest(root, manifest)


def _collect_partition(
    root: Path,
    manifest: CollectionManifest,
    endpoint: str,
    key: str,
    relative_path: Path,
    fetch: Callable[[], list[dict[str, Any]]],
    *,
    core: bool,
    resume: bool,
    optional_group: str | None = None,
) -> list[dict[str, Any]]:
    existing = _existing_partition(root, manifest, endpoint, key) if resume else None
    was_manifest_record = existing is not None
    if existing is None and resume:
        existing = _adopt_orphan_partition(root, endpoint, key, relative_path)
    if existing is not None:
        existing.status = "reused" if was_manifest_record else "adopted"
        manifest.replace_partition(existing)
        save_manifest(root, manifest)
        return _read_records(root / existing.path)
    try:
        rows = fetch()
        record = _write_partition(root, root / relative_path, endpoint, key, rows)
        manifest.replace_partition(record)
        save_manifest(root, manifest)
        return rows
    except Exception:
        manifest.mark_endpoint_error(endpoint, core=core, optional_group=optional_group)
        manifest.replace_partition(PartitionRecord(endpoint, key, str(relative_path), 0, "", "", "failed"))
        save_manifest(root, manifest)
        return []


def _enforce_minimum_rows(
    root: Path, manifest: CollectionManifest, endpoint: str, key: str, config: FullMarketMLConfig, rows: list[dict[str, Any]]
) -> None:
    if len(rows) < max(4500, config.sample.minimum_daily_symbols):
        manifest.add_blocking_code(f"{endpoint}_insufficient_rows")
        save_manifest(root, manifest)


def _existing_partition(root: Path, manifest: CollectionManifest, endpoint: str, key: str) -> PartitionRecord | None:
    try:
        record = manifest.partition(endpoint, key)
    except KeyError:
        return None
    path = root / record.path
    if record.status == "failed" or not path.is_file() or _sha256(path) != record.sha256:
        return None
    try:
        table = pq.ParquetFile(path).read()
    except Exception:
        return None
    if table.num_rows != record.row_count or str(table.schema) != record.schema:
        return None
    return record


def _adopt_orphan_partition(root: Path, endpoint: str, key: str, relative_path: Path) -> PartitionRecord | None:
    path = root / relative_path
    if not path.is_file():
        return None
    try:
        table = pq.ParquetFile(path).read()
    except Exception:
        return None
    return PartitionRecord(endpoint, key, str(relative_path), table.num_rows, str(table.schema), _sha256(path), "adopted")


def _request(fetch: Callable[[], Any], pacing_seconds: float) -> Any:
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        time.sleep(pacing_seconds)
        try:
            return fetch()
        except Exception:
            if attempt == len(RETRY_DELAYS_SECONDS):
                raise
            time.sleep(RETRY_DELAYS_SECONDS[attempt])
    raise AssertionError("unreachable")


def _write_partition(root: Path, path: Path, endpoint: str, key: str, rows: list[dict[str, Any]]) -> PartitionRecord:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".data-", suffix=".tmp", delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        pq.write_table(table, temporary_path)
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return PartitionRecord(endpoint, key, str(path.relative_to(root)), table.num_rows, str(table.schema), _sha256(path))


def _read_records(path: Path) -> list[dict[str, Any]]:
    return pq.ParquetFile(path).read().to_pylist()


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        return list(value.to_dict("records"))
    return [dict(row) for row in value]


def _index_daily_rows(client: Any, trade_date: str, pacing_seconds: float) -> list[dict[str, Any]]:
    rows = [
        row
        for code in INDEX_CODES
        for row in _records(_request(lambda code=code: client.index_daily(ts_code=code, trade_date=trade_date), pacing_seconds))
    ]
    if {str(row.get("ts_code")) for row in rows} != set(INDEX_CODES):
        raise ValueError("index_daily missing an allowed index code")
    return rows


def _raw_path(endpoint: str, trade_date: str) -> Path:
    return Path("raw") / f"endpoint={endpoint}" / f"trade_date={trade_date}" / "data.parquet"


def _stock_basic_path(list_status: str) -> Path:
    return Path("raw") / "endpoint=stock_basic" / f"list_status={list_status}" / "data.parquet"


def _static_path(endpoint: str) -> Path:
    return Path("raw") / f"endpoint={endpoint}" / "data.parquet"


def _compact(value: str) -> str:
    return value.replace("-", "")


def _calendar_dates(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    values = []
    while current <= last:
        values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
