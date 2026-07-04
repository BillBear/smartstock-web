#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$BASE_DIR/backend"
RUNTIME_DIR="$BASE_DIR/runtime"
POSTGRES_PORT="${SMARTSTOCK_POSTGRES_PORT:-5432}"
BACKEND_PORT="${SMARTSTOCK_BACKEND_PORT:-8000}"

mkdir -p "$RUNTIME_DIR/logs"

workspace_dir() {
  if [[ "$BASE_DIR" == */.worktrees/* ]]; then
    cd "$BASE_DIR/../.." && pwd
  else
    cd "$BASE_DIR/.." && pwd
  fi
}

load_local_env() {
  local workspace env_file
  workspace="$(workspace_dir)"
  env_file="${SMARTSTOCK_LOCAL_ENV_FILE:-$workspace/.local-secrets/smartstock.env}"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}

wait_for_port() {
  local port="$1"
  local retries="${2:-120}"
  for _ in $(seq 1 "$retries"); do
    if lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

load_local_env
wait_for_port "$POSTGRES_PORT" 120

cd "$BACKEND_DIR"
source venv/bin/activate
exec uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
