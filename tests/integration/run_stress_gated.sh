#!/usr/bin/env bash
# Run one relay_transport_stress.py scenario and fail on a non-zero exit status OR on
# asyncio shutdown noise in its output (issues #137/#138). Expected fault-injection
# output (relay "Error client N ... BrokenPipeError", "socket.send() raised exception",
# transport "dropped malformed line") is intentionally not matched.
#   usage: bash tests/integration/run_stress_gated.sh <scenario> [--cycles N]
set -uo pipefail
log=$(mktemp)
python3 -X faulthandler tests/integration/relay_transport_stress.py "$@" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
noise='Task was destroyed but it is pending|exception was never retrieved|CancelledError|Event loop is closed|Exception in callback|Unhandled exception'
if grep -nE "$noise" "$log"; then
  echo "::error::asyncio shutdown noise in output of: $*"
  exit 1
fi
exit "$status"
