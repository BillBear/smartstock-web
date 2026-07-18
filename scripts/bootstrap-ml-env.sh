#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(basename "$(dirname "$REPO_ROOT")")" == ".worktrees" ]]; then
  WORKSPACE_ROOT="$(cd "$REPO_ROOT/../.." && pwd)"
else
  WORKSPACE_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
fi
HOMEBREW_PYTHON="${HOMEBREW_PYTHON_313:-/opt/homebrew/opt/python@3.13/bin/python3.13}"
ML_VENV_ROOT="$WORKSPACE_ROOT/.venvs/ml-py313"
LOCK_FILE="$REPO_ROOT/backend/requirements-ml-lock.txt"

if [[ ! -x "$HOMEBREW_PYTHON" ]]; then
  echo "Homebrew Python 3.13.14 is required at $HOMEBREW_PYTHON" >&2
  exit 2
fi
if [[ ! -f "$LOCK_FILE" ]]; then
  echo "Missing ML lock file: $LOCK_FILE" >&2
  exit 2
fi

PYTHON_VERSION="$($HOMEBREW_PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if [[ "$PYTHON_VERSION" != "3.13.14" ]]; then
  echo "Expected Python 3.13.14, found $PYTHON_VERSION" >&2
  exit 2
fi

if [[ ! -x "$ML_VENV_ROOT/bin/python" ]]; then
  "$HOMEBREW_PYTHON" -m venv "$ML_VENV_ROOT"
fi

"$ML_VENV_ROOT/bin/python" -m pip install --upgrade pip
"$ML_VENV_ROOT/bin/python" -m pip install --requirement "$LOCK_FILE"
ML_PYTHON="$ML_VENV_ROOT/bin/python" ML_ASSET_ROOT="${ML_ASSET_ROOT:-$WORKSPACE_ROOT/ml-assets}" \
  "$REPO_ROOT/scripts/check-ml-env.sh"
