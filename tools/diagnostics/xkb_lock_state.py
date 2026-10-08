#!/usr/bin/env python3
"""Print the X11 (XKB) Caps Lock / Num Lock state of the Linux session.

Read-only diagnostic for telling two failures apart when Windows NVDA says
nothing after Num Lock is pressed in a remote session:

  1. Linux Num Lock DID change (this tool flips between on/off) but nothing was
     announced: a speech/announcement path problem.
  2. Linux Num Lock never changed: a key injection / key-mapping problem.

Run it inside the Linux graphical session (it needs DISPLAY):

    python3 tools/xkb_lock_state.py            # print once
    python3 tools/xkb_lock_state.py --watch    # print on every change, Ctrl+C to stop

It never injects keys and never logs anything but lock state.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import sys
import time

XKB_USE_CORE_KBD = 0x0100
MOD_LOCK = 0x02   # Caps Lock
MOD_2 = 0x10      # Num Lock in the standard X keymaps


def decode_locked_mods(locked_mods: int) -> dict:
    """Decode XKB locked modifiers. Num Lock is Mod2 in standard keymaps."""
    return {"caps_lock": bool(locked_mods & MOD_LOCK),
            "num_lock": bool(locked_mods & MOD_2)}


def format_state(state: dict) -> str:
    return "Caps Lock: %s  Num Lock: %s" % (
        "on" if state["caps_lock"] else "off",
        "on" if state["num_lock"] else "off")


class _XkbState(ctypes.Structure):
    _fields_ = [
        ("group", ctypes.c_ubyte), ("locked_group", ctypes.c_ubyte),
        ("base_group", ctypes.c_ushort), ("latched_group", ctypes.c_ushort),
        ("mods", ctypes.c_ubyte), ("base_mods", ctypes.c_ubyte),
        ("latched_mods", ctypes.c_ubyte), ("locked_mods", ctypes.c_ubyte),
        ("compat_state", ctypes.c_ubyte), ("grab_mods", ctypes.c_ubyte),
        ("compat_grab_mods", ctypes.c_ubyte), ("lookup_mods", ctypes.c_ubyte),
        ("compat_lookup_mods", ctypes.c_ubyte), ("ptr_buttons", ctypes.c_ushort),
    ]


def read_state() -> dict:
    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    dpy = x11.XOpenDisplay(None)
    if not dpy:
        raise OSError("cannot open X display (is DISPLAY set? X11 only)")
    try:
        state = _XkbState()
        if x11.XkbGetState(dpy, XKB_USE_CORE_KBD, ctypes.byref(state)) != 0:
            raise OSError("XkbGetState failed")
        return decode_locked_mods(state.locked_mods)
    finally:
        x11.XCloseDisplay(dpy)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watch", action="store_true",
                        help="keep running and print whenever the state changes")
    args = parser.parse_args(argv)
    try:
        last = read_state()
        print(format_state(last), flush=True)
        while args.watch:
            time.sleep(0.1)
            now = read_state()
            if now != last:
                print(format_state(now), flush=True)
                last = now
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
