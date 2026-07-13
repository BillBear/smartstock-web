"""Resumable raw TuShare collection for the offline full-market ML pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq

from .config import FullMarketMLConfig
from .manifests import CollectionManifest, PartitionRecord, load_manifest, manifest_path, save_manifest, validate_partition


CORE_DAILY_ENDPOINTS = ("daily", "daily_basic", "adj_factor", "stk_limit", "suspend_d")
CARDINALITY_GATED_ENDPOINTS = ("daily", "daily_basic", "adj_factor", "stk_limit")
CORE_STATIC_ENDPOINTS = ("namechange",)
INDEX_CODES = ("000001.SH", "000300.SH", "000905.SH", "399006.SZ")
RETRY_DELAYS_SECONDS = (1, 2, 4, 8)
POINT_IN_TIME_ENDPOINTS = ("fina_indicator", "forecast", "express")


def collect_point_in_time_fundamentals(
    client: Any,
    symbols: tuple[str, ...] | list[str],
    output_root: str | Path,
    *,
    start_date: str,
    end_date: str,
    pacing_seconds: float = 0.35,
    endpoints: tuple[str, ...] = POINT_IN_TIME_ENDPOINTS,
    workers: int = 1,
) -> dict[str, Any]:
    """Collect additive, immutable announcement data with per-symbol resume."""
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    normalised_symbols = tuple(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))
    requested_endpoints = tuple(dict.fromkeys(str(endpoint) for endpoint in endpoints))
    unsupported = sorted(set(requested_endpoints) - set(POINT_IN_TIME_ENDPOINTS))
    if unsupported:
        raise ValueError("unsupported point-in-time endpoints: " + ", ".join(unsupported))
    contract = {
        "symbols": list(normalised_symbols),
        "start_date": _compact(start_date),
        "end_date": _compact(end_date),
        "endpoints": list(requested_endpoints),
    }
    manifest_path_value = root / "collection_manifest.json"
    if manifest_path_value.is_file():
        manifest = json.loads(manifest_path_value.read_text(encoding="utf-8"))
        if manifest.get("contract") != contract:
            raise ValueError("fundamental collection contract changed; use a new immutable output root")
    else:
        manifest = {"contract": contract, "partitions": {}, "status": "running", "errors": []}
        _write_json_file_atomic(manifest_path_value, manifest)

    pending: list[tuple[str, str, Path]] = []
    for endpoint in requested_endpoints:
        endpoint_records = manifest["partitions"].setdefault(endpoint, {})
        for symbol in normalised_symbols:
            path = root / f"endpoint={endpoint}" / f"symbol={symbol}" / "data.parquet"
            existing = endpoint_records.get(symbol)
            if existing and path.is_file() and _file_digest(path) == existing.get("sha256"):
                continue
            if path.exists():
                if existing:
                    raise ValueError(f"corrupted immutable partition: {path}")
                endpoint_records[symbol] = {
                    "path": str(path.relative_to(root)),
                    "row_count": pq.ParquetFile(path).metadata.num_rows,
                    "sha256": _file_digest(path),
                    "status": "collected",
                }
                continue
            pending.append((endpoint, symbol, path))

    def fetch(endpoint: str, symbol: str) -> tuple[str, str, list[dict[str, Any]], str | None]:
        try:
            rows = _records(
                _request(
                    lambda: getattr(client, endpoint)(
                        ts_code=symbol,
                        start_date=contract["start_date"],
                        end_date=contract["end_date"],
                    ),
                    pacing_seconds,
                )
            )
            return endpoint, symbol, rows, None
        except Exception as error:
            return endpoint, symbol, [], f"{type(error).__name__}: {error}"

    max_workers = max(1, min(int(workers), 8))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fundamental-fetch") as executor:
        futures = {
            executor.submit(fetch, endpoint, symbol): (endpoint, symbol, path)
            for endpoint, symbol, path in pending
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            endpoint, symbol, path = futures[future]
            _, _, rows, failure = future.result()
            endpoint_records = manifest["partitions"][endpoint]
            if failure is None:
                _write_records_atomic(path, rows)
                endpoint_records[symbol] = {
                    "path": str(path.relative_to(root)),
                    "row_count": len(rows),
                    "sha256": _file_digest(path),
                    "status": "collected",
                }
            else:
                manifest["errors"].append({"endpoint": endpoint, "symbol": symbol, "error": failure})
                endpoint_records[symbol] = {"path": str(path.relative_to(root)), "row_count": 0, "sha256": "", "status": "failed"}
            if completed % 25 == 0:
                _write_json_file_atomic(manifest_path_value, manifest)
    failed = [record for endpoints in manifest["partitions"].values() for record in endpoints.values() if record["status"] == "failed"]
    manifest["status"] = "complete" if not failed else "partial"
    manifest["partition_count"] = sum(len(records) for records in manifest["partitions"].values())
    _write_json_file_atomic(manifest_path_value, manifest)
    return manifest


def load_point_in_time_fundamentals(output_root: str | Path, endpoint: str):
    """Load only verified non-empty partitions registered by the additive collector."""
    import pandas as pd

    root = Path(output_root)
    path = root / "collection_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"fundamental collection manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = manifest.get("partitions", {}).get(endpoint, {})
    frames = []
    for symbol, record in sorted(records.items()):
        if record.get("status") != "collected" or int(record.get("row_count", 0)) <= 0:
            continue
        partition = root / record["path"]
        if not partition.is_file() or _file_digest(partition) != record.get("sha256"):
            raise ValueError(f"fundamental partition hash mismatch: {endpoint}/{symbol}")
        frames.append(pd.read_parquet(partition))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
                        start_date=_compact(config.collection.namechange_history_start), end_date=_compact(config.dates.signal_end)
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
            rows = [row for partition in reused for row in _read_records(root / partition.path)]
            manifest.trade_cal_open_dates = _verified_open_calendar_dates(rows)
            save_manifest(root, manifest)
            return rows
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
    manifest.trade_cal_open_dates = _verified_open_calendar_dates(rows)
    save_manifest(root, manifest)
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
    if not classifications:
        _mark_historical_industry_unavailable(root, manifest)
        return
    codes = [str(row["index_code"]) for row in classifications if row.get("index_code")]
    members = _collect_partition(
        root,
        manifest,
        "index_member_all",
        "SW2021-L1",
        _static_path("index_member_all"),
        lambda: _historical_member_records(client, codes, pacing_seconds),
        core=False,
        optional_group="historical_industry",
        resume=resume,
    )
    if not members:
        _mark_historical_industry_unavailable(root, manifest)
        return
    manifest.industry_relative_enabled = True
    save_manifest(root, manifest)


def _mark_historical_industry_unavailable(root: Path, manifest: CollectionManifest) -> None:
    manifest.mark_endpoint_error("historical_industry", core=False, optional_group="historical_industry")
    manifest.industry_relative_enabled = False
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
    has_manifest_record = _has_manifest_partition(manifest, endpoint, key)
    existing = _existing_partition(root, manifest, endpoint, key) if resume else None
    was_manifest_record = existing is not None
    if existing is None and resume and not has_manifest_record:
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


def _has_manifest_partition(manifest: CollectionManifest, endpoint: str, key: str) -> bool:
    try:
        manifest.partition(endpoint, key)
    except KeyError:
        return False
    return True


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
    try:
        validate_partition(root, record)
    except ValueError:
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
    table = rows.arrow_table if isinstance(rows, _Records) and rows.arrow_table is not None else pa.Table.from_pylist(rows)
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


class _Records(list[dict[str, Any]]):
    def __init__(self, rows: list[dict[str, Any]], arrow_table: pa.Table | None = None):
        super().__init__(rows)
        self.arrow_table = arrow_table


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        rows = list(value.to_dict("records"))
        try:
            return _Records(rows, pa.Table.from_pandas(value, preserve_index=False))
        except Exception:
            return rows
    return [dict(row) for row in value]


def _historical_member_records(client: Any, codes: list[str], pacing_seconds: float) -> list[dict[str, Any]]:
    results = [
        _records(_request(lambda code=code: client.index_member_all(l1_code=code), pacing_seconds))
        for code in codes
    ]
    rows = [row for result in results for row in result]
    tables = [result.arrow_table for result in results if isinstance(result, _Records) and result.arrow_table is not None]
    return _Records(rows, pa.concat_tables(tables)) if tables else rows


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


def _verified_open_calendar_dates(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    dates = set()
    for row in rows:
        if str(row.get("is_open")) != "1" or not row.get("cal_date"):
            continue
        digits = "".join(character for character in str(row["cal_date"]) if character.isdigit())
        if len(digits) >= 8:
            dates.add(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}")
    return tuple(sorted(dates))


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


def _file_digest(path: Path) -> str:
    return _sha256(path)


def _write_records_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = rows.arrow_table if isinstance(rows, _Records) and rows.arrow_table is not None else pa.Table.from_pylist(rows)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".data-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        pq.write_table(table, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_file_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    os.replace(temporary, path)
