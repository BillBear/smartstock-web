#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

"$BASE_DIR/stop.sh"
sleep 1
"$BASE_DIR/start.sh"
