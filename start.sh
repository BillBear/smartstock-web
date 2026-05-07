#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$BASE_DIR/backend"
FRONTEND_DIR="$BASE_DIR/frontend"
POSTGRES_DIR="$BASE_DIR/postgres"
RUNTIME_DIR="$BASE_DIR/runtime"

BACKEND_PORT=8000
FRONTEND_PORT=3601
POSTGRES_PORT=5432
BACKEND_SESSION="smartstock-backend"
FRONTEND_SESSION="smartstock-frontend"

mkdir -p "$RUNTIME_DIR"

is_listening() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

wait_for_port() {
  local port="$1"
  local retries="${2:-60}"

  for _ in $(seq 1 "$retries"); do
    if is_listening "$port"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

has_screen_session() {
  local name="$1"
  screen -ls 2>/dev/null | grep -q "[.]$name[[:space:]]"
}

start_postgres() {
  if is_listening "$POSTGRES_PORT"; then
    echo "PostgreSQL already running on 127.0.0.1:$POSTGRES_PORT"
    return
  fi

  echo "Starting PostgreSQL..."
  "$POSTGRES_DIR/start.sh"
  wait_for_port "$POSTGRES_PORT" 40 || {
    echo "PostgreSQL failed to start. Check $POSTGRES_DIR/postgres.log"
    exit 1
  }
}

start_backend() {
  if is_listening "$BACKEND_PORT"; then
    echo "Backend already running on http://localhost:$BACKEND_PORT"
    return
  fi

  if has_screen_session "$BACKEND_SESSION"; then
    screen -S "$BACKEND_SESSION" -X quit >/dev/null 2>&1 || true
  fi

  echo "Starting backend on port $BACKEND_PORT..."
  screen -dmS "$BACKEND_SESSION" zsh -lc "cd '$BACKEND_DIR' && source venv/bin/activate && exec uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT"

  wait_for_port "$BACKEND_PORT" 80 || {
    echo "Backend failed to start. Inspect: screen -r $BACKEND_SESSION"
    exit 1
  }
  echo "Backend is ready on http://localhost:$BACKEND_PORT"
}

start_frontend() {
  if is_listening "$FRONTEND_PORT"; then
    echo "Frontend already running on http://localhost:$FRONTEND_PORT"
    return
  fi

  if has_screen_session "$FRONTEND_SESSION"; then
    screen -S "$FRONTEND_SESSION" -X quit >/dev/null 2>&1 || true
  fi

  echo "Starting frontend on port $FRONTEND_PORT..."
  screen -dmS "$FRONTEND_SESSION" zsh -lc "cd '$FRONTEND_DIR' && exec npm run dev -- --host 0.0.0.0 --port $FRONTEND_PORT"

  wait_for_port "$FRONTEND_PORT" 80 || {
    echo "Frontend failed to start. Inspect: screen -r $FRONTEND_SESSION"
    exit 1
  }
  echo "Frontend is ready on http://localhost:$FRONTEND_PORT"
}

start_postgres
start_backend
start_frontend

echo
echo "SmartStock started successfully"
echo "Frontend: http://localhost:$FRONTEND_PORT"
echo "Backend:  http://localhost:$BACKEND_PORT"
echo "Sessions: screen -ls"
