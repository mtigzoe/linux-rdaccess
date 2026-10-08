#!/usr/bin/env python3
"""Check actual GTK controls and semantic snapshots in a disposable Xvfb session.

Run ``python3 tools/diagnostics/gtk_atspi_smoke.py`` on Linux with GTK3/AT-SPI, Xvfb,
dbus-run-session, xfwm4 and xdotool installed. The runner creates a private
display, session bus and settings directories; it does not use the desktop.
The optional first argument selects another source checkout to test.
"""
from pathlib import Path
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]).resolve()
sys.path.insert(0, str(root))
from linux_rdaccess_core.accessibility.a11y_model import build_focus_payload, build_text_update, find_focused_object_ex, object_id

private = Path(os.environ.get("LRD_SMOKE_PRIVATE", "")) if "--inner" in sys.argv else Path(
    tempfile.mkdtemp(prefix="linux-rdaccess-gtk-smoke-"))
os.environ["LRD_SMOKE_PRIVATE"] = str(private)
os.environ.pop("NO_AT_BRIDGE", None)
os.environ.pop("AT_SPI_BUS_ADDRESS", None)
os.environ.pop("WAYLAND_DISPLAY", None)
os.environ["GSETTINGS_BACKEND"] = "memory"
os.environ["GTK_USE_PORTAL"] = "0"
os.environ["GIO_USE_VFS"] = "local"
os.environ["XDG_CURRENT_DESKTOP"] = "XFCE"
os.environ["XDG_SESSION_TYPE"] = "x11"
os.environ["GTK_MODULES"] = "gail:atk-bridge"
os.environ["GDK_BACKEND"] = "x11"
for variable, name in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                       ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
    directory = private / name
    directory.mkdir(mode=0o700, exist_ok=True)
    os.environ[variable] = str(directory)

if "--inner" not in sys.argv:
    print("ISOLATED_LOG_DIR", private, flush=True)
    raise SystemExit(subprocess.call(["xvfb-run", "-a", "dbus-run-session", "--", sys.executable,
                                     str(Path(__file__).resolve()), str(root), "--inner"]))

# Refuse keyboard injection if the inner invocation is pointed at a desktop.
display = re.fullmatch(r":(\d+)(?:\.\d+)?", os.environ.get("DISPLAY", ""))
if not display:
    raise SystemExit("This check requires a private Xvfb display.")
pid = int(Path(f"/tmp/.X{display[1]}-lock").read_text().strip())
if Path(f"/proc/{pid}/comm").read_text().strip() != "Xvfb":
    raise SystemExit("This check requires a private Xvfb display.")

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

spec = importlib.util.spec_from_file_location("smoke", root / "tests/apps/accessibility_smoke_app.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
context = GLib.MainContext.default()
events = []
checks = []
processes = []
streams = []

def wait(predicate, label, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        try:
            result = predicate()
        except GLib.Error:
            result = None
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError(f"Timed out: {label}")

def check(label, value=True):
    if not value:
        raise AssertionError(label)
    checks.append(label)
    print("PASS", label, flush=True)

def walk(source, budget=300):
    pending = [source]
    visited = set()
    while pending and len(visited) < budget:
        current = pending.pop()
        oid = object_id(current)
        if oid in visited:
            continue
        visited.add(oid)
        yield current
        for index in range(min(128, current.get_child_count())):
            child = current.get_child_at_index(index)
            if child is not None:
                pending.append(child)

def named(name, role=None):
    for accessible in walk(Atspi.get_desktop(0)):
        matches_role = role is None or (accessible.get_role_name() in role if isinstance(role, set)
                                       else accessible.get_role_name() == role)
        if accessible.get_name() == name and matches_role:
            return accessible
    return None

def focused(accessible):
    return accessible.get_state_set().contains(Atspi.StateType.FOCUSED)

def key(*keys):
    subprocess.run(["xdotool", "key", "--clearmodifiers", *keys], check=True)

def focus(accessible):
    if not accessible.get_component_iface().grab_focus():
        raise AssertionError("AT-SPI control refused keyboard focus")
    wait(lambda: focused(accessible), "control focus")

def on_event(event, _data=None):
    try:
        events.append((event.type, event.detail1, event.source.get_name()))
    except GLib.Error:
        pass

try:
    for name, arguments in (("wm", ["xfwm4", "--replace", "--compositor=off"]),
                            ("atspi", ["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"])):
        stream = (private / f"{name}.log").open("w")
        streams.append(stream)
        processes.append(subprocess.Popen(arguments, stdout=stream, stderr=stream))
    listener = Atspi.EventListener.new(on_event)
    for event_type in ("object:state-changed:focused", "object:state-changed:checked",
                       "object:text-changed", "object:text-caret-moved"):
        check("register " + event_type, listener.register(event_type))
    stream = (private / "application.log").open("w")
    streams.append(stream)
    processes.append(subprocess.Popen([sys.executable, str(root / "tests/apps/accessibility_smoke_app.py")],
                                      stdout=stream, stderr=stream))
    primary = wait(lambda: named("Apply changes", "push button"), "GTK AT-SPI application startup")
    title = "linux-rdaccess accessibility smoke test"
    window_ids = subprocess.check_output(["xdotool", "search", "--name", title], text=True).splitlines()
    # xfwm4 can still be claiming the session when the GTK window first appears.
    # Retry activation instead of treating that transient X11 race as a failure.
    def activate_window():
        result = subprocess.run(
            ["xdotool", "windowactivate", "--sync", window_ids[-1]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3, check=False,
        )
        return result.returncode == 0

    wait(activate_window, "GTK window activation by window manager", timeout=15)
    check("GTK window activation")
    controls = {}
    roles = {}
    for declared in smoke.CONTROL_SPECS:
        name = declared["label"]
        if declared["id"] == "items-list":
            page = wait(lambda: named("List", "page tab"), "list notebook page")
            page.get_component_iface().grab_focus()
            key("space")
        expected = {declared["expected_role"]}
        accessible = wait(lambda name=name, expected=expected: named(name, expected), "accessible " + name)
        actual = accessible.get_role_name()
        check("role " + declared["id"], actual in expected)
        controls[declared["id"]] = accessible
        roles[declared["id"]] = actual
    print("ROLES", json.dumps(roles, sort_keys=True), flush=True)

    focus(primary)
    key("Tab")
    checkbox = controls["feature-checkbox"]
    wait(lambda: focused(checkbox), "Tab reaches checkbox")
    check("keyboard Tab changes focus from button to checkbox")
    found, complete = find_focused_object_ex(Atspi.get_desktop(0))
    check("semantic focus search finds the actual GTK keyboard target",
          found is not None and complete and object_id(found) == object_id(checkbox))
    wait(lambda: any(kind == "object:state-changed:focused" and detail and name == "Enable notifications"
                     for kind, detail, name in events), "focused AT-SPI event")
    check("AT-SPI focus event follows keyboard Tab")
    key("shift+Tab")
    wait(lambda: focused(primary), "Shift+Tab returns to button")
    check("keyboard Shift+Tab restores the previous focus target")
    key("Tab")
    wait(lambda: focused(checkbox), "Tab returns to checkbox")
    check("checkbox initially checked", checkbox.get_state_set().contains(Atspi.StateType.CHECKED))
    key("space")
    wait(lambda: not checkbox.get_state_set().contains(Atspi.StateType.CHECKED), "checkbox toggle")
    check("keyboard Space updates checkbox checked state")
    wait(lambda: any(kind == "object:state-changed:checked" and not detail
                     and name == "Enable notifications" for kind, detail, name in events), "checked AT-SPI event")
    check("AT-SPI checked event follows checkbox toggle")

    entry = controls["single-entry"]
    focus(entry)
    key("ctrl+a")
    subprocess.run(["xdotool", "type", "--clearmodifiers", "prelive-edit"], check=True)
    text = entry.get_text_iface()
    wait(lambda: text.get_text(0, text.get_character_count()) == "prelive-edit", "entry edits")
    check("keyboard typing replaces editable entry text")
    wait(lambda: text.get_caret_offset() == len("prelive-edit"), "entry caret")
    check("editable entry caret follows typed text")
    registry = {}
    payload = build_focus_payload("object:state-changed:focused", 1, entry, object_registry=registry)
    focused_snapshot = next(item for item in payload["objects"] if item["id"] == payload["focus_id"])
    check("semantic focus snapshot carries actual GTK entry text and caret",
          focused_snapshot["text"] == "prelive-edit" and focused_snapshot["caret_offset"] == len("prelive-edit"))
    key("Left")
    wait(lambda: text.get_caret_offset() == len("prelive-edit") - 1, "left arrow caret")
    update = build_text_update("object:text-caret-moved", entry, object_registry=registry)
    check("semantic caret update carries actual arrow navigation",
          update is not None and update["caret_offset"] == len("prelive-edit") - 1)
    wait(lambda: any(kind == "object:text-caret-moved" and name == "Account name"
                     for kind, _detail, name in events), "caret AT-SPI event")
    check("AT-SPI text/caret events are emitted")

    # A populated table must expose selection changes, not just its role.
    page = wait(lambda: named("List", "page tab"), "list notebook page")
    selection = controls["settings-tabs"].get_selection_iface()
    if not selection.select_child(1):
        raise AssertionError("List notebook page refused selection")
    wait(lambda: page.get_state_set().contains(Atspi.StateType.SELECTED), "list notebook page selected")
    file_list = controls["items-list"]
    focus(file_list)
    key("ctrl+Home")
    table = file_list.get_table_iface()
    wait(lambda: list(table.get_selected_rows()) == [0], "first file row selected")
    key("Down")
    wait(lambda: list(table.get_selected_rows()) == [1], "next file row selected")
    cell = table.get_accessible_at(1, 0)
    check("Down changes the selected table row and preserves its accessible name",
          cell.get_name() == "Pictures" and cell.get_role_name() == "table cell")
    key("Up")
    wait(lambda: list(table.get_selected_rows()) == [0], "previous file row selected")
    check("Up restores the previous table selection")

    focus(primary)
    key("alt+f")
    close_item = wait(lambda: named("Close", "menu item"), "File menu item")
    wait(lambda: close_item.get_state_set().contains(Atspi.StateType.SHOWING), "File menu visible")
    check("Alt+F opens an accessible menu with a named menu item")
    key("Escape")
    wait(lambda: focused(primary), "menu focus restored")
    check("Escape dismisses the menu and restores the previous control focus")

    dialog_button = controls["dialog-button"]
    focus(dialog_button)
    key("space")
    dialog = wait(lambda: named("Sample confirmation", "dialog"), "modal confirmation dialog")
    check("modal dialog exposes dialog role and modal state",
          dialog.get_state_set().contains(Atspi.StateType.MODAL))
    wait(lambda: any(focused(item) for item in walk(dialog)), "modal focused control")
    check("keyboard focus enters the modal dialog")
    key("Escape")
    wait(lambda: named("Sample confirmation", "dialog") is None, "modal closed")
    wait(lambda: focused(dialog_button), "focus restored to opener")
    check("Escape closes modal and restores keyboard focus to its opener")
    print(json.dumps({"status": "PASS", "checks": len(checks), "roles": roles,
                      "event_count": len(events), "log_dir": str(private)}, sort_keys=True), flush=True)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in streams:
        stream.close()
