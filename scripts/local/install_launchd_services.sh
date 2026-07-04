#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LAUNCH_AGENTS_DIR="${SMARTSTOCK_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
RUNTIME_DIR="$BASE_DIR/runtime"
LOG_DIR="$RUNTIME_DIR/logs"
RENDER_DIR="$RUNTIME_DIR/launchd"
DRY_RUN=0
NO_LOAD=0

usage() {
  cat <<'EOF'
Usage: scripts/local/install_launchd_services.sh [--dry-run] [--no-load]

Installs macOS user launchd services for the local SmartStock validation
environment. The generated services call repository-local scripts and keep
local-only paths outside business code.

Options:
  --dry-run   Render and validate planned files without writing or loading.
  --no-load   Write plist files but do not bootstrap them into launchd.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --no-load)
      NO_LOAD=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "launchd services are only supported on macOS" >&2
  exit 1
fi

if [[ "$DRY_RUN" == "1" ]]; then
  RENDER_DIR="$(mktemp -d "${TMPDIR:-/tmp}/smartstock-launchd.XXXXXX")"
  trap 'rm -rf "$RENDER_DIR"' EXIT
  SMARTSTOCK_RENDER_LAUNCHD_NO_LOG_DIR=1 "$BASE_DIR/scripts/local/render_launchd_plists.sh" "$RENDER_DIR" >/dev/null
else
  mkdir -p "$LOG_DIR"
  "$BASE_DIR/scripts/local/render_launchd_plists.sh" "$RENDER_DIR" >/dev/null
fi

for label in com.smartstock.postgres com.smartstock.backend com.smartstock.frontend; do
  source_plist="$RENDER_DIR/$label.plist"
  target_plist="$LAUNCH_AGENTS_DIR/$label.plist"
  plutil -lint "$source_plist" >/dev/null
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "Would write $target_plist"
    continue
  fi
  mkdir -p "$LAUNCH_AGENTS_DIR"
  cp "$source_plist" "$target_plist"
  echo "Installed $target_plist"
done

if [[ "$DRY_RUN" == "1" || "$NO_LOAD" == "1" ]]; then
  exit 0
fi

uid="$(id -u)"
for label in com.smartstock.postgres com.smartstock.backend com.smartstock.frontend; do
  plist="$LAUNCH_AGENTS_DIR/$label.plist"
  launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$uid" "$plist"
  launchctl enable "gui/$uid/$label"
  launchctl kickstart -k "gui/$uid/$label"
  echo "Loaded $label"
done
