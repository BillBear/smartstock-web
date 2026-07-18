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

origin_main_relation_value() {
  local head origin count
  head="$(git -C "$BASE_DIR" rev-parse HEAD 2>/dev/null || true)"
  origin="$(git -C "$BASE_DIR" rev-parse refs/remotes/origin/main 2>/dev/null || true)"
  if [[ -z "$head" || -z "$origin" ]]; then
    echo "unknown"
  elif [[ "$head" == "$origin" ]]; then
    echo "in_sync"
  elif git -C "$BASE_DIR" merge-base --is-ancestor "$origin" "$head" 2>/dev/null; then
    count="$(git -C "$BASE_DIR" rev-list --count "$origin..$head" 2>/dev/null || echo "?")"
    echo "ahead_by_${count}"
  elif git -C "$BASE_DIR" merge-base --is-ancestor "$head" "$origin" 2>/dev/null; then
    count="$(git -C "$BASE_DIR" rev-list --count "$head..$origin" 2>/dev/null || echo "?")"
    echo "behind_by_${count}"
  else
    echo "diverged"
  fi
}

ml_asset_root() {
  local workspace
  workspace="$(workspace_dir)"
  echo "${ML_ASSET_ROOT:-$workspace/ml-assets}"
}

latest_certified_dataset_id() {
  local asset_root
  asset_root="$(ml_asset_root)"
  ML_ASSET_ROOT_VALUE="$asset_root" python3 - <<'PY'
import json
import os
from pathlib import Path

manifest = Path(os.environ["ML_ASSET_ROOT_VALUE"]) / "asset_manifest.json"
try:
    print(json.loads(manifest.read_text(encoding="utf-8")).get("dataset_id") or "unknown")
except Exception:
    print("unknown")
PY
}

latest_research_run_id() {
  local asset_root
  asset_root="$(ml_asset_root)"
  ML_ASSET_ROOT_VALUE="$asset_root" python3 - <<'PY'
import os
from pathlib import Path

runs = Path(os.environ["ML_ASSET_ROOT_VALUE"]) / "runs"
try:
    candidates = [item for item in runs.iterdir() if item.is_dir()]
    print(max(candidates, key=lambda item: item.stat().st_mtime).name if candidates else "unknown")
except Exception:
    print("unknown")
PY
}

ml_decision_gate_state() {
  if grep -q "_apply_ml_prediction_to_pick_values" "$BASE_DIR/backend/app/services/coach_service.py" 2>/dev/null; then
    echo "isolated"
  else
    echo "legacy"
  fi
}

ml_identity_lines() {
  local model_json="${1:-}"
  line "deploy_branch: $(git -C "$BASE_DIR" branch --show-current 2>/dev/null || echo unknown)"
  line "deploy_commit: $(git -C "$BASE_DIR" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  line "origin_main_relation: $(origin_main_relation_value)"
  line "research_contract_commit: $(git -C "$BASE_DIR" rev-parse --short=12 refs/heads/research/ml-platform-v1 2>/dev/null || echo unknown)"
  line "latest_certified_dataset_id: $(latest_certified_dataset_id)"
  line "latest_research_run_id: $(latest_research_run_id)"
  MODEL_JSON="$model_json" ML_DECISION_GATE_STATE="$(ml_decision_gate_state)" python3 - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("MODEL_JSON") or "{}")
    data = payload.get("data") or payload
    readiness = data.get("ml_readiness") or (data.get("metrics") or {}).get("ml_readiness") or {}
    if not data.get("available") and not data.get("model_id"):
        raise ValueError("model unavailable")
    ready = readiness.get("production_ml_ready") is True
    print(f"active_model_id: {data.get('model_id') or 'unknown'}")
    print(f"active_model_status: {readiness.get('status') or data.get('status') or 'unknown'}")
    if ready:
        decision_mode = "decision_enabled"
    elif os.environ.get("ML_DECISION_GATE_STATE") == "isolated":
        decision_mode = "shadow_only"
    else:
        decision_mode = "legacy_unisolated"
    print(f"active_model_decision_mode: {decision_mode}")
except Exception:
    print("active_model_id: unavailable")
    print("active_model_status: unavailable")
    print("active_model_decision_mode: unavailable")
PY
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

protected_path_status() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return
  fi
  case "$BASE_DIR" in
    "$HOME/Documents"/*|"$HOME/Desktop"/*|"$HOME/Downloads"/*)
      line "Launchd path warning: deploy root is under a macOS protected directory; launchd may need Full Disk Access or a non-protected repo path"
      ;;
  esac
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

check_launchd() {
  local label="$1"
  if [[ "$(uname -s)" != "Darwin" ]] || ! command -v launchctl >/dev/null 2>&1; then
    return
  fi
  local uid output state pid
  uid="$(id -u)"
  output="$(launchctl print "gui/$uid/$label" 2>/dev/null || true)"
  if [[ -z "$output" ]]; then
    line "Launchd $label: not loaded"
    return
  fi
  state="$(printf '%s\n' "$output" | awk -F'= ' '/state =/ {print $2; exit}')"
  pid="$(printf '%s\n' "$output" | awk -F'= ' '/pid =/ {print $2; exit}')"
  line "Launchd $label: loaded state=${state:-unknown} pid=${pid:-none}"
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
protected_path_status

check_launchd "com.smartstock.postgres"
check_launchd "com.smartstock.backend"
check_launchd "com.smartstock.frontend"

check_port "PostgreSQL" "$POSTGRES_PORT"
check_port "Backend" "$BACKEND_PORT"
check_port "Frontend" "$FRONTEND_PORT"

if [[ "$OFFLINE" == "1" ]]; then
  ml_identity_lines
  line "Offline mode: skipped HTTP and database probes"
  exit 0
fi

MODEL_JSON=""
if command -v curl >/dev/null 2>&1; then
  line "Backend health: $(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/health" 2>/dev/null || echo unavailable)"
  line "Runtime version: $(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/api/system/version" 2>/dev/null || echo unavailable)"
  MODEL_JSON="$(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/api/coach/models/latest" 2>/dev/null || true)"
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

ml_identity_lines "$MODEL_JSON"
