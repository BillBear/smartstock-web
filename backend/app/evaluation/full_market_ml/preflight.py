"""Environment and TuShare readiness checks for full-market ML training."""
from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .config import FullMarketMLConfig
from .manifests import load_manifest, manifest_path, validate_partition


MINIMUM_MEMORY_BYTES = 15 * 1024**3
MINIMUM_FREE_DISK_BYTES = 40 * 1024**3
SUPPORTED_PYTHON_MAJOR_MINOR = (3, 13)
READINESS_MODES = {"online", "offline"}
PINNED_MODULES = {
    "numpy": "2.5.1",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
    "scikit-learn": "1.9.0",
    "lightgbm": "4.6.0",
    "joblib": "1.5.3",
    "psycopg2-binary": "2.9.12",
    "psutil": "7.2.2",
    "tushare": "1.4.29",
    "python-dotenv": "1.2.2",
}


def run_preflight(
    config: FullMarketMLConfig,
    env: Mapping[str, str],
    probe_client: Any,
    *,
    memory_bytes: Optional[int] = None,
    free_disk_bytes: Optional[int] = None,
    python_version: Optional[Sequence[int]] = None,
    module_versions: Optional[Mapping[str, str]] = None,
    runtime_root: Optional[Path] = None,
    today: Optional[date] = None,
    readiness_mode: str = "online",
) -> dict[str, Any]:
    """Return secret-safe readiness evidence and atomically persist it."""
    if readiness_mode not in READINESS_MODES:
        raise ValueError(f"readiness_mode must be one of {sorted(READINESS_MODES)}")

    root = runtime_root or _default_runtime_root()
    runtime_root_writable = _is_writable(root)
    observed: dict[str, Any] = {
        "config_sha256": config.sha256,
        "readiness_mode": readiness_mode,
        "python_version": _version_text(python_version or sys.version_info),
        "module_versions": _module_versions(module_versions),
        "tushare_token_configured": bool(env.get("TUSHARE_TOKEN", "").strip()),
        "memory_bytes": memory_bytes if memory_bytes is not None else _memory_bytes(),
        "free_disk_bytes": free_disk_bytes if free_disk_bytes is not None else _free_disk_bytes(root),
        "runtime_root": str(root),
        "runtime_root_writable": runtime_root_writable,
        "trade_calendar_date": None,
        "daily_probe_count": None,
        "offline_manifest_path": str(manifest_path(root, "full-build")),
        "offline_partition_count": None,
        "offline_manifest_ready": None,
    }
    blocking_codes: list[str] = []

    version = tuple(python_version or sys.version_info)
    if tuple(version[:2]) != SUPPORTED_PYTHON_MAJOR_MINOR:
        blocking_codes.append("python_version_unsupported")
    if any(observed["module_versions"].get(name) != expected for name, expected in PINNED_MODULES.items()):
        blocking_codes.append("pinned_modules_missing_or_mismatched")
    if observed["memory_bytes"] < MINIMUM_MEMORY_BYTES:
        blocking_codes.append("memory_insufficient")
    if observed["free_disk_bytes"] < MINIMUM_FREE_DISK_BYTES:
        blocking_codes.append("free_disk_insufficient")
    if not observed["runtime_root_writable"]:
        blocking_codes.append("runtime_root_unwritable")

    if readiness_mode == "offline":
        _verify_offline_assets(config, root, observed, blocking_codes)
    else:
        if not observed["tushare_token_configured"]:
            blocking_codes.append("tushare_token_missing")
        if observed["tushare_token_configured"] and probe_client is not None:
            _probe_tushare(
                probe_client,
                observed,
                blocking_codes,
                today or date.today(),
                max(4500, config.sample.minimum_daily_symbols),
            )
        elif observed["tushare_token_configured"]:
            blocking_codes.extend(("trade_calendar_unavailable", "daily_probe_insufficient"))

    result = {
        "ready": not blocking_codes,
        "blocking_codes": blocking_codes,
        "observed": observed,
    }
    if observed["runtime_root_writable"]:
        _write_json_atomically(root / "preflight.json", result)
    return result


def _probe_tushare(
    probe_client: Any,
    observed: dict[str, Any],
    blocking_codes: list[str],
    today: date,
    minimum_daily_symbols: int,
) -> None:
    try:
        records = _records(
            probe_client.trade_cal(
                exchange="",
                start_date=(today - timedelta(days=31)).strftime("%Y%m%d"),
                end_date=today.strftime("%Y%m%d"),
                fields="cal_date,is_open",
            )
        )
        open_dates = [str(row["cal_date"]) for row in records if str(row.get("is_open")) == "1" and row.get("cal_date")]
        trade_date = max(open_dates)
    except Exception:
        blocking_codes.append("trade_calendar_unavailable")
        blocking_codes.append("daily_probe_insufficient")
        return

    observed["trade_calendar_date"] = trade_date
    try:
        observed["daily_probe_count"] = len(_records(probe_client.daily(trade_date=trade_date)))
    except Exception:
        blocking_codes.append("daily_probe_insufficient")
        return
    if observed["daily_probe_count"] < minimum_daily_symbols:
        blocking_codes.append("daily_probe_insufficient")


def _verify_offline_assets(
    config: FullMarketMLConfig,
    root: Path,
    observed: dict[str, Any],
    blocking_codes: list[str],
) -> None:
    path = manifest_path(root, "full-build")
    if not path.is_file():
        blocking_codes.append("offline_raw_manifest_missing")
        return
    try:
        manifest = load_manifest(root, "full-build", config.sha256, config.collection.request_pacing_seconds)
    except ValueError:
        blocking_codes.append("offline_raw_manifest_mismatched")
        return

    observed["offline_partition_count"] = len(manifest.partitions)
    observed["offline_manifest_ready"] = manifest.ready
    if not manifest.ready:
        blocking_codes.append("offline_raw_manifest_not_ready")
        return
    if not manifest.partitions:
        blocking_codes.append("offline_raw_manifest_empty")
        return
    if not manifest.trade_cal_open_dates:
        blocking_codes.append("offline_trade_calendar_unavailable")
        return
    observed["trade_calendar_date"] = max(manifest.trade_cal_open_dates).replace("-", "")
    optional_failed_endpoints = set(manifest.optional_failures)
    try:
        for record in manifest.partitions:
            if record.status == "failed" and record.endpoint in optional_failed_endpoints:
                continue
            validate_partition(root, record)
    except ValueError:
        blocking_codes.append("offline_raw_assets_invalid")


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        return list(value.to_dict("records"))
    return list(value)


def _module_versions(provided: Optional[Mapping[str, str]]) -> dict[str, Optional[str]]:
    if provided is not None:
        return {name: provided.get(name) for name in PINNED_MODULES}
    versions: dict[str, Optional[str]] = {}
    for name in PINNED_MODULES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _memory_bytes() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:
        return 0


def _free_disk_bytes(root: Path) -> int:
    try:
        return int(os.statvfs(root.parent if not root.exists() else root).f_bavail * os.statvfs(root.parent if not root.exists() else root).f_frsize)
    except OSError:
        return 0


def _is_writable(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".preflight-", delete=True):
            pass
    except OSError:
        return False
    return True


def _write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".preflight-", suffix=".tmp", delete=False) as temporary_file:
        temporary_file.write(encoded)
        temporary_file.flush()
        os.fsync(temporary_file.fileno())
        temporary_path = Path(temporary_file.name)
    os.replace(temporary_path, path)


def _default_runtime_root() -> Path:
    return Path(__file__).resolve().parents[4] / "runtime" / "ml_full_market"


def _version_text(version: Sequence[int]) -> str:
    return ".".join(str(part) for part in tuple(version)[:3])
