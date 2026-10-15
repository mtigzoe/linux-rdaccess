"""Activate one visible, WM-managed window and verify the EWMH result.

The caller supplies visible candidate IDs and its existing bounded wait function.
Only public X11 properties and numeric IDs are included in diagnostics.
"""

from __future__ import annotations

import json
import re
import subprocess

ROOT_PROPERTIES = (
    "_NET_SUPPORTING_WM_CHECK",
    "_NET_SUPPORTED",
    "_NET_CLIENT_LIST",
    "_NET_ACTIVE_WINDOW",
)


def _properties(*arguments):
    result = subprocess.run(
        ["xprop", *arguments], capture_output=True, text=True, check=True, timeout=3
    )
    return {
        re.split(r"[(:=]", line, maxsplit=1)[0].strip(): line
        for line in result.stdout.splitlines()
    }


def _windows(properties, name):
    return [
        int(value, 16)
        for value in re.findall(r"0x[0-9a-fA-F]+", properties.get(name, ""))
    ]


def _window(properties, name):
    return next(iter(_windows(properties, name)), 0)


def activate_window(candidates, wait, label, *, diagnostic=None):
    """Send one activation after WM readiness; return its verified decimal ID.

    ``candidates()`` must return only visible IDs (for example, from xdotool
    search --onlyvisible). ``wait(predicate, label)`` owns the entire readiness
    and activation budget. Command failures remain fatal; requests are not
    repeated while waiting for the active-window property to change.
    """
    state = {
        "wm": 0,
        "wm_self": 0,
        "supports_activation": False,
        "managed": [],
        "visible_candidates": [],
        "target": 0,
        "active": 0,
        "activation_sent": False,
    }
    activation_stderr = ""

    def poll():
        nonlocal activation_stderr
        properties = _properties("-root", *ROOT_PROPERTIES)
        state["wm"] = _window(properties, "_NET_SUPPORTING_WM_CHECK")
        state["active"] = _window(properties, "_NET_ACTIVE_WINDOW")
        managed = _windows(properties, "_NET_CLIENT_LIST")
        state["managed"] = managed[:32]
        atoms = re.findall(r"_[A-Z][A-Z0-9_]*", properties.get("_NET_SUPPORTED", ""))
        state["supports_activation"] = "_NET_ACTIVE_WINDOW" in atoms
        state["wm_self"] = 0
        if not state["wm"] or not state["supports_activation"]:
            return None
        check = _properties("-id", str(state["wm"]), "_NET_SUPPORTING_WM_CHECK")
        state["wm_self"] = _window(check, "_NET_SUPPORTING_WM_CHECK")
        if state["wm_self"] != state["wm"]:
            return None
        if state["activation_sent"]:
            return (
                str(state["target"])
                if state["target"] in managed and state["active"] == state["target"]
                else None
            )
        visible = [
            int(str(value), 0) if str(value).startswith("0x") else int(value)
            for value in (candidates() or [])
        ]
        state["visible_candidates"] = visible[:32]
        target = next((value for value in reversed(visible) if value in managed), 0)
        if not target:
            return None
        state["target"] = target
        # Set before running the command: a failed/slow request is fatal, not
        # a reason for the caller's polling loop to send it again.
        state["activation_sent"] = True
        result = subprocess.run(
            ["xdotool", "windowactivate", str(target)],
            capture_output=True,
            text=True,
            check=True,
            timeout=3,
        )
        activation_stderr = result.stderr or ""
        return None

    def report(success, error=None):
        item = dict(state, success=success)
        if error is not None:
            item["error"] = type(error).__name__
        stderr = getattr(error, "stderr", None) or activation_stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if stderr:
            item["command_stderr"] = stderr[-1000:]
        if diagnostic is not None:
            diagnostic(item)
        else:
            print("X11_ACTIVATION " + json.dumps(item, sort_keys=True), flush=True)

    try:
        target = wait(poll, label)
    except Exception as error:
        report(False, error)
        raise
    report(True)
    return target
