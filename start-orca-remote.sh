#!/usr/bin/env bash
set -euo pipefail

session_pid="$(pgrep -u "$USER" -n xfce4-session || true)"
if [[ -z "$session_pid" ]]; then
  echo "Could not find an active xfce4-session." >&2
  exit 1
fi

while IFS= read -r -d '' entry; do
  case "$entry" in
    DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_RUNTIME_DIR=*|XDG_SESSION_TYPE=*|WAYLAND_DISPLAY=*)
      export "$entry"
      ;;
  esac
done < "/proc/$session_pid/environ"

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "No graphical display found in the active XFCE session." >&2
  exit 1
fi

exec orca --replace
