#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$BASE_DIR/runtime"
POSTGRES_DIR="$BASE_DIR/postgres"

BACKEND_PORT=8000
FRONTEND_PORT=3601
POSTGRES_PORT=5432
BACKEND_SESSION="smartstock-backend"
FRONTEND_SESSION="smartstock-frontend"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"

stop_screen_session() {
  local name="$1"
  if screen -ls 2>/dev/null | grep -q "[.]$name[[:space:]]"; then
    screen -S "$name" -X quit >/dev/null 2>&1 || true
    echo "$name screen session stopped"
  fi
}

stop_by_pid_file() {
  local pid_file="$1"
  local name="$2"

  if [ ! -f "$pid_file" ]; then
    return 1
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    echo "$name stopped (pid=$pid)"
  fi
  rm -f "$pid_file"
  return 0
}

stop_by_port() {
  local port="$1"
  local name="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return 1
  fi

  echo "$pids" | xargs kill >/dev/null 2>&1 || true
  echo "$name stopped (port=$port)"
  return 0
}

stop_screen_session "$BACKEND_SESSION"
stop_screen_session "$FRONTEND_SESSION"

stop_by_pid_file "$BACKEND_PID_FILE" "Backend" || stop_by_port "$BACKEND_PORT" "Backend" || echo "Backend not running"
stop_by_pid_file "$FRONTEND_PID_FILE" "Frontend" || stop_by_port "$FRONTEND_PORT" "Frontend" || echo "Frontend not running"

if lsof -iTCP:"$POSTGRES_PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  "$POSTGRES_DIR/stop.sh" >/dev/null 2>&1 || true
  echo "PostgreSQL stopped"
else
  echo "PostgreSQL not running"
fi
