#!/usr/bin/env bash
# Start the AT-SPI -> NVDA speech+braille bridge inside an xrdp desktop session.
#
#   DISPLAY=:10 ./run_braille_bridge.sh [--debug] [bridge options]
#   DISPLAY=:10 ./run_braille_bridge.sh --check     # print the environment facts and exit
#
# The AT-SPI bus address is always asked from the live session bus. An inherited
# AT_SPI_BUS_ADDRESS is only a fallback, because after an xrdp reconnect or an
# at-spi-bus-launcher restart an old value points at a bus that no longer exists:
# libatspi then aborts the bridge (dbind-ERROR, SIGTRAP), and the stale address would
# also be published on the X root window, so every newly started application would
# fail to register with AT-SPI.
set -euo pipefail

check_only=0
args=()
for arg in "$@"; do
  if [[ "$arg" == "--check" ]]; then check_only=1; else args+=("$arg"); fi
done

if [[ -z "${DISPLAY:-}" ]]; then
  echo "DISPLAY is not set. Run this inside the xrdp desktop session, for example DISPLAY=:10." >&2
  exit 2
fi

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
fi

live_address=""
if raw="$(gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
    --method org.a11y.Bus.GetAddress 2>/dev/null)"; then
  live_address="$(python3 -c 'import ast,sys; print(ast.literal_eval(sys.stdin.read())[0])' <<<"$raw" 2>/dev/null || true)"
fi

if [[ -n "$live_address" ]]; then
  if [[ -n "${AT_SPI_BUS_ADDRESS:-}" && "$AT_SPI_BUS_ADDRESS" != "$live_address" ]]; then
    echo "warning: ignoring stale AT_SPI_BUS_ADDRESS from the environment" >&2
  fi
  export AT_SPI_BUS_ADDRESS="$live_address"
elif [[ -n "${AT_SPI_BUS_ADDRESS:-}" ]]; then
  echo "warning: could not query org.a11y.Bus on DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS;" \
       "using AT_SPI_BUS_ADDRESS from the environment" >&2
else
  echo "error: cannot find the AT-SPI bus. Is DBUS_SESSION_BUS_ADDRESS the xrdp session's bus?" >&2
  echo "       DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS" >&2
  exit 3
fi

xprop -root -f AT_SPI_BUS 8s -set AT_SPI_BUS "$AT_SPI_BUS_ADDRESS"
published="$(xprop -root AT_SPI_BUS 2>/dev/null | sed -n 's/^AT_SPI_BUS(STRING) = "\(.*\)"$/\1/p')"
if [[ "$published" != "$AT_SPI_BUS_ADDRESS" ]]; then
  echo "error: AT_SPI_BUS on the X root window of $DISPLAY is '$published', expected '$AT_SPI_BUS_ADDRESS'" >&2
  exit 4
fi

echo "DISPLAY=$DISPLAY"
echo "DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS"
echo "AT_SPI_BUS_ADDRESS=$AT_SPI_BUS_ADDRESS (X root AT_SPI_BUS matches)"

if [[ "$check_only" == 1 ]]; then
  exit 0
fi

exec python3 atspi_nvda_braille_bridge.py "${args[@]}"
