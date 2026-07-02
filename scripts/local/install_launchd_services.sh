#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$BASE_DIR/runtime/launchd"
AGENT_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$UID"

"$BASE_DIR/scripts/local/render_launchd_plists.sh" "$OUT_DIR" >/dev/null
mkdir -p "$AGENT_DIR"

for plist in "$OUT_DIR"/com.smartstock.*.plist; do
  label="$(basename "$plist" .plist)"
  target="$AGENT_DIR/$(basename "$plist")"
  cp "$plist" "$target"
  launchctl bootout "$DOMAIN" "$target" >/dev/null 2>&1 || true
  launchctl bootstrap "$DOMAIN" "$target"
  launchctl enable "$DOMAIN/$label" >/dev/null 2>&1 || true
  echo "installed $label -> $target"
done

echo "SmartStock launchd services installed. Use launchctl print $DOMAIN/com.smartstock.backend to inspect."
