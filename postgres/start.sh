#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$SCRIPT_DIR"
DATA_DIR="$BASE_DIR/data"
LOG_FILE="$BASE_DIR/postgres.log"
PG_BIN_DIR="/opt/anaconda3/envs/smartstock-pg/bin"
POSTGRES_PORT=5432

export PATH="$PG_BIN_DIR:$PATH"

if [ ! -x "$PG_BIN_DIR/pg_ctl" ] || [ ! -x "$PG_BIN_DIR/psql" ]; then
  echo "PostgreSQL binaries not found in $PG_BIN_DIR"
  echo "Expected: pg_ctl, psql, initdb, createdb"
  exit 1
fi

if lsof -iTCP:"$POSTGRES_PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "PostgreSQL already running on 127.0.0.1:$POSTGRES_PORT"
  exit 0
fi

if [ ! -f "$DATA_DIR/PG_VERSION" ]; then
  initdb -D "$DATA_DIR" -U smartstock -A trust --encoding=UTF8 --locale=C
fi

pg_ctl -D "$DATA_DIR" -l "$LOG_FILE" -o "-h 127.0.0.1 -p $POSTGRES_PORT" start

for _ in $(seq 1 20); do
  if lsof -iTCP:"$POSTGRES_PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! lsof -iTCP:"$POSTGRES_PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "PostgreSQL failed to start. Check $LOG_FILE"
  tail -n 40 "$LOG_FILE" || true
  exit 1
fi

if ! psql -h 127.0.0.1 -p "$POSTGRES_PORT" -U smartstock -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='smartstock'" | grep -q 1; then
  createdb -h 127.0.0.1 -p "$POSTGRES_PORT" -U smartstock smartstock
fi

echo "PostgreSQL started on 127.0.0.1:$POSTGRES_PORT (db=smartstock, user=smartstock)"
