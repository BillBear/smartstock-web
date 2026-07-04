#!/usr/bin/env bash
set -euo pipefail

ROOT="${SMARTSTOCK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

BACKEND="$ROOT/backend"
if [[ -n "${SMARTSTOCK_PY:-}" ]]; then
  PY="$SMARTSTOCK_PY"
elif [[ -x "$BACKEND/venv/bin/python" ]]; then
  PY="$BACKEND/venv/bin/python"
else
  PY="/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python"
fi
RUN_ROOT="$ROOT/runtime/ml_runs/local_core_v1"
LOG_DIR="$ROOT/runtime/logs"
TRAIN_END="${1:-$(date +%Y-%m-%d)}"

mkdir -p "$RUN_ROOT" "$LOG_DIR"

cd "$BACKEND"

echo "[1/5] Installing local ML dependencies"
"$PY" -m pip install -r requirements-ml-local.txt

echo "[2/5] Running environment preflight"
"$PY" scripts/check_local_ml_environment.py \
  --output-root "$RUN_ROOT/preflight" \
  --history-smoke-symbols 002415,600519,300750

echo "[3/5] Running 100-symbol pilot"
"$PY" scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 Pilot - 100 symbols" \
  --train-start 2025-01-01 \
  --train-end "$TRAIN_END" \
  --target-valid-symbols 100 \
  --oversample-symbols 130 \
  --min-formal-model-symbols 100 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root "$RUN_ROOT/pilot"

echo "[4/5] Running formal 700-symbol training"
"$PY" scripts/run_local_ml_experiment.py \
  --model-family local_core_v1 \
  --model-display-name "Local Core ML v1 - 700 symbols" \
  --train-start 2025-01-01 \
  --train-end "$TRAIN_END" \
  --target-valid-symbols 700 \
  --oversample-symbols 760 \
  --min-formal-model-symbols 700 \
  --sample-step 2 \
  --primary-horizon 10 \
  --exclude-news-features \
  --exclude-market-state-features \
  --output-root "$RUN_ROOT/formal"

echo "[5/5] Completed local_core_v1 overnight run"
find "$RUN_ROOT" -maxdepth 4 -name "post_run_review.md" -print
