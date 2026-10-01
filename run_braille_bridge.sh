#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DISPLAY:-}" ]]; then
  echo "DISPLAY is not set. Run this inside the xrdp desktop session, for example DISPLAY=:10." >&2
  exit 2
fi

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
fi

if [[ -z "${AT_SPI_BUS_ADDRESS:-}" ]]; then
  raw="$(gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus --method org.a11y.Bus.GetAddress)"
  AT_SPI_BUS_ADDRESS="$(python3 -c 'import ast,sys; print(ast.literal_eval(sys.stdin.read())[0])' <<<"$raw")"
  export AT_SPI_BUS_ADDRESS
fi

xprop -root -f AT_SPI_BUS 8s -set AT_SPI_BUS "$AT_SPI_BUS_ADDRESS"

exec python3 atspi_nvda_braille_bridge.py "$@"
