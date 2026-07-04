#!/usr/bin/env python3
"""Secret-safe cloud deployment boundary checks for SmartStock AI.

This script does not validate strategy quality and does not load application
code. It only checks whether required runtime configuration is present and
whether local-only paths/settings would block a future cloud deployment.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


REQUIRED_VARS = [
    "APP_ENV",
    "APP_VERSION",
    "GIT_COMMIT",
    "COACH_DB_URL",
    "TUSHARE_TOKEN",
    "ENABLE_MOCK_FALLBACK",
    "MODEL_ARTIFACT_ROOT",
    "STRATEGY_EVIDENCE_ROOT",
    "LOG_DIR",
]

LOCAL_PATH_VARS = [
    "MODEL_ARTIFACT_ROOT",
    "STRATEGY_EVIDENCE_ROOT",
    "LOG_DIR",
]

SECRET_VARS = {
    "TUSHARE_TOKEN",
    "COACH_DB_URL",
}


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return values


def configured_value(key: str, env_values: Dict[str, str]) -> Optional[str]:
    value = env_values.get(key)
    if value is not None and str(value).strip() != "":
        return str(value).strip()
    value = os.environ.get(key)
    if value is not None and str(value).strip() != "":
        return str(value).strip()
    return None


def safe_status_line(key: str, value: Optional[str]) -> str:
    if not value:
        return f"{key}: missing"
    if key in SECRET_VARS:
        return f"{key}: configured"
    return f"{key}: configured ({value})"


def looks_local_path(value: str) -> bool:
    expanded = os.path.expanduser(value)
    local_prefixes = (
        "/Users/",
        "/var/folders/",
        "/private/var/folders/",
    )
    return expanded.startswith(local_prefixes)


def check_values(env_values: Dict[str, str], strict: bool) -> Tuple[List[str], List[str], List[str]]:
    lines: List[str] = []
    warnings: List[str] = []
    failures: List[str] = []

    for key in REQUIRED_VARS:
        value = configured_value(key, env_values)
        lines.append(safe_status_line(key, value))
        if not value:
            message = f"{key} is not configured"
            (failures if strict else warnings).append(message)

    app_env = (configured_value("APP_ENV", env_values) or "").lower()
    if strict and app_env in {"", "local"}:
        failures.append("APP_ENV must be a non-local environment for cloud deployment")

    mock_fallback = (configured_value("ENABLE_MOCK_FALLBACK", env_values) or "").lower()
    if mock_fallback not in {"false", "0", "no"}:
        (failures if strict else warnings).append("ENABLE_MOCK_FALLBACK should be false for real-data deployments")

    use_mock_data = (configured_value("USE_MOCK_DATA", env_values) or "false").lower()
    if use_mock_data not in {"false", "0", "no"}:
        (failures if strict else warnings).append("USE_MOCK_DATA should be false for real-data deployments")

    db_url = configured_value("COACH_DB_URL", env_values) or ""
    if "127.0.0.1" in db_url or "localhost" in db_url:
        (failures if strict else warnings).append("COACH_DB_URL points to localhost; cloud deployment needs a managed or provisioned database URL")

    for key in LOCAL_PATH_VARS:
        value = configured_value(key, env_values)
        if value and looks_local_path(value):
            (failures if strict else warnings).append(f"{key} uses a local macOS path")

    return lines, warnings, failures


def default_env_file(repo_root: Path) -> Path:
    backend_env = repo_root / "backend" / ".env"
    if backend_env.exists():
        return backend_env
    return repo_root / "backend" / ".env.example"


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check SmartStock cloud deployment configuration boundaries.")
    parser.add_argument("--env-file", help="Path to a .env file. Defaults to backend/.env, then backend/.env.example.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when cloud-blocking issues are found.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    env_file = Path(args.env_file).expanduser() if args.env_file else default_env_file(repo_root)
    if not env_file.is_absolute():
        env_file = (Path.cwd() / env_file).resolve()

    env_values = parse_env_file(env_file)
    lines, warnings, failures = check_values(env_values, strict=bool(args.strict))

    print("SmartStock cloud readiness")
    print(f"repo_root: {repo_root}")
    print(f"env_file: {env_file} ({'present' if env_file.exists() else 'missing'})")
    print(f"mode: {'strict' if args.strict else 'advisory'}")
    for line in lines:
        print(line)
    for warning in warnings:
        print(f"warning: {warning}")
    for failure in failures:
        print(f"failure: {failure}")

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
