#!/usr/bin/env bash
set -euo pipefail

AGENT_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$UID"

for label in com.smartstock.frontend com.smartstock.backend com.smartstock.postgres; do
  target="$AGENT_DIR/$label.plist"
  launchctl bootout "$DOMAIN" "$target" >/dev/null 2>&1 || true
  rm -f "$target"
  echo "removed $label"
done
