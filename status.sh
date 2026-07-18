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

git_relation() {
  local head origin count
  head="$(git -C "$BASE_DIR" rev-parse HEAD 2>/dev/null || true)"
  origin="$(git -C "$BASE_DIR" rev-parse refs/remotes/origin/main 2>/dev/null || true)"
  if [ -z "$head" ] || [ -z "$origin" ]; then
    echo "git relation: unknown (missing HEAD or origin/main)"
  elif [ "$head" = "$origin" ]; then
    echo "git relation: in sync with origin/main"
  elif git -C "$BASE_DIR" merge-base --is-ancestor "$origin" "$head" 2>/dev/null; then
    count="$(git -C "$BASE_DIR" rev-list --count "$origin..$head" 2>/dev/null || echo "?")"
    echo "git relation: ahead of origin/main by $count commit(s)"
  elif git -C "$BASE_DIR" merge-base --is-ancestor "$head" "$origin" 2>/dev/null; then
    count="$(git -C "$BASE_DIR" rev-list --count "$head..$origin" 2>/dev/null || echo "?")"
    echo "git relation: behind origin/main by $count commit(s)"
  else
    echo "git relation: diverged from origin/main"
  fi
}

origin_main_relation_value() {
  local head origin count
  head="$(git -C "$BASE_DIR" rev-parse HEAD 2>/dev/null || true)"
  origin="$(git -C "$BASE_DIR" rev-parse refs/remotes/origin/main 2>/dev/null || true)"
  if [ -z "$head" ] || [ -z "$origin" ]; then
    echo "unknown"
  elif [ "$head" = "$origin" ]; then
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

stable_tag_line() {
  local stable
  stable="$(git -C "$BASE_DIR" tag --merged HEAD --list 'local-stable-*' --sort=-creatordate 2>/dev/null | head -n 1 || true)"
  if [ -n "$stable" ]; then
    local sha
    sha="$(git -C "$BASE_DIR" rev-list -n 1 "$stable" 2>/dev/null | cut -c1-12 || true)"
    echo "stable tag: $stable${sha:+ ($sha)}"
  else
    echo "stable tag: none reachable from HEAD"
  fi
}

workspace_dir() {
  if [[ "$BASE_DIR" == */.worktrees/* ]]; then
    cd "$BASE_DIR/../.." && pwd
  else
    cd "$BASE_DIR/.." && pwd
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
  echo "deploy_branch: $(git -C "$BASE_DIR" branch --show-current 2>/dev/null || echo unknown)"
  echo "deploy_commit: $(git -C "$BASE_DIR" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
  echo "origin_main_relation: $(origin_main_relation_value)"
  echo "research_contract_commit: $(git -C "$BASE_DIR" rev-parse --short=12 refs/heads/research/ml-platform-v1 2>/dev/null || echo unknown)"
  echo "latest_certified_dataset_id: $(latest_certified_dataset_id)"
  echo "latest_research_run_id: $(latest_research_run_id)"
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

secret_line() {
  local workspace env_file token_line
  workspace="$(workspace_dir)"
  env_file="${SMARTSTOCK_LOCAL_ENV_FILE:-$workspace/.local-secrets/smartstock.env}"
  if [ -L "$BASE_DIR/backend/.env" ]; then
    echo "backend env: symlink -> $(readlink "$BASE_DIR/backend/.env")"
  elif [ -f "$BASE_DIR/backend/.env" ]; then
    echo "backend env: regular file"
  else
    echo "backend env: missing"
  fi
  if [ ! -f "$env_file" ]; then
    echo "local secret file: missing ($env_file)"
    echo "TuShare token: not configured"
    return
  fi
  echo "local secret file: present ($env_file)"
  token_line="$(grep -E '^[[:space:]]*(export[[:space:]]+)?TUSHARE_TOKEN=' "$env_file" 2>/dev/null | tail -n 1 || true)"
  if [ -n "$token_line" ] && [[ ! "$token_line" =~ TUSHARE_TOKEN=[[:space:]]*$ ]]; then
    echo "TuShare token: configured"
  else
    echo "TuShare token: not configured"
  fi
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

launchd_line() {
  local label="$1"
  if [ "$(uname -s)" != "Darwin" ] || ! command -v launchctl >/dev/null 2>&1; then
    return
  fi
  local uid output state pid
  uid="$(id -u)"
  output="$(launchctl print "gui/$uid/$label" 2>/dev/null || true)"
  if [ -z "$output" ]; then
    echo "Launchd $label: not loaded"
    return
  fi
  state="$(printf '%s\n' "$output" | awk -F'= ' '/state =/ {print $2; exit}')"
  pid="$(printf '%s\n' "$output" | awk -F'= ' '/pid =/ {print $2; exit}')"
  echo "Launchd $label: loaded state=${state:-unknown} pid=${pid:-none}"
}

echo "SmartStock status"
git_value "git branch" branch --show-current
git_value "git commit" rev-parse --short=12 HEAD
git_relation
stable_tag_line
echo "Expected deploy root: $EXPECTED_DEPLOY_ROOT"
secret_line

MODEL_JSON=""

launchd_line "com.smartstock.postgres"
launchd_line "com.smartstock.backend"
launchd_line "com.smartstock.frontend"

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
  MODEL_JSON="$(curl -sS --max-time 3 "http://localhost:$BACKEND_PORT/api/coach/models/latest" 2>/dev/null || true)"
  picks="$(curl -sS --max-time 8 "http://localhost:$BACKEND_PORT/api/coach/picks/today?max_count=30&risk_level=medium&user_id=default&cached_only=true" 2>/dev/null || true)"
  if [ -n "$picks" ]; then
    candidate_summary="$(PICKS_JSON="$picks" python3 - <<'PY'
import json, os
try:
    payload = json.loads(os.environ.get("PICKS_JSON") or "{}").get("data") or {}
    meta = payload.get("universe_meta") or {}
    context = payload.get("calendar_context") or {}
    actions = context.get("actions") or {}
    print(
        f"trade_date={payload.get('trade_date') or '-'} "
        f"picks={len(payload.get('picks') or [])} "
        f"total_universe={meta.get('total_universe_count', '-')} "
        f"mode={context.get('mode') or '-'} "
        f"requested={context.get('requested_date') or '-'} "
        f"effective={context.get('effective_trade_date') or '-'} "
        f"can_refresh={actions.get('can_refresh')} "
        f"can_paper_buy={actions.get('can_paper_buy')}"
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

ml_identity_lines "$MODEL_JSON"

if [ -d "$RUNTIME_DIR" ]; then
  echo "Runtime logs: $RUNTIME_DIR"
fi
