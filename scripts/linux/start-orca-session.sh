#!/usr/bin/env bash
set -euo pipefail

# Use this user's newest XFCE session, never another user's (xrdp can host
# several users at once, and /proc/<pid>/environ of theirs is unreadable).
uid="$(id -u)"
proc_root="${LINUX_RDACCESS_PROC_ROOT:-/proc}"

pid="$(pgrep -u "$uid" -n xfce4-session || true)"
if [[ -z "$pid" ]]; then
    echo "No XFCE graphical session found."
    exit 1
fi

echo "Using XFCE session PID: $pid"

env_file="$proc_root/$pid/environ"
if [[ ! -r "$env_file" ]]; then
    echo "Cannot read the environment of XFCE session PID $pid."
    exit 1
fi

# environ entries are NUL separated and may contain newlines; splitting on
# newlines would let one variable's value forge another variable.
# Use the selected desktop's complete environment, without SSH forwarding or
# stale session variables from the shell that launched this helper.
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR XDG_SESSION_TYPE
while IFS= read -r -d '' line || [[ -n "$line" ]]; do
    case "$line" in
        DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_RUNTIME_DIR=*|WAYLAND_DISPLAY=*|XDG_SESSION_TYPE=*)
            export "$line"
            ;;
    esac
done < "$env_file"

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "No graphical display found in the active XFCE session." >&2
    exit 1
fi

echo "DISPLAY=${DISPLAY:-not set}"
echo "XAUTHORITY=${XAUTHORITY:-not set}"
echo "DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-not set}"
echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-not set}"
if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    echo "WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
fi

# A private log directory: a predictable file in a shared /tmp can be replaced
# by another user's symlink, which the redirection below would then follow.
log_dir="${XDG_STATE_HOME:-$HOME/.local/state}/linux-rdaccess"
mkdir -p "$log_dir"
chmod 700 "$log_dir"
log_file="$log_dir/orca.log"
echo "Starting Orca..."
# Detach Orca from this shell so closing the terminal does not stop it.
if command -v setsid >/dev/null 2>&1; then
    setsid orca --replace >"$log_file" 2>&1 </dev/null &
else
    nohup orca --replace >"$log_file" 2>&1 </dev/null &
fi

sleep "${LINUX_RDACCESS_ORCA_WAIT:-2}"

if pgrep -u "$uid" -a orca >/dev/null; then
    pgrep -u "$uid" -a orca
    echo "Orca is running."
else
    echo "Orca did not start. Log:"
    cat "$log_file"
    exit 1
fi
