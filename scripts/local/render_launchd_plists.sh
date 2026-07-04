#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TEMPLATE_DIR="$BASE_DIR/deployment/local/launchd"
OUT_DIR="${1:-$BASE_DIR/runtime/launchd}"

mkdir -p "$OUT_DIR"
if [[ "${SMARTSTOCK_RENDER_LAUNCHD_NO_LOG_DIR:-0}" != "1" ]]; then
  mkdir -p "$BASE_DIR/runtime/logs"
fi

for template in "$TEMPLATE_DIR"/*.plist.template; do
  name="$(basename "$template" .template)"
  sed "s#__SMARTSTOCK_HOME__#$BASE_DIR#g" "$template" > "$OUT_DIR/$name"
  echo "$OUT_DIR/$name"
done
