"""Read-only root-cause accounting for detailed moneyflow coverage gaps."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyarrow.parquet as pq

from .tushare_training_field_lineage_audit import DETAILED_MONEYFLOW_AMOUNT_FIELDS


CAUSES = (
    "covered",
    "missing_moneyflow_partition",
    "missing_moneyflow_symbol",
    "null_detailed_field",
)
_SAMPLE_LIMIT = 20


class MoneyflowCoverageForensicsError(ValueError):
    """Raised when an immutable source run cannot be audited safely."""


def audit_moneyflow_coverage(*, source_run_root: str | Path, code_commit: str) -> dict[str, object]:
    """Classify every daily-universe row once without changing source data."""
    root = _require_directory(source_run_root, "source run root")
    manifest_path = root / "manifests" / "full-build.json"
    manifest = _read_manifest(manifest_path)
    daily_records = _records_by_key(manifest, "daily", required=True)
    moneyflow_records = _records_by_key(manifest, "moneyflow", required=False)
    cause_counts = {cause: 0 for cause in CAUSES}
    board_cause_counts: dict[str, dict[str, int]] = defaultdict(lambda: {cause: 0 for cause in CAUSES})
    field_null_counts = {field: 0 for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS}
    samples: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    daily_coverage = []
    daily_row_count = 0

    for trade_date, daily_record in sorted(daily_records.items()):
        daily_codes = _read_daily_codes(_partition_path(root, daily_record))
        moneyflow_record = moneyflow_records.get(trade_date)
        moneyflow_rows = _read_moneyflow_rows(root, moneyflow_record) if moneyflow_record is not None else None
        daily_counts = {cause: 0 for cause in CAUSES}
        for symbol in daily_codes:
            board = board_for(symbol)
            cause = _cause_for(symbol, moneyflow_rows, field_null_counts)
            cause_counts[cause] += 1
            daily_counts[cause] += 1
            board_cause_counts[board][cause] += 1
            _append_sample(samples, board, cause, symbol)
        daily_row_count += len(daily_codes)
        daily_coverage.append(
            {
                "trade_date": trade_date,
                "daily_count": len(daily_codes),
                **daily_counts,
                "detailed_moneyflow_coverage": daily_counts["covered"] / len(daily_codes) if daily_codes else 0.0,
                "moneyflow_partition_present": moneyflow_rows is not None,
            }
        )

    if daily_row_count == 0:
        raise MoneyflowCoverageForensicsError("source manifest has no daily universe rows")
    return {
        "schema_version": 1,
        "status": "complete_read_only_forensics",
        "code_commit": str(code_commit),
        "source": {
            "run_root": str(root),
            "full_build_manifest_sha256": _sha256_file(manifest_path),
        },
        "daily_row_count": daily_row_count,
        "trade_date_count": len(daily_coverage),
        "full_universe_detailed_coverage": cause_counts["covered"] / daily_row_count,
        "cause_counts": cause_counts,
        "board_cause_counts": {board: dict(counts) for board, counts in sorted(board_cause_counts.items())},
        "detailed_field_null_counts": field_null_counts,
        "daily_coverage": daily_coverage,
        "samples": {board: {cause: values for cause, values in sorted(causes.items())} for board, causes in sorted(samples.items())},
        "interpretation": (
            "This report describes source coverage only. It does not relax the 95% gate, "
            "approve a sub-universe, or authorize model training or production integration."
        ),
    }


def canonical_ts_code(value: object) -> str:
    code = str(value).strip().upper()
    if not code or "." not in code:
        raise MoneyflowCoverageForensicsError(f"invalid ts_code: {value}")
    return code


def board_for(code: str) -> str:
    suffix = code.rsplit(".", 1)[1]
    return suffix if suffix in {"BJ", "SH", "SZ"} else "OTHER"


def _records_by_key(manifest: Mapping[str, object], endpoint: str, *, required: bool) -> dict[str, Mapping[str, object]]:
    records: dict[str, Mapping[str, object]] = {}
    partitions = manifest.get("partitions")
    if not isinstance(partitions, list):
        raise MoneyflowCoverageForensicsError("full-build manifest has invalid partitions")
    for record in partitions:
        if not isinstance(record, Mapping) or record.get("endpoint") != endpoint:
            continue
        key = str(record.get("key", ""))
        if not key:
            raise MoneyflowCoverageForensicsError(f"{endpoint} partition has no key")
        if key in records:
            raise MoneyflowCoverageForensicsError(f"duplicate {endpoint} manifest key: {key}")
        if endpoint == "daily" and record.get("status") == "failed":
            raise MoneyflowCoverageForensicsError(f"daily partition failed: {key}")
        records[key] = record
    if required and not records:
        raise MoneyflowCoverageForensicsError(f"full-build manifest has no {endpoint} partitions")
    return records


def _read_daily_codes(path: Path) -> tuple[str, ...]:
    frame = _read_columns(path, ("ts_code",), "daily")
    codes = tuple(canonical_ts_code(value) for value in frame["ts_code"].tolist())
    if len(set(codes)) != len(codes):
        raise MoneyflowCoverageForensicsError(f"duplicate daily ts_code: {path}")
    return codes


def _read_moneyflow_rows(root: Path, record: Mapping[str, object]) -> dict[str, dict[str, object]] | None:
    if record.get("status") == "failed":
        return None
    path = _partition_path(root, record)
    frame = _read_columns(path, ("ts_code", *DETAILED_MONEYFLOW_AMOUNT_FIELDS), "moneyflow")
    frame["ts_code"] = frame["ts_code"].map(canonical_ts_code)
    if frame["ts_code"].duplicated().any():
        raise MoneyflowCoverageForensicsError(f"duplicate moneyflow ts_code: {path}")
    return {
        str(row["ts_code"]): {field: row[field] for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS}
        for _, row in frame.iterrows()
    }


def _cause_for(symbol: str, moneyflow_rows: dict[str, dict[str, object]] | None, field_null_counts: dict[str, int]) -> str:
    if moneyflow_rows is None:
        return "missing_moneyflow_partition"
    row = moneyflow_rows.get(symbol)
    if row is None:
        return "missing_moneyflow_symbol"
    null_fields = [field for field in DETAILED_MONEYFLOW_AMOUNT_FIELDS if pd.isna(row[field])]
    if null_fields:
        for field in null_fields:
            field_null_counts[field] += 1
        return "null_detailed_field"
    return "covered"


def _append_sample(samples: dict[str, dict[str, list[str]]], board: str, cause: str, symbol: str) -> None:
    values = samples[board][cause]
    if len(values) < _SAMPLE_LIMIT:
        values.append(symbol)


def _read_columns(path: Path, columns: tuple[str, ...], endpoint: str) -> pd.DataFrame:
    if not path.is_file():
        raise MoneyflowCoverageForensicsError(f"{endpoint} partition is missing: {path}")
    schema = pq.ParquetFile(path).schema_arrow
    missing = sorted(set(columns) - set(schema.names))
    if missing:
        raise MoneyflowCoverageForensicsError(f"{endpoint} partition is missing columns: " + ", ".join(missing))
    return pq.read_table(path, columns=list(columns)).to_pandas()


def _partition_path(root: Path, record: Mapping[str, object]) -> Path:
    value = record.get("path")
    if not isinstance(value, str) or not value:
        raise MoneyflowCoverageForensicsError("partition has no path")
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise MoneyflowCoverageForensicsError(f"partition path escapes source root: {value}") from error
    return candidate


def _read_manifest(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        raise MoneyflowCoverageForensicsError(f"full-build manifest is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise MoneyflowCoverageForensicsError("full-build manifest must be a JSON object")
    return value


def _require_directory(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise MoneyflowCoverageForensicsError(f"{label} is missing: {path}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
