#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(basename "$(dirname "$REPO_ROOT")")" == ".worktrees" ]]; then
  WORKSPACE_ROOT="$(cd "$REPO_ROOT/../.." && pwd)"
else
  WORKSPACE_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
fi
ML_PYTHON="$WORKSPACE_ROOT/.venvs/ml-py313/bin/python"
ML_ASSET_ROOT="${ML_ASSET_ROOT:-$WORKSPACE_ROOT/ml-assets}"

if [[ ! -x "$ML_PYTHON" ]]; then
  echo "ML_PYTHON is unavailable: $ML_PYTHON" >&2
  exit 2
fi

ML_EXPECTED_PYTHON="$WORKSPACE_ROOT/.venvs/ml-py313/bin/python" \
ML_ASSET_ROOT="$ML_ASSET_ROOT" \
  "$ML_PYTHON" - <<'PY'
import importlib.metadata as metadata
import os
import platform
import shutil
import sys
from pathlib import Path

expected_python = Path(os.environ["ML_EXPECTED_PYTHON"]).resolve()
asset_root = Path(os.environ["ML_ASSET_ROOT"])
expected = {
    "numpy": "2.5.1",
    "pandas": "3.0.3",
    "pyarrow": "25.0.0",
    "scikit-learn": "1.9.0",
    "lightgbm": "4.6.0",
    "joblib": "1.5.3",
    "tushare": "1.4.29",
}

errors = []
if Path(sys.executable).resolve() != expected_python:
    errors.append(f"unexpected interpreter: {sys.executable}")
if sys.version_info[:3] != (3, 13, 14):
    errors.append(f"unexpected Python version: {sys.version.split()[0]}")
if platform.machine() != "arm64":
    errors.append(f"unexpected architecture: {platform.machine()}")
for package, version in expected.items():
    try:
        actual = metadata.version(package)
    except metadata.PackageNotFoundError:
        actual = "missing"
    if actual != version:
        errors.append(f"{package}={actual}, expected {version}")
if not asset_root.is_dir() or not os.access(asset_root, os.W_OK):
    errors.append(f"asset root unavailable or not writable: {asset_root}")
else:
    free_bytes = shutil.disk_usage(asset_root).free
    if free_bytes < 30 * 1024**3:
        errors.append(f"insufficient free disk: {free_bytes} bytes")

if errors:
    raise SystemExit("ML environment check failed: " + "; ".join(errors))

print(f"ML_PYTHON={sys.executable}")
print(f"Python={sys.version.split()[0]}")
print(f"architecture={platform.machine()}")
print(f"asset_root={asset_root}")
print(f"free_disk_gib={shutil.disk_usage(asset_root).free / 1024**3:.1f}")
for package, version in expected.items():
    print(f"{package}={version}")
PY
