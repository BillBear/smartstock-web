#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$BASE_DIR/runtime"

BACKEND_PORT=8000
FRONTEND_PORT=3601
POSTGRES_PORT=5432
EXPECTED_DEPLOY_ROOT="${SMARTSTOCK_EXPECTED_DEPLOY_ROOT:-$BASE_DIR}"

git_value() {
  local label="$1"
  shift
  local value
  value="$(git -C "$BASE_DIR" "$@" 2>/dev/null || true)"
  echo "$label: ${value:-unknown}"
}

process_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

status_line() {
  local name="$1"
  local port="$2"
  local url="${3:-}"
  local pid

  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true)"
  if [ -n "$pid" ]; then
    local cwd
    cwd="$(process_cwd "$pid")"
    if [ -n "$url" ]; then
      echo "$name: running (pid=$pid, port=$port, $url)"
    else
      echo "$name: running (pid=$pid, port=$port)"
    fi
    echo "$name process cwd: ${cwd:-unknown}"
  else
    echo "$name: stopped"
  fi
}

echo "SmartStock status"
git_value "git branch" branch --show-current
git_value "git commit" rev-parse --short=12 HEAD
echo "Expected deploy root: $EXPECTED_DEPLOY_ROOT"

status_line "PostgreSQL" "$POSTGRES_PORT"
status_line "Backend" "$BACKEND_PORT" "http://localhost:$BACKEND_PORT"
status_line "Frontend" "$FRONTEND_PORT" "http://localhost:$FRONTEND_PORT"

if command -v curl >/dev/null 2>&1; then
  health="$(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/health" 2>/dev/null || true)"
  echo "Backend health: ${health:-unavailable}"
  version="$(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/api/system/version" 2>/dev/null || true)"
  if echo "$version" | grep -q '"Not Found"'; then
    echo "Runtime version: unavailable (running backend does not expose /api/system/version)"
  else
    echo "Runtime version: ${version:-unavailable}"
  fi
  picks="$(curl -sS --max-time 8 "http://localhost:$BACKEND_PORT/api/coach/picks/today?max_count=30&risk_level=medium&user_id=default&cached_only=true" 2>/dev/null || true)"
  if [ -n "$picks" ]; then
    candidate_summary="$(PICKS_JSON="$picks" python3 - <<'PY'
import json, os
try:
    payload = json.loads(os.environ.get("PICKS_JSON") or "{}").get("data") or {}
    meta = payload.get("universe_meta") or {}
    print(
        f"trade_date={payload.get('trade_date') or '-'} "
        f"picks={len(payload.get('picks') or [])} "
        f"total_universe={meta.get('total_universe_count', '-')}"
    )
except Exception:
    print("unavailable")
PY
)"
    echo "candidate pool: $candidate_summary"
  else
    echo "candidate pool: unavailable"
  fi
fi

if [ -d "$RUNTIME_DIR" ]; then
  echo "Runtime logs: $RUNTIME_DIR"
fi
