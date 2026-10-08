#!/usr/bin/env bash
set -euo pipefail

# $USER is not always set (non-login shells, services); the numeric uid is.
proc_root="${LINUX_RDACCESS_PROC_ROOT:-/proc}"
session_pid="$(pgrep -u "$(id -u)" -n xfce4-session || true)"
if [[ -z "$session_pid" ]]; then
  echo "Could not find an active xfce4-session." >&2
  exit 1
fi

# Do not mix SSH forwarding or stale shell variables into the desktop session.
unset DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR XDG_SESSION_TYPE
while IFS= read -r -d '' entry || [[ -n "$entry" ]]; do
  case "$entry" in
    DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_RUNTIME_DIR=*|XDG_SESSION_TYPE=*|WAYLAND_DISPLAY=*)
      export "$entry"
      ;;
  esac
done < "$proc_root/$session_pid/environ"

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo "No graphical display found in the active XFCE session." >&2
  exit 1
fi

exec orca --replace
