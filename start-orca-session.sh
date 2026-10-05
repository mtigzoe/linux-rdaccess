#!/usr/bin/env bash
set -euo pipefail

pid="$(pgrep -n xfce4-session || true)"
if [[ -z "$pid" ]]; then
    echo "No XFCE graphical session found."
    exit 1
fi

echo "Using XFCE session PID: $pid"

while IFS= read -r line; do
    case "$line" in
        DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_RUNTIME_DIR=*|WAYLAND_DISPLAY=*)
            export "$line"
            ;;
    esac
done < <(tr '\0' '\n' < "/proc/$pid/environ")

echo "DISPLAY=${DISPLAY:-not set}"
echo "XAUTHORITY=${XAUTHORITY:-not set}"
echo "DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-not set}"
echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-not set}"
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    echo "WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
fi

log_file="${TMPDIR:-/tmp}/linux-rdaccess-orca.log"
echo "Starting Orca..."
orca --replace >"$log_file" 2>&1 &

sleep 2

if pgrep -a orca >/dev/null; then
    pgrep -a orca
    echo "Orca is running."
else
    echo "Orca did not start. Log:"
    cat "$log_file"
    exit 1
fi
