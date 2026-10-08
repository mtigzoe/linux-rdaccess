#!/usr/bin/env python3
"""Smoke-test actual XFCE applications via AT-SPI inside a private Xvfb session.

Run with: dbus-run-session -- xvfb-run -a python3 tools/diagnostics/real_gui_atspi_smoke.py
No real user display, Orca session, NVDA relay, or braille hardware is used.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


def verify_private_display() -> None:
    match = re.fullmatch(r":(\d+)(?:\.\d+)?", os.environ.get("DISPLAY", ""))
    if not match:
        raise RuntimeError("A private Xvfb display is required")
    pid = int(Path(f"/tmp/.X{match.group(1)}-lock").read_text().strip())
    if Path(f"/proc/{pid}/comm").read_text().strip() != "Xvfb":
        raise RuntimeError("Refusing to operate outside Xvfb")


def wait_for(predicate, label: str, *, seconds: float = 18):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {label}")


def walk(obj, *, limit: int = 400):
    queue = [obj]
    seen = set()
    while queue and len(seen) < limit:
        obj = queue.pop(0)
        try:
            identifier = (obj.get_process_id(), obj.get_role_name(), obj.get_name())
            if identifier in seen:
                continue
            seen.add(identifier)
            yield obj
            queue.extend(obj.get_child_at_index(i) for i in range(min(obj.get_child_count(), 80)))
            queue = [x for x in queue if x is not None]
        except Exception:
            continue


def main() -> int:
    verify_private_display()
    # Keep app settings and caches strictly inside a disposable directory.
    with tempfile.TemporaryDirectory(prefix="lrd-real-gui-") as temporary:
        root = Path(temporary)
        env = os.environ.copy()
        env.update({
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
            "GSETTINGS_BACKEND": "memory",
            "GDK_BACKEND": "x11",
            "GTK_MODULES": "gail:atk-bridge",
        })
        env.pop("NO_AT_BRIDGE", None)
        for key in ("config", "data", "cache", "runtime"):
            (root / key).mkdir(mode=0o700)
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        processes = []
        log_files = []
        try:
            for name, command in (
                ("xfwm4", ["xfwm4", "--replace", "--compositor=off"]),
                ("atspi", ["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"]),
                ("thunar", ["thunar", str(root)]),
                ("mousepad", ["mousepad"]),
            ):
                log_file = (root / f"{name}.log").open("w")
                log_files.append(log_file)
                processes.append(subprocess.Popen(command, env=env, stdout=log_file, stderr=log_file))
            for name, target in (("Thunar", "thunar"), ("Mousepad", "mousepad")):
                def find_application():
                    desktop = Atspi.get_desktop(0)
                    for app in walk(desktop):
                        if app.get_role_name() == "application" and target in app.get_name().casefold():
                            return app
                    return None
                app = wait_for(find_application, f"{name} AT-SPI application")
                def has_window():
                    for child in walk(app):
                        if child.get_role_name() in ("frame", "window", "dialog"):
                            return True
                    return False
                wait_for(has_window, f"{name} accessible top-level window")
                def semantic_controls():
                    roles = {node.get_role_name() for node in walk(app)}
                    # Both real applications expose interactive controls in
                    # their AT-SPI hierarchy, not just an application frame.
                    return roles if any(role in roles for role in (
                        "menu bar", "menu", "push button", "text", "entry",
                        "table", "tree table", "page tab list", "tool bar",
                    )) else None
                roles = wait_for(semantic_controls, f"{name} interactive AT-SPI controls")
                print(f"PASS {name}: application, window and interactive roles {sorted(roles)}", flush=True)
            # Verify an actual keyboard event reaches a live XFCE application.
            # F10 is GTK's standard menu-bar focus key in Mousepad.
            windows = subprocess.check_output(
                ["xdotool", "search", "--onlyvisible", "--class", "mousepad"],
                text=True, env=env,
            ).splitlines()
            if not windows:
                raise AssertionError("Mousepad X11 window not found")
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", windows[-1]],
                env=env, check=True, timeout=5,
            )
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "F10"],
                env=env, check=True, timeout=5,
            )
            def mousepad_menu_focus():
                desktop = Atspi.get_desktop(0)
                for node in walk(desktop):
                    try:
                        states = node.get_state_set()
                        if states.contains(Atspi.StateType.FOCUSED) and node.get_role_name() in (
                            "menu", "menu item", "menu bar",
                        ):
                            return node.get_role_name()
                    except Exception:
                        continue
                return None
            role = wait_for(mousepad_menu_focus, "Mousepad F10 menu keyboard focus")
            print(f"PASS Mousepad: F10 keyboard moves AT-SPI focus to {role}", flush=True)
            return 0
        except Exception:
            for log in sorted(root.glob("*.log")):
                print(f"--- {log.name} ---", file=sys.stderr)
                print(log.read_text(errors="replace")[-3500:], file=sys.stderr)
            raise
        finally:
            for proc in reversed(processes):
                if proc.poll() is None:
                    proc.terminate()
            for proc in reversed(processes):
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=4)
            for stream in log_files:
                stream.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
