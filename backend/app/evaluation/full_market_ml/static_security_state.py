"""Immutable stock-master evidence for point-in-time research-sample checks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


STOCK_BASIC_FIELDS = "ts_code,symbol,name,market,exchange,list_status,list_date,delist_date,is_hs"
_STATUSES = ("L", "D", "P")
_COLUMNS = tuple(STOCK_BASIC_FIELDS.split(","))
_MINIMUM_LISTED_ROWS = 4500


@dataclass(frozen=True)
class StaticSecurityStateAsset:
    root: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str
    as_of_date: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "asset_name": self.root.name,
            "manifest_sha256": self.manifest_sha256,
            "observed_at_utc": self.manifest["observed_at_utc"],
            "as_of_date": self.as_of_date,
            "status": self.manifest["status"],
            "partitions": [
                {
                    "key": record["key"],
                    "row_count": record["row_count"],
                    "columns": record["columns"],
                    "status": record["status"],
                    "sha256": record["sha256"],
                }
                for record in self.manifest["partitions"]
            ],
        }


def collect_static_security_state(
    client: Any,
    asset_parent: str | Path,
    observed_at_utc: str | None = None,
) -> StaticSecurityStateAsset:
    """Fetch L/D/P stock master partitions and publish one immutable asset."""
    parent = Path(asset_parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    observed_at = _normalise_observed_at(observed_at_utc)
    temporary = Path(tempfile.mkdtemp(prefix=".security-state-", dir=parent))
    try:
        frames = {
            status: _normalise_frame(client.stock_basic(exchange="", list_status=status, fields=STOCK_BASIC_FIELDS), status)
            for status in _STATUSES
        }
        _validate_frames(frames)
        partitions = [_write_partition(temporary, status, frames[status]) for status in _STATUSES]
        manifest = _with_sha256(
            {
                "schema_version": "static_security_state_v1",
                "asset_kind": "stock_basic_interval_master",
                "observed_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
                "as_of_date": observed_at.date().isoformat(),
                "status": "verified",
                "partitions": sorted(partitions, key=lambda record: str(record["key"])),
            }
        )
        final_root = parent / f"security_{manifest['sha256'][:16]}"
        if final_root.exists():
            raise FileExistsError(f"static security-state asset already exists: {final_root}")
        _write_json_atomic(temporary / "manifests" / "static-security-state.json", manifest)
        os.replace(temporary, final_root)
        return StaticSecurityStateAsset(
            root=final_root,
            manifest=manifest,
            manifest_sha256=str(manifest["sha256"]),
            as_of_date=str(manifest["as_of_date"]),
        )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def load_static_security_state_asset(asset_path: str | Path) -> StaticSecurityStateAsset:
    """Load and fully validate an already published static-security asset."""
    root = Path(asset_path).expanduser().resolve()
    manifest_path = root / "manifests" / "static-security-state.json"
    manifest = _load_json(manifest_path)
    _verify_manifest(manifest, root)
    return StaticSecurityStateAsset(
        root=root,
        manifest=manifest,
        manifest_sha256=str(manifest["sha256"]),
        as_of_date=str(manifest["as_of_date"]),
    )


def validate_static_security_state_for_panel(
    asset: StaticSecurityStateAsset,
    panel_symbols: Iterable[str],
    panel_latest_trade_date: str,
) -> dict[str, Any]:
    """Verify that one static master covers the immutable panel's symbols and end date."""
    checked = load_static_security_state_asset(asset.root)
    panel = {str(symbol).strip() for symbol in panel_symbols if str(symbol).strip()}
    static_symbols: list[str] = []
    for record in checked.manifest["partitions"]:
        path = checked.root / str(record["path"])
        frame = pd.read_parquet(path, columns=["symbol"])
        static_symbols.extend(str(value).strip() for value in frame["symbol"].tolist() if str(value).strip())
    static_set = set(static_symbols)
    duplicates = len(static_symbols) - len(static_set)
    missing = sorted(panel - static_set)
    blocking: list[str] = []
    if not panel:
        blocking.append("security_state:panel_symbols_unavailable")
    if missing:
        blocking.append("security_state:panel_symbols_missing")
    if duplicates:
        blocking.append("security_state:duplicate_static_symbols")
    if checked.as_of_date < _date_text(panel_latest_trade_date):
        blocking.append("security_state:asset_as_of_before_panel_end")
    return {
        "panel_latest_trade_date": _date_text(panel_latest_trade_date),
        "asset_as_of_date": checked.as_of_date,
        "panel_symbol_count": len(panel),
        "static_symbol_count": len(static_set),
        "missing_panel_symbol_count": len(missing),
        "missing_panel_symbols": missing,
        "duplicate_static_symbol_count": duplicates,
        "blocking_codes": sorted(blocking),
        "validation_status": "verified" if not blocking else "blocked",
    }


def _normalise_frame(value: Any, status: str) -> pd.DataFrame:
    frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value)
    if list(frame.columns) != list(_COLUMNS):
        raise ValueError(f"stock_basic:{status} schema must equal requested fields")
    return frame.copy()


def _validate_frames(frames: Mapping[str, pd.DataFrame]) -> None:
    symbols: set[str] = set()
    for status in _STATUSES:
        frame = frames[status]
        if status == "L" and len(frame.index) < _MINIMUM_LISTED_ROWS:
            raise ValueError(f"stock_basic:L has fewer than {_MINIMUM_LISTED_ROWS} rows")
        if status == "D" and frame.empty:
            raise ValueError("stock_basic:D must contain delisted rows")
        if frame.empty:
            continue
        listed_status = frame["list_status"].fillna("").astype(str).str.strip().str.upper()
        if not listed_status.eq(status).all():
            raise ValueError(f"stock_basic:{status} has mismatched list_status")
        frame_symbols = frame["symbol"].fillna("").astype(str).str.strip()
        if frame_symbols.eq("").any() or frame_symbols.duplicated().any() or any(value in symbols for value in frame_symbols):
            raise ValueError(f"stock_basic:{status} has duplicate or missing symbols")
        symbols.update(frame_symbols.tolist())
        list_dates = _parse_dates(frame["list_date"], f"stock_basic:{status}:list_date")
        delist_text = frame["delist_date"].fillna("").astype(str).str.strip()
        if status == "D":
            delist_dates = _parse_dates(delist_text, "stock_basic:D:delist_date")
            if (delist_dates < list_dates).any():
                raise ValueError("stock_basic:D has delist_date before list_date")
        elif delist_text.ne("").any():
            raise ValueError(f"stock_basic:{status} must not contain delist_date")


def _write_partition(root: Path, status: str, frame: pd.DataFrame) -> dict[str, Any]:
    relative = Path("raw") / "endpoint=stock_basic" / f"list_status={status}" / "data.parquet"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)
    return {
        "endpoint": "stock_basic",
        "key": status,
        "path": str(relative),
        "sha256": _sha256_file(path),
        "row_count": int(len(frame.index)),
        "columns": list(frame.columns),
        "status": "valid-with-rows" if not frame.empty else "valid-but-empty",
        "request": {"exchange": "", "list_status": status, "fields": STOCK_BASIC_FIELDS},
    }


def _verify_manifest(manifest: Mapping[str, Any], root: Path) -> None:
    if manifest.get("schema_version") != "static_security_state_v1":
        raise ValueError("unsupported static security-state manifest")
    if manifest.get("asset_kind") != "stock_basic_interval_master" or manifest.get("status") != "verified":
        raise ValueError("static security-state manifest is not verified")
    expected_hash = _payload_sha256(manifest)
    if str(manifest.get("sha256", "")).lower() != expected_hash:
        raise ValueError("static security-state manifest hash is invalid")
    if root.name != f"security_{expected_hash[:16]}":
        raise ValueError("static security-state asset path is not canonical")
    observed_at = _normalise_observed_at(str(manifest.get("observed_at_utc", "")))
    if str(manifest.get("as_of_date", "")) != observed_at.date().isoformat():
        raise ValueError("static security-state as_of_date does not match observed_at_utc")
    records = manifest.get("partitions")
    if not isinstance(records, list) or [record.get("key") for record in records if isinstance(record, Mapping)] != ["D", "L", "P"]:
        raise ValueError("static security-state manifest must contain D/L/P partitions")
    frames: dict[str, pd.DataFrame] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("static security-state partition record is invalid")
        status = str(record.get("key", ""))
        relative = Path(str(record.get("path", "")))
        if record.get("endpoint") != "stock_basic" or status not in _STATUSES or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("static security-state partition path is invalid")
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise FileNotFoundError(f"static security-state partition is unavailable: {relative}")
        if _sha256_file(path) != str(record.get("sha256", "")).lower():
            raise ValueError(f"static security-state partition hash mismatch: {relative}")
        frame = pd.read_parquet(path)
        if list(frame.columns) != list(record.get("columns", [])):
            raise ValueError(f"static security-state partition schema mismatch: {relative}")
        if int(record.get("row_count", -1)) != len(frame.index):
            raise ValueError(f"static security-state partition row count mismatch: {relative}")
        frames[status] = _normalise_frame(frame, status)
    _validate_frames(frames)


def _normalise_observed_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at_utc must be an ISO-8601 timestamp") from exc
    if observed.tzinfo is None:
        raise ValueError("observed_at_utc must include a timezone")
    return observed.astimezone(timezone.utc).replace(microsecond=0)


def _parse_dates(values: pd.Series, label: str) -> pd.Series:
    text = values.fillna("").astype(str).str.strip()
    parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if text.eq("").any() or parsed.isna().any():
        raise ValueError(f"{label} must contain valid YYYYMMDD values")
    return parsed


def _date_text(value: str) -> str:
    text = str(value).strip()
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError("panel_latest_trade_date must be a valid date")
    return parsed.date().isoformat()


def _with_sha256(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["sha256"] = _payload_sha256(result)
    return result


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value.pop("sha256", None)
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"static security-state manifest is unavailable: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("static security-state manifest must be an object")
    return value


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".manifest-", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write((json.dumps(dict(payload), ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
