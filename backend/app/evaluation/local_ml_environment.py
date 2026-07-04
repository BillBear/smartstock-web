from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


REQUIRED_PACKAGES = [
    "pandas",
    "numpy",
    "sklearn",
    "joblib",
    "scipy",
    "psycopg2",
    "sqlalchemy",
    "akshare",
    "tushare",
]
OPTIONAL_PACKAGES = ["pyarrow", "xgboost", "lightgbm"]


def local_secret_candidates(repo_root: str | Path) -> List[str]:
    root = Path(repo_root).expanduser().resolve()
    candidates: List[str] = []
    for base in [root, *root.parents]:
        candidates.append(str(base / ".local-secrets" / "smartstock.env"))
    candidates.append(str(root / "backend" / ".env"))
    return _dedupe(candidates)


def evaluate_dependency_status() -> Dict[str, Any]:
    required = {name: _package_status(name, blocking=True) for name in REQUIRED_PACKAGES}
    optional = {name: _package_status(name, blocking=False) for name in OPTIONAL_PACKAGES}
    missing_required = [
        name
        for name, status in required.items()
        if status.get("status") != "available"
    ]
    return {
        "python_version": sys.version.split()[0],
        "required": required,
        "optional": optional,
        "required_ok": not missing_required,
        "missing_required": missing_required,
    }


def evaluate_environment_report(
    config: Dict[str, Any],
    data_source_manager: Any,
    history_smoke_symbols: Iterable[str],
    check_system: bool = True,
) -> Dict[str, Any]:
    blocking: List[str] = []
    dependency = evaluate_dependency_status()
    if not dependency["required_ok"]:
        blocking.append("missing_required_python_packages")

    snapshot_count = 0
    snapshot_error = None
    try:
        snapshot = data_source_manager.get_a_share_snapshot() or []
        snapshot_count = len(snapshot)
    except Exception as exc:
        snapshot_error = str(exc)[:240]
        blocking.append("full_snapshot_fetch_failed")

    min_snapshot = int(config.get("min_full_snapshot_count") or 5000)
    if snapshot_count < min_snapshot:
        blocking.append(f"full_snapshot_count_below_{min_snapshot}")

    history_results = []
    for symbol in history_smoke_symbols:
        row_count = 0
        error = None
        try:
            df = data_source_manager.get_history_data_range(
                str(symbol),
                start_date="2026-06-01",
                end_date="2026-07-03",
            )
            row_count = len(df) if hasattr(df, "__len__") else 0
        except Exception as exc:
            error = str(exc)[:240]
        result = {"symbol": str(symbol), "rows": int(row_count)}
        if error:
            result["error"] = error
        history_results.append(result)
        if row_count <= 0:
            blocking.append(f"history_smoke_failed_{symbol}")

    system = _system_status(config, check_system=check_system)
    if system.get("disk_free_below_required"):
        blocking.append("disk_free_below_required")
    if system.get("memory_below_required"):
        blocking.append("memory_below_required")

    token_configured = bool(os.environ.get("TUSHARE_TOKEN"))
    if not token_configured:
        blocking.append("tushare_token_missing")

    return {
        "ready": not blocking,
        "blocking_codes": sorted(set(blocking)),
        "dependency": dependency,
        "snapshot_count": snapshot_count,
        "snapshot_error": snapshot_error,
        "history_smoke": history_results,
        "system": system,
        "tushare_token_configured": token_configured,
        "mock_fallback_allowed": os.environ.get("ENABLE_MOCK_FALLBACK") == "True",
    }


def _package_status(name: str, blocking: bool) -> Dict[str, Any]:
    if importlib.util.find_spec(name) is None:
        return {
            "installed": False,
            "status": "missing",
            "blocking": bool(blocking),
        }
    try:
        module = importlib.import_module(name)
        return {
            "installed": True,
            "status": "available",
            "blocking": False,
            "version": str(getattr(module, "__version__", "unknown")),
        }
    except Exception as exc:
        return {
            "installed": True,
            "status": "unavailable",
            "blocking": bool(blocking),
            "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _system_status(config: Dict[str, Any], check_system: bool) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "checked": bool(check_system),
        "platform": platform.platform(),
    }
    if not check_system:
        return status

    repo_root = Path(__file__).resolve().parents[3]
    usage = shutil.disk_usage(repo_root)
    free_gb = round(usage.free / (1024**3), 2)
    min_disk = float(config.get("min_disk_free_gb") or 50)
    status["disk_free_gb"] = free_gb
    status["min_disk_free_gb"] = min_disk
    status["disk_free_below_required"] = free_gb < min_disk

    min_memory = float(config.get("min_memory_gb") or 12)
    status["min_memory_gb"] = min_memory
    if sys.platform == "darwin":
        try:
            mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
            memory_gb = round(mem_bytes / (1024**3), 2)
            status["memory_gb"] = memory_gb
            status["memory_below_required"] = memory_gb < min_memory
        except Exception as exc:
            status["memory_check_error"] = str(exc)[:160]
    return status
