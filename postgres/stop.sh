#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
PG_BIN_DIR="/opt/anaconda3/envs/smartstock-pg/bin"
POSTGRES_PORT=5432

export PATH="$PG_BIN_DIR:$PATH"

if [ ! -x "$PG_BIN_DIR/pg_ctl" ]; then
  echo "pg_ctl not found in $PG_BIN_DIR"
  exit 1
fi

if ! lsof -iTCP:"$POSTGRES_PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "PostgreSQL not running"
  exit 0
fi

pg_ctl -D "$DATA_DIR" stop

echo "PostgreSQL stopped"
