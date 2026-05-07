#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "backend/start.sh is deprecated. Redirecting to project start.sh"
exec "$PROJECT_DIR/start.sh"
