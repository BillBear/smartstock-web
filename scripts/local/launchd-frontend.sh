#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$BASE_DIR/frontend"
BACKEND_PORT="${SMARTSTOCK_BACKEND_PORT:-8000}"
FRONTEND_PORT="${SMARTSTOCK_FRONTEND_PORT:-3601}"

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

wait_for_port "$BACKEND_PORT" 120

cd "$FRONTEND_DIR"
exec npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
