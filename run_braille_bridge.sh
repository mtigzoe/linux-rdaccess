#!/usr/bin/env bash
# Backward-compatible entry point. Implementation: scripts/linux/run_braille_bridge.sh
set -euo pipefail
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$root_dir/scripts/linux/run_braille_bridge.sh" "$@"
