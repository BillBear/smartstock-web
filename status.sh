#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$BASE_DIR/runtime"

BACKEND_PORT=8000
FRONTEND_PORT=3601
POSTGRES_PORT=5432

status_line() {
  local name="$1"
  local port="$2"
  local url="${3:-}"
  local pid

  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true)"
  if [ -n "$pid" ]; then
    if [ -n "$url" ]; then
      echo "$name: running (pid=$pid, port=$port, $url)"
    else
      echo "$name: running (pid=$pid, port=$port)"
    fi
  else
    echo "$name: stopped"
  fi
}

status_line "PostgreSQL" "$POSTGRES_PORT"
status_line "Backend" "$BACKEND_PORT" "http://localhost:$BACKEND_PORT"
status_line "Frontend" "$FRONTEND_PORT" "http://localhost:$FRONTEND_PORT"

if [ -d "$RUNTIME_DIR" ]; then
  echo "Runtime logs: $RUNTIME_DIR"
fi
