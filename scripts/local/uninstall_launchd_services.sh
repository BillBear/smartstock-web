#!/usr/bin/env bash
set -euo pipefail

LAUNCH_AGENTS_DIR="${SMARTSTOCK_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
elif [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: scripts/local/uninstall_launchd_services.sh [--dry-run]"
  exit 0
elif [[ $# -gt 0 ]]; then
  echo "Unknown option: $1" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "launchd services are only supported on macOS" >&2
  exit 1
fi

uid="$(id -u)"
for label in com.smartstock.frontend com.smartstock.backend com.smartstock.postgres; do
  plist="$LAUNCH_AGENTS_DIR/$label.plist"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "Would unload gui/$uid/$label and remove $plist"
    continue
  fi
  launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
  rm -f "$plist"
  echo "Removed $label"
done
