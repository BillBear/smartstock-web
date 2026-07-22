"""Immutable raw-data capture for a future-only ML research lockbox."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Mapping, Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


REQUIRED_ENDPOINTS = ("daily", "daily_basic", "adj_factor", "stk_limit", "suspend_d")
FULL_MARKET_ENDPOINTS = frozenset(REQUIRED_ENDPOINTS) - {"suspend_d"}
MIN_FULL_MARKET_ROWS = 4_500


class MLProspectiveLockboxError(ValueError):
    """Raised when a proposed future-data batch breaks the lockbox contract."""


class ProspectiveFetcher(Protocol):
    def fetch(self, endpoint: str, trade_date: str) -> pd.DataFrame: ...


def normalize_trade_date(value: object, source: str) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise MLProspectiveLockboxError(f"{source} has an invalid trade date: {value}")
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def validate_capture_date(value: object, *, development_cutoff: object) -> str:
    capture_date = normalize_trade_date(value, "capture date")
    cutoff = normalize_trade_date(development_cutoff, "development cutoff")
    if capture_date <= cutoff:
        raise MLProspectiveLockboxError(
            f"capture date {capture_date} must be strictly after development cutoff {cutoff}"
        )
    return capture_date


def validate_endpoint_frame(endpoint: str, frame: pd.DataFrame, requested_trade_date: object) -> pd.DataFrame:
    """Validate one raw endpoint response without deriving features or labels."""
    if endpoint not in REQUIRED_ENDPOINTS:
        raise MLProspectiveLockboxError(f"unsupported prospective endpoint: {endpoint}")
    if not isinstance(frame, pd.DataFrame):
        raise MLProspectiveLockboxError(f"{endpoint} response is not a DataFrame")
    if "trade_date" not in frame.columns:
        raise MLProspectiveLockboxError(f"{endpoint} response misses trade_date")
    expected_date = normalize_trade_date(requested_trade_date, "requested trade date")
    result = frame.copy()
    if result.empty:
        if endpoint in FULL_MARKET_ENDPOINTS:
            raise MLProspectiveLockboxError(f"{endpoint} has fewer than {MIN_FULL_MARKET_ROWS} rows for {expected_date}")
        result["trade_date"] = result["trade_date"].astype("string")
        return result

    normalized_dates = result["trade_date"].map(lambda value: normalize_trade_date(value, endpoint))
    source_dates = set(normalized_dates.tolist())
    if source_dates != {expected_date}:
        rendered = ", ".join(sorted(source_dates))
        raise MLProspectiveLockboxError(
            f"{endpoint} source date {rendered} does not match requested date {expected_date}"
        )
    if "ts_code" not in result.columns:
        raise MLProspectiveLockboxError(f"{endpoint} response misses ts_code")
    if result["ts_code"].isna().any() or result["ts_code"].astype("string").str.strip().eq("").any():
        raise MLProspectiveLockboxError(f"{endpoint} response has an empty ts_code")
    if endpoint in FULL_MARKET_ENDPOINTS and len(result) < MIN_FULL_MARKET_ROWS:
        raise MLProspectiveLockboxError(f"{endpoint} has fewer than {MIN_FULL_MARKET_ROWS} rows for {expected_date}")
    result["trade_date"] = normalized_dates
    return result


def capture_prospective_batch(
    *,
    fetcher: ProspectiveFetcher,
    trade_dates: tuple[str, ...] | list[str],
    development_cutoff: str,
    output_dir: str | Path,
    code_commit: str,
    input_provenance: Mapping[str, str],
) -> dict[str, Any]:
    """Capture a new immutable raw batch and never evaluate its outcomes."""
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"prospective lockbox output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.running"
    if temporary.exists():
        raise FileExistsError(f"prospective lockbox requires inspection before retry: {temporary}")
    requested_dates = tuple(sorted({validate_capture_date(value, development_cutoff=development_cutoff) for value in trade_dates}))
    if not requested_dates:
        raise MLProspectiveLockboxError("prospective lockbox has no open trading dates to capture")
    if not code_commit.strip():
        raise MLProspectiveLockboxError("prospective lockbox requires a code commit")
    if not input_provenance or any(not str(value).strip() for value in input_provenance.values()):
        raise MLProspectiveLockboxError("prospective lockbox requires non-empty input provenance")

    temporary.mkdir()
    try:
        _write_progress(temporary, "capture", status="running", requested_trade_date_count=len(requested_dates))
        files: list[dict[str, Any]] = []
        for index, trade_date in enumerate(requested_dates, start=1):
            compact_date = trade_date.replace("-", "")
            for endpoint in REQUIRED_ENDPOINTS:
                frame = validate_endpoint_frame(endpoint, fetcher.fetch(endpoint, compact_date), trade_date)
                relative_path = Path("raw") / endpoint / f"trade_date={compact_date}" / "data.parquet"
                target = temporary / relative_path
                _write_parquet(target, frame)
                files.append(
                    {
                        "endpoint": endpoint,
                        "trade_date": trade_date,
                        "path": str(relative_path),
                        "row_count": int(len(frame)),
                        "sha256": _sha256_file(target),
                    }
                )
            _write_progress(
                temporary,
                "capture",
                status="running",
                requested_trade_date_count=len(requested_dates),
                captured_trade_date_count=index,
                latest_captured_trade_date=trade_date,
            )

        manifest = {
            "schema_version": 1,
            "status": "complete",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "code_commit": str(code_commit),
            "development_cutoff": normalize_trade_date(development_cutoff, "development cutoff"),
            "requested_trade_dates": list(requested_dates),
            "captured_trade_dates": list(requested_dates),
            "required_endpoints": list(REQUIRED_ENDPOINTS),
            "minimum_full_market_rows": MIN_FULL_MARKET_ROWS,
            "input_provenance": dict(sorted((str(key), str(value)) for key, value in input_provenance.items())),
            "files": files,
            "outcome_labels_opened": False,
            "model_selection_allowed": False,
            "production_integration_allowed": False,
        }
        _write_json(temporary / "prospective_batch_manifest.json", manifest)
        _write_progress(temporary, "complete", status="complete", captured_trade_date_count=len(requested_dates))
        os.replace(temporary, destination)
        return {
            "status": "complete",
            "output_dir": str(destination),
            "captured_trade_dates": list(requested_dates),
            "outcome_labels_opened": False,
            "model_selection_allowed": False,
            "production_integration_allowed": False,
        }
    except BaseException as error:
        _write_progress(
            temporary,
            "failed",
            status="failed",
            failure_type=type(error).__name__,
            failure_message=str(error),
        )
        raise


def _write_progress(path: Path, stage: str, *, status: str, **details: Any) -> None:
    _write_json(
        path / "progress.json",
        {
            "stage": stage,
            "status": status,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            **details,
        },
    )


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), handle, compression="zstd")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
