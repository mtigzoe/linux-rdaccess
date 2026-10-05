#!/usr/bin/env python3
"""Bounded, private diagnostics for an existing local X11 desktop.

No text injection, keyboard listeners, speech capture, or clipboard access.
Names are available to in-memory callers; CLI reports always redact them.
"""
from __future__ import annotations

import argparse
import ast
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOCKS = ("Num Lock", "Caps Lock", "Scroll Lock")
TARGETS = {"thunar": "^Thunar$", "firefox": "^[Ff]irefox.*$"}
KEYS = {name: (name,) for name in (
    "Tab", "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
    "Escape", "Return", "Num_Lock", "Caps_Lock", "Scroll_Lock", "Control_L",
)}
KEYS["Shift+Tab"] = ("Shift_L", "Tab")


class DiagnosticError(Exception):
    """Fixed messages only: never include subprocess, input, or AT-SPI text."""


class Xkb:
    def __init__(self, display: str):
        self.lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        signatures = {
            "XOpenDisplay": ([ctypes.c_char_p], ctypes.c_void_p),
            "XCloseDisplay": ([ctypes.c_void_p], ctypes.c_int),
            "XInternAtom": ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_ulong),
            "XkbGetIndicatorState": ([ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.POINTER(ctypes.c_uint)], ctypes.c_int),
            "XkbGetNamedIndicator": ([ctypes.c_void_p, ctypes.c_ulong,
                                      ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                      ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        self.display = self.lib.XOpenDisplay(display.encode("ascii"))
        if not self.display:
            raise DiagnosticError("X11 display unavailable")

    def snapshot(self) -> dict:
        mask = ctypes.c_uint()
        if self.lib.XkbGetIndicatorState(self.display, 0x100, ctypes.byref(mask)) != 0:
            raise DiagnosticError("XKB indicator query failed")
        result = {"indicator_mask": mask.value}
        for name in LOCKS:
            atom = self.lib.XInternAtom(self.display, name.encode("ascii"), 1)
            index, on, real = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
            available = bool(atom and self.lib.XkbGetNamedIndicator(
                self.display, atom, ctypes.byref(index), ctypes.byref(on), None,
                ctypes.byref(real)))
            result[name] = {"available": available, "on": bool(on.value) if available else None,
                            "index": index.value if available else None,
                            "physical_indicator": bool(real.value) if available else None}
        return result

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None


def command(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        raise DiagnosticError("X11 command unavailable or timed out") from None
    if result.returncode:
        raise DiagnosticError("X11 command failed")
    return result.stdout


def target_windows(target: str) -> list[dict]:
    if target not in TARGETS:
        raise DiagnosticError("Unsupported application")
    ids = command(["xdotool", "search", "--onlyvisible", "--class", TARGETS[target]])
    result = []
    for raw in ids.splitlines()[:100]:
        if not raw.isdecimal():
            continue
        pid_text = command(["xdotool", "getwindowpid", raw]).strip()
        if not pid_text.isdecimal():
            continue
        pid = int(pid_text)
        try:
            if Path(f"/proc/{pid}").stat().st_uid != os.getuid():
                continue
        except OSError:
            continue
        result.append({"window_id": int(raw), "pid": pid})
    return result


class Focus:
    def __init__(self):
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib
        self.atspi, self.glib = Atspi, GLib
        Atspi.set_timeout(500, 1500)

    def read(self, pid: int | None = None):
        """Read focus and its name in memory, with bounded tree traversal.

        Names may contain private application data. Never serialize this object;
        use public() for output. Password names are never queried.
        """
        desktop = self.atspi.get_desktop(0)
        queue = [desktop]
        visited = 0
        deadline = time.monotonic() + 1.5
        def children(obj, limit):
            for index in range(min(obj.get_child_count(), limit)):
                if time.monotonic() >= deadline:
                    break
                child = obj.get_child_at_index(index)
                if child is not None:
                    queue.append(child)
        while queue and visited < 2000 and time.monotonic() < deadline:
            obj = queue.pop()
            visited += 1
            try:
                if obj == desktop:
                    children(obj, 100)
                    continue
                if obj.get_role() == self.atspi.Role.APPLICATION and pid is not None:
                    if obj.get_process_id() != pid:
                        continue
                states = obj.get_state_set()
                if states.contains(self.atspi.StateType.FOCUSED):
                    role = obj.get_role()
                    name = None if role == self.atspi.Role.PASSWORD_TEXT else obj.get_name()
                    return {"object": obj, "name": name, "role": role.value_nick,
                            "states": sorted(state.value_nick for state in states.get_states())}
                children(obj, 200)
            except Exception:
                continue
        return None

    @staticmethod
    def public(snapshot):
        if snapshot is None:
            return {"found": False}
        return {"found": True, "name": "[redacted]", "name_present": bool(snapshot["name"]),
                "role": snapshot["role"], "states": snapshot["states"]}

    def changed(self, previous, current) -> bool:
        return bool(current and (not previous or current["object"] != previous["object"]))

    def pump(self):
        context = self.glib.MainContext.default()
        for _ in range(20):
            if not context.pending():
                break
            context.iteration(False)


def injection_backend():
    """Reuse production XTest and transactional ownership, without Orca hooks."""
    import remote_access
    tree = ast.parse(remote_access._XTEST_HELPER)
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
             and node.name in ("_LrdXTest", "_lrd_wrap_local_key_results")]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<production-XTest>", "exec"), namespace)
    helper = namespace["_LrdXTest"]()
    namespace["_LRD_XTEST"] = helper

    class Backend:
        @staticmethod
        def _resolve_key(key_name, vk_code, extended):
            return key_name

        def send_key(self, key_name=None, pressed=None, vk_code=None, extended=None):
            return helper.key(key_name, pressed)

        def key(self, name, pressed):
            return self.send_key(key_name=name, pressed=pressed)

        def __getattr__(self, name):
            return getattr(helper, name)

        def close(self):
            if helper._dpy and not helper._down_codes:
                helper._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
                helper._x11.XCloseDisplay(helper._dpy)
                helper._dpy = None

    Backend.send_key = namespace["_lrd_wrap_local_key_results"](Backend.send_key)
    return Backend()


def require_released(backend, key: str):
    """Do not borrow a physical/remote key which was already held down."""
    if backend._dpy is None:
        backend._open()
    query = backend._x11.XQueryKeymap
    query.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    query.restype = ctypes.c_int
    bits = ctypes.create_string_buffer(32)
    query(backend._dpy, bits)
    names = KEYS[key] + ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                         "Super_L", "Super_R", "Insert", "KP_Insert", "Caps_Lock")
    for name in names:
        sym = backend._x11.XStringToKeysym(name.encode("ascii"))
        code = backend._x11.XKeysymToKeycode(backend._dpy, sym) if sym else 0
        if code and bits.raw[code // 8] & (1 << (code % 8)):
            raise DiagnosticError("Test input or modifier already held; retry when released")


def inject(backend, key: str):
    if key not in KEYS:
        raise DiagnosticError("Unsupported test input")
    held = []
    failed = False
    try:
        for name in KEYS[key]:
            if not backend.key(name, True):
                raise DiagnosticError("Test injection failed")
            held.append(name)
    finally:
        for name in reversed(held):
            try:
                if not backend.key(name, False):
                    # Try the same owned release once more, never a second backend.
                    if not backend.key(name, False):
                        failed = True
            except Exception:
                failed = True
        if failed:
            raise DiagnosticError("Test release failed")


def exercise(window: dict, key: str, focus: Focus, backend, timeout: float):
    if key not in KEYS:
        raise DiagnosticError("Unsupported test input")
    if int(command(["xdotool", "getactivewindow"]).strip()) != window["window_id"]:
        raise DiagnosticError("Target window is not active")
    before = focus.read(window["pid"])
    require_released(backend, key)
    if int(command(["xdotool", "getactivewindow"]).strip()) != window["window_id"]:
        raise DiagnosticError("Target window is not active")
    started = time.monotonic()
    inject(backend, key)
    input_ms = (time.monotonic() - started) * 1000
    deadline = started + timeout
    after = before
    changed_ms = None
    while time.monotonic() < deadline:
        focus.pump()
        after = focus.read(window["pid"])
        if focus.changed(before, after):
            changed_ms = (time.monotonic() - started) * 1000
            break
        time.sleep(0.01)
    return {"before": focus.public(before), "after": focus.public(after),
            "input_submission_ms": round(input_ms, 3),
            "focus_observed_ms": round(changed_ms, 3) if changed_ms is not None else None,
            "focus_changed": changed_ms is not None}


def screenshot(window_id: int, path: Path):
    """Explicit opt-in, target-window-only PNG, always mode 0600."""
    import gi
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkX11", "3.0")
    from gi.repository import Gdk, GdkX11
    Gdk.init([])
    display = Gdk.Display.get_default()
    if display is None:
        raise DiagnosticError("Screenshot display unavailable")
    window = GdkX11.X11Window.foreign_new_for_display(display, window_id)
    if window is None:
        raise DiagnosticError("Screenshot target unavailable")
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, window.get_width(), window.get_height())
    if pixbuf is None:
        raise DiagnosticError("Screenshot capture failed")
    fd, temporary = tempfile.mkstemp(prefix=".lrd-screenshot-", dir=path.parent)
    os.close(fd)
    try:
        if not pixbuf.savev(temporary, "png", [], []):
            raise DiagnosticError("Screenshot save failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise DiagnosticError("Invalid diagnostic arguments")


def main(argv=None) -> int:
    try:
        parser = PrivateParser(description=__doc__.splitlines()[0])
        parser.add_argument("--display", default=":0")
        parser.add_argument("--target", choices=tuple(TARGETS))
        parser.add_argument("--window", type=int)
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--key", action="append", default=[], help="Allowlisted navigation/lock test input")
        parser.add_argument("--timeout", type=float, default=0.6)
        parser.add_argument("--watch-locks", type=float, default=0, help="Seconds to observe XKB state, no key listener")
        parser.add_argument("--screenshot", type=Path)
        args = parser.parse_args(argv)
        if (not 0.05 <= args.timeout <= 3 or not 0 <= args.watch_locks <= 60
                or len(args.key) > 20 or any(key not in KEYS for key in args.key)
                or ((args.activate or args.key or args.screenshot or args.window) and not args.target)):
            raise DiagnosticError("Invalid diagnostic arguments")
        from linux_rdaccess import graphical_session_env
        environment = graphical_session_env()
        if environment.get("DISPLAY") != args.display or environment.get("XDG_SESSION_TYPE") == "wayland":
            raise DiagnosticError("Requested X11 session does not match detected session")
        os.environ.update(environment)
        xkb = Xkb(args.display)
        try:
            result = {"display": args.display, "xkb_before": xkb.snapshot()}
            if args.watch_locks:
                print(json.dumps(result), flush=True)
                previous = result["xkb_before"]
                started = time.monotonic()
                while time.monotonic() - started < args.watch_locks:
                    current = xkb.snapshot()
                    if current != previous:
                        print(json.dumps({"elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                                          "xkb": current}), flush=True)
                        previous = current
                    time.sleep(0.02)
                result = {"xkb_after": xkb.snapshot()}
            elif args.target:
                windows = target_windows(args.target)
                result["windows"] = windows
                if args.window:
                    windows = [item for item in windows if item["window_id"] == args.window]
                if len(windows) != 1:
                    if args.activate or args.key or args.screenshot or args.window:
                        raise DiagnosticError("Select one existing target window with --window")
                    result["selection_required"] = True
                    print(json.dumps(result), flush=True)
                    return 0
                window = windows[0]
                focus = Focus()
                if args.activate:
                    command(["xdotool", "windowactivate", "--sync", str(window["window_id"])])
                result["focus"] = focus.public(focus.read(window["pid"]))
                if args.key:
                    backend = injection_backend()
                    try:
                        result["steps"] = [dict(step=index, **exercise(window, key, focus, backend, args.timeout))
                                           for index, key in enumerate(args.key, 1)]
                    finally:
                        backend.close()
                if args.screenshot:
                    screenshot(window["window_id"], args.screenshot)
                    result["screenshot_saved_privately"] = True
                result["xkb_after"] = xkb.snapshot()
            print(json.dumps(result), flush=True)
        finally:
            xkb.close()
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, DiagnosticError) else "Diagnostic unavailable"
        print(json.dumps({"error": message}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
