#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
EXPECTED_DEPLOY_ROOT="${SMARTSTOCK_EXPECTED_DEPLOY_ROOT:-$BASE_DIR}"
BACKEND_PORT="${SMARTSTOCK_BACKEND_PORT:-8000}"
FRONTEND_PORT="${SMARTSTOCK_FRONTEND_PORT:-3601}"
POSTGRES_PORT="${SMARTSTOCK_POSTGRES_PORT:-5432}"
OFFLINE=0

if [[ "${1:-}" == "--offline" ]] || [[ "${SMARTSTOCK_DOCTOR_OFFLINE:-}" == "1" ]]; then
  OFFLINE=1
fi

line() {
  printf '%s\n' "$1"
}

workspace_dir() {
  if [[ "$BASE_DIR" == */.worktrees/* ]]; then
    cd "$BASE_DIR/../.." && pwd
  else
    cd "$BASE_DIR/.." && pwd
  fi
}

git_relation() {
  local head origin count
  head="$(git -C "$BASE_DIR" rev-parse HEAD 2>/dev/null || true)"
  origin="$(git -C "$BASE_DIR" rev-parse refs/remotes/origin/main 2>/dev/null || true)"
  if [[ -z "$head" || -z "$origin" ]]; then
    line "Git relation: unknown (missing HEAD or origin/main)"
    return
  fi
  if [[ "$head" == "$origin" ]]; then
    line "Git relation: in sync with origin/main"
  elif git -C "$BASE_DIR" merge-base --is-ancestor "$origin" "$head" 2>/dev/null; then
    count="$(git -C "$BASE_DIR" rev-list --count "$origin..$head" 2>/dev/null || echo "?")"
    line "Git relation: ahead of origin/main by $count commit(s)"
  elif git -C "$BASE_DIR" merge-base --is-ancestor "$head" "$origin" 2>/dev/null; then
    count="$(git -C "$BASE_DIR" rev-list --count "$head..$origin" 2>/dev/null || echo "?")"
    line "Git relation: behind origin/main by $count commit(s)"
  else
    line "Git relation: diverged from origin/main"
  fi
}

secret_status() {
  local workspace env_file token_line
  workspace="$(workspace_dir)"
  env_file="${SMARTSTOCK_LOCAL_ENV_FILE:-$workspace/.local-secrets/smartstock.env}"
  if [[ ! -f "$env_file" ]]; then
    line "Local secret file: missing ($env_file)"
    line "TuShare token: not configured"
    return
  fi
  line "Local secret file: present ($env_file)"
  token_line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?TUSHARE_TOKEN=' "$env_file" 2>/dev/null | tail -n 1 || true)"
  if [[ -n "$token_line" && ! "$token_line" =~ TUSHARE_TOKEN=[[:space:]]*$ ]]; then
    line "TuShare token: configured"
  else
    line "TuShare token: not configured"
  fi
}

check_port() {
  local label="$1"
  local port="$2"
  local pid
  pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null | head -n 1 || true)"
  if [[ -n "$pid" ]]; then
    local cwd
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
    line "$label: listening on $port (pid=$pid)"
    line "$label process cwd: ${cwd:-unknown}"
    if [[ -n "$cwd" && "$cwd" != "$EXPECTED_DEPLOY_ROOT"* ]]; then
      line "$label warning: process is not running from expected deploy root"
    fi
  else
    line "$label: not listening on $port"
  fi
}

line "SmartStock Doctor"
line "Expected deploy root: $EXPECTED_DEPLOY_ROOT"
line "Current script root: $BASE_DIR"
line "Git branch: $(git -C "$BASE_DIR" branch --show-current 2>/dev/null || echo unknown)"
line "Git commit: $(git -C "$BASE_DIR" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
git_relation

if [[ -L "$BASE_DIR/backend/.env" ]]; then
  line "Backend env: symlink -> $(readlink "$BASE_DIR/backend/.env")"
elif [[ -f "$BASE_DIR/backend/.env" ]]; then
  line "Backend env: regular file"
else
  line "Backend env: missing"
fi
secret_status

check_port "PostgreSQL" "$POSTGRES_PORT"
check_port "Backend" "$BACKEND_PORT"
check_port "Frontend" "$FRONTEND_PORT"

if [[ "$OFFLINE" == "1" ]]; then
  line "Offline mode: skipped HTTP and database probes"
  exit 0
fi

if command -v curl >/dev/null 2>&1; then
  line "Backend health: $(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/health" 2>/dev/null || echo unavailable)"
  line "Runtime version: $(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/api/system/version" 2>/dev/null || echo unavailable)"
  picks="$(curl -sS --max-time 8 "http://localhost:$BACKEND_PORT/api/coach/picks/today?max_count=30&risk_level=medium&user_id=default&cached_only=true" 2>/dev/null || true)"
  if [[ -n "$picks" ]]; then
    PICK_PAYLOAD="$picks" python3 - <<'PY'
import json, os
payload = json.loads(os.environ.get("PICK_PAYLOAD") or "{}").get("data") or {}
meta = payload.get("universe_meta") or {}
total = int(meta.get("total_universe_count") or 0)
print(f"Candidate pool: trade_date={payload.get('trade_date') or '-'} picks={len(payload.get('picks') or [])} total_universe={total}")
if total and total < 5000:
    print("Candidate pool warning: total_universe below 5000")
PY
  else
    line "Candidate pool: unavailable"
  fi
fi
