#!/usr/bin/env python3
"""Assert real application keyboard/AT-SPI behavior in a disposable session.

Run ``python3 tools/diagnostics/real_gui_atspi_smoke.py --skip vscode`` when
only VS Code's Remote SSH CLI is available. Without --skip every application
is required. The runner owns a private Xvfb display, D-Bus and app settings;
calling it from an existing dbus-run-session/xvfb-run is also safe.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from linux_rdaccess_core.accessibility.a11y_model import (
    build_focus_payload, build_text_update, object_id, set_caret_offset,
)

APPLICATIONS = ("settings", "thunar", "mousepad", "terminal", "calendar", "firefox", "vscode")
BINARIES = dict(zip(APPLICATIONS, ("xfce4-settings-manager", "thunar", "mousepad",
                                "xfce4-terminal", "xfce4-panel", "firefox", "code")))


def isolated_environment(root: Path, source=None) -> dict:
    env = dict(os.environ if source is None else source)
    # Sanitize both the inspector and applications, before importing AT-SPI
    # or spawning the bus. An SSH-inherited address can otherwise reach Orca's
    # active desktop despite DISPLAY pointing at Xvfb.
    for name in ("AT_SPI_BUS_ADDRESS", "DBUS_SESSION_BUS_ADDRESS", "NO_AT_BRIDGE",
                 "WAYLAND_DISPLAY", "SESSION_MANAGER", "VSCODE_IPC_HOOK_CLI",
                 "VSCODE_CLI_AUTHORITY", "ELECTRON_RUN_AS_NODE"):
        env.pop(name, None)
    env.update({
        "GSETTINGS_BACKEND": "memory", "GDK_BACKEND": "x11",
        "GTK_MODULES": "gail:atk-bridge", "GTK_USE_PORTAL": "0",
        "GIO_USE_VFS": "local", "GVFS_DISABLE_FUSE": "1", "XDG_CURRENT_DESKTOP": "XFCE",
        "XDG_SESSION_TYPE": "x11", "LC_ALL": "C.UTF-8",
        "LRD_GUI_PRIVATE": str(root),
    })
    for variable, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                                ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
        path = root / directory
        path.mkdir(mode=0o700, exist_ok=True)
        env[variable] = str(path)
    return env


def verify_private_display() -> None:
    match = re.fullmatch(r":(\d+)(?:\.\d+)?", os.environ.get("DISPLAY", ""))
    if not match:
        raise RuntimeError("A private Xvfb display is required")
    try:
        pid = int(Path(f"/tmp/.X{match[1]}-lock").read_text().strip())
        private = Path(f"/proc/{pid}/comm").read_text().strip() == "Xvfb"
    except (OSError, ValueError):
        private = False
    if not private:
        raise RuntimeError("Refusing to operate outside Xvfb")


def verify_private_bus_environment(daemon_environment: bytes, source=None) -> None:
    env = os.environ if source is None else source
    daemon = dict(item.split(b"=", 1) for item in daemon_environment.split(b"\0") if b"=" in item)
    root = env.get("LRD_GUI_PRIVATE", "")
    if not root or not env.get("DISPLAY"):
        raise RuntimeError("A runner-owned private D-Bus session is required")
    expected_runtime = str(Path(root) / "runtime")
    if env.get("XDG_RUNTIME_DIR") != expected_runtime:
        raise RuntimeError("D-Bus runtime directory must belong to the private test session")
    for name in ("LRD_GUI_PRIVATE", "DISPLAY", "XDG_RUNTIME_DIR"):
        if daemon.get(name.encode()) != env[name].encode():
            raise RuntimeError("Refusing to use a D-Bus daemon outside the private Xvfb session")


def walk(obj, *, limit: int = 1500):
    """Walk proxy identities: equally named controls are distinct objects."""
    queue = deque([obj])
    seen = set()
    while queue and len(seen) < limit:
        obj = queue.popleft()
        if obj is None or obj in seen:
            continue
        seen.add(obj)
        try:
            yield obj
            queue.extend(obj.get_child_at_index(i) for i in range(min(obj.get_child_count(), 250)))
        except Exception:
            # Providers can remove children during focus/menu transitions.
            continue


def desktop_code_binary() -> str | None:
    # Remote SSH prepends its CLI to PATH even if desktop Code is installed.
    for binary in (shutil.which("code"), "/usr/bin/code", "/usr/local/bin/code"):
        if not binary:
            continue
        resolved = Path(binary).resolve()
        if "remote-cli" in resolved.parts or ".vscode-server" in resolved.parts:
            continue
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            continue
        # The desktop CLI detaches Electron and exits before its GUI. Launch
        # the package's native executable so we own its process group.
        native = resolved.parent.parent / "code"
        if native.is_file() and os.access(native, os.X_OK):
            return str(native)
        return binary
    return None


class Session:
    def __init__(self, root: Path):
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib, Gio
        self.Atspi, self.GLib = Atspi, GLib
        # Chromium/Electron also consult the private bus screen-reader status.
        # Set it here without starting or touching an Orca process.
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        response = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                 "org.freedesktop.DBus", "GetConnectionUnixProcessID",
                                 GLib.Variant("(s)", ("org.freedesktop.DBus",)),
                                 GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 5000, None)
        try:
            daemon_environment = Path(f"/proc/{response.unpack()[0]}/environ").read_bytes()
        except OSError as exc:
            raise RuntimeError("Cannot verify private D-Bus daemon ownership") from exc
        verify_private_bus_environment(daemon_environment)
        for property_name in ("IsEnabled", "ScreenReaderEnabled"):
            bus.call_sync("org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties",
                          "Set", GLib.Variant("(ssv)", ("org.a11y.Status", property_name,
                                                       GLib.Variant("b", True))),
                          None, Gio.DBusCallFlags.NONE, 5000, None)
        self.context = GLib.MainContext.default()
        self.root = root
        self.processes = []
        self.streams = []
        self.checks = []
        self.events = []
        self.listener = Atspi.EventListener.new(self.on_event)
        for kind in ("object:state-changed:focused", "object:text-changed", "object:text-caret-moved"):
            if not self.listener.register(kind):
                raise AssertionError(f"Cannot register AT-SPI event {kind}")

    def on_event(self, event, _data=None):
        try:
            self.events.append((event.type, event.detail1, event.source))
        except self.GLib.Error:
            pass

    def wait(self, predicate, label: str, *, seconds: float = 18):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            while self.context.pending():
                self.context.iteration(False)
            try:
                result = predicate()
                if result:
                    return result
            except self.GLib.Error:
                pass
            time.sleep(0.04)
        raise AssertionError(f"Timed out waiting for {label}")

    def check(self, label: str, condition=True):
        if not condition:
            raise AssertionError(label)
        self.checks.append(label)
        print("PASS", label, flush=True)

    def launch(self, label: str, command: list[str]):
        stream = (self.root / f"{label}.log").open("w")
        self.streams.append(stream)
        proc = subprocess.Popen(command, stdout=stream, stderr=stream, start_new_session=True)
        self.processes.append(proc)
        return proc

    def application(self, name: str):
        def find():
            desktop = self.Atspi.get_desktop(0)
            for index in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(index)
                if app and name in app.get_name().casefold():
                    return app
            return None
        app = self.wait(find, f"{name} AT-SPI application", seconds=40 if name == "code" else 18)
        window = self.wait(lambda: self.find(app, {"frame", "window", "dialog"}),
                           f"{name} accessible window")
        self.check(f"{name}: named application and {window.get_role_name()} window", bool(app.get_name()))
        return app

    def find(self, app, roles=None, name=None, predicate=None):
        for node in walk(app):
            if roles and node.get_role_name() not in roles:
                continue
            if name is not None and node.get_name() != name:
                continue
            if predicate and not predicate(node):
                continue
            return node
        return None

    def state(self, node, state):
        return node.get_state_set().contains(getattr(self.Atspi.StateType, state))

    def focused(self, app):
        # Breadth-first traversal leaves the deepest focused descendant last;
        # Firefox/Electron can report FOCUSED on both a window and its input.
        focused = None
        for node in walk(app):
            if self.state(node, "FOCUSED"):
                focused = node
        return focused

    def showing(self, node):
        return self.state(node, "SHOWING") and self.state(node, "VISIBLE")

    def focus(self, node):
        # GTK can publish hidden or unrealized accessibles before a window
        # is ready. Native focus requires mapped geometry so the following
        # keyboard event reaches a visible widget.
        self.wait(lambda: self.showing(node), "mapped accessible control before focus")
        component = node.get_component_iface()
        self.wait(lambda: (extents := component.get_extents(self.Atspi.CoordType.SCREEN)).width > 0
                  and extents.height > 0 and extents.x > -(1 << 30) and extents.y > -(1 << 30),
                  "realized accessible component before focus")
        if not component.grab_focus():
            raise AssertionError(f"Cannot focus {node.get_role_name()} {node.get_name()!r}")
        self.wait(lambda: self.state(node, "FOCUSED"), "AT-SPI focus")

    def key(self, *keys):
        subprocess.run(["xdotool", "key", "--clearmodifiers", *keys], check=True, timeout=6,
                       stdout=subprocess.DEVNULL)

    def type(self, value):
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "2", value],
                       check=True, timeout=8, stdout=subprocess.DEVNULL)

    def activate(self, app):
        pid = str(app.get_process_id())
        def windows():
            result = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", pid],
                                    capture_output=True, text=True, timeout=5)
            if result.stdout.splitlines():
                return result.stdout.splitlines()
            # Electron may expose a renderer PID over AT-SPI while X11 owns
            # the browser PID. The display contains only our test processes.
            result = subprocess.run(["xdotool", "search", "--onlyvisible", "--class",
                                     re.escape(app.get_name())], capture_output=True, text=True, timeout=5)
            return result.stdout.splitlines() or None
        ids = self.wait(windows, f"{app.get_name()} visible X11 window")
        def activate():
            result = subprocess.run(["xdotool", "windowactivate", "--sync", ids[-1]],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            return result.returncode == 0
        self.wait(activate, "window activation")
        active = subprocess.check_output(["xdotool", "getactivewindow"], text=True).strip()
        self.check(f"{app.get_name()}: X11 window activation", active == ids[-1])

    def tab_round_trip(self, app, initial):
        self.focus(initial)
        start = len(self.events)
        self.key("Tab")
        changed = self.wait(lambda: (node if (node := self.focused(app)) != initial else None),
                            f"{app.get_name()} Tab changes accessible focus")
        self.check(f"{app.get_name()}: Tab changes focus to {changed.get_role_name()}")
        self.wait(lambda: any(kind == "object:state-changed:focused" and detail and source == changed
                              for kind, detail, source in self.events[start:]), "Tab focus event")
        self.check(f"{app.get_name()}: keyboard focus emits AT-SPI event")
        self.key("shift+Tab")
        self.wait(lambda: self.state(initial, "FOCUSED"), "Shift+Tab restores previous control")
        self.check(f"{app.get_name()}: Shift+Tab restores previous control")

    def text_edit(self, node, value, label):
        self.focus(node)
        self.key("ctrl+a")
        self.type(value)
        text = node.get_text_iface()
        self.wait(lambda: self.Atspi.Text.get_text(text, 0, text.get_character_count()) == value, label + " text")
        self.wait(lambda: text.get_caret_offset() == len(value), label + " caret")
        self.key("Left")
        self.wait(lambda: text.get_caret_offset() == len(value) - 1, label + " left-arrow caret")
        self.check(label + ": typed text and left-arrow caret match AT-SPI")
        self.check(label + ": semantic routing accepts provider caret setter",
                   set_caret_offset(node, 1))
        self.wait(lambda: text.get_caret_offset() == 1, label + " routed caret")
        self.check(label + ": routed caret is confirmed by the provider")
        self.key("ctrl+a")

        def selected_text():
            update = build_text_update("object:text-selection-changed", node,
                                       object_registry={object_id(node): node})
            if (update is not None and update["text"] == value
                    and update["selection_start"] == 0
                    and update["selection_end"] == len(value)):
                return update
            return None

        self.wait(selected_text, label + " semantic selection")
        self.check(label + ": semantic text snapshot tracks keyboard selection")
        self.key("Right")
        self.wait(lambda: text.get_caret_offset() == len(value), label + " selection collapse")

    def close(self):
        # Bus launchers and GUI apps may fork. Each launched process owns a
        # new session, so signals cannot reach the user's desktop processes.
        for proc in reversed(self.processes):
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for proc in reversed(self.processes):
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=4)
        # Reap helpers even when the group's original leader already exited.
        for proc in reversed(self.processes):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for stream in self.streams:
            stream.close()


def settings_check(session):
    session.launch("settings", [BINARIES["settings"]])
    app = session.application("xfce4-settings-manager")
    session.activate(app)
    # XFCE Settings Manager versions differ in whether Search is mapped
    # initially. Keep the editable-field assertions when it is present, but
    # validate actual keyboard navigation through the category view when not.
    search = session.find(app, {"text", "entry"}, "Search", session.showing)
    if search is not None:
        session.tab_round_trip(app, search)
        session.text_edit(search, "keyboard", "Settings search")
        session.key("ctrl+a", "BackSpace")
        session.check("Settings Manager: search has accessible name and editable text",
                      "EditableText" in search.get_interfaces())
        return app

    # Require an accessible, visible control inside the Settings dialog.
    # Some Ubuntu/XFCE versions render the category chooser without a
    # standalone Search text entry.
    controls = {"push button", "toggle button", "icon", "list item", "table cell",
                "tree item", "page tab", "combo box", "check box"}
    control = session.wait(
        lambda: session.find(app, controls, predicate=session.showing),
        "showing Settings Manager category control",
    )
    session.focus(control)
    session.check("Settings Manager: category control is keyboard focusable",
                  session.state(control, "FOCUSED"))
    session.key("Tab")
    session.wait(lambda: (target if (target := session.focused(app)) != control else None),
                 "Settings Manager Tab moves from category control")
    session.check("Settings Manager: keyboard Tab changes accessible focus")
    return app


def thunar_check(session):
    files = session.root / "files"
    files.mkdir()
    for filename in ("alpha.txt", "beta.txt", "gamma.txt"):
        (files / filename).write_text("isolated accessibility fixture\n")
    session.launch("thunar", ["thunar", str(files)])
    app = session.application("thunar")
    session.activate(app)
    session.key("ctrl+l")
    location = session.wait(lambda: session.find(app, {"text", "entry"},
                                                predicate=lambda node: session.state(node, "FOCUSED")),
                            "Thunar location bar focus")
    text = location.get_text_iface()
    session.wait(lambda: str(files) in session.Atspi.Text.get_text(text, 0, text.get_character_count()), "location path")
    session.check("Thunar: Ctrl+L exposes focused location text with current path")
    session.key("Escape", "ctrl+2")
    table = session.wait(lambda: session.find(app, {"table", "tree table"},
                                             predicate=lambda node: "Selection" in node.get_interfaces()
                                             and session.find(node, {"table cell"}, "alpha.txt") is not None),
                         "Thunar file table and named fixture rows")
    session.focus(table)
    session.key("ctrl+a")
    selection = table.get_table_iface()
    session.wait(lambda: len(selection.get_selected_rows()) == 3, "Thunar Ctrl+A selects three fixture rows")
    session.check("Thunar: Ctrl+A selects all three named fixture rows through AT-SPI")
    session.key("Down")
    session.wait(lambda: len(selection.get_selected_rows()) == 1, "Thunar Down selects single row")
    first = tuple(selection.get_selected_rows())
    session.key("Down")
    session.wait(lambda: len(selection.get_selected_rows()) == 1 and
                 tuple(selection.get_selected_rows()) != first, "Thunar Down changes selected row")
    session.check("Thunar: table exposes named files and keyboard Down changes AT-SPI selected row")
    return app


def mousepad_check(session, thunar=None):
    fixture = session.root / "mousepad.txt"
    fixture.write_text("initial text\n")
    session.launch("mousepad", ["mousepad", str(fixture)])
    app = session.application("mousepad")
    session.activate(app)
    editor = session.wait(lambda: session.find(app, {"text"}, predicate=lambda node:
                                                "EditableText" in node.get_interfaces()
                                                and session.state(node, "FOCUSED")), "Mousepad editor")
    session.text_edit(editor, "lrd mousepad text", "Mousepad editor")
    if thunar is not None:
        session.activate(thunar)
        session.activate(app)
        session.wait(lambda: session.state(editor, "FOCUSED"), "editor focus after window switching")
        session.check("Mousepad: window switching restores editor focus")
    session.key("ctrl+o")
    dialog = session.wait(lambda: session.find(app, {"file chooser", "dialog"},
                                               predicate=lambda node: "open" in node.get_name().casefold()),
                          "Mousepad Ctrl+O file chooser")
    session.wait(lambda: session.focused(dialog), "file chooser focused control")
    # Choose a standard button so this round trip does not depend on GTK's
    # location-bar implementation or its internal completion popup.
    cancel = session.wait(lambda: session.find(dialog, {"push button"}, "Cancel"), "file chooser Cancel")
    session.tab_round_trip(dialog, cancel)
    session.key("Escape")
    session.wait(lambda: session.find(app, {"file chooser", "dialog"},
                                      predicate=lambda node: "open" in node.get_name().casefold()) is None,
                 "file chooser dismissed")
    session.wait(lambda: session.state(editor, "FOCUSED"), "Mousepad restored editor focus")
    session.check("Mousepad: Ctrl+O dialog, Escape dismissal and editor focus restoration")
    return app


def terminal_check(session):
    session.launch("terminal", ["xfce4-terminal", "--disable-server", "--command", "/bin/sh"])
    app = session.application("xfce4-terminal")
    session.activate(app)
    terminal = session.wait(lambda: session.find(app, {"terminal"}), "VTE terminal accessibility")
    session.focus(terminal)
    session.type("printf 'LRD_%s_%s\\n' TERMINAL MARKER")
    session.key("Return")
    text = terminal.get_text_iface()
    session.wait(lambda: re.search(r"(?m)^LRD_TERMINAL_MARKER\r?$", session.Atspi.Text.get_text(text, 0, text.get_character_count())),
                 "terminal output in AT-SPI text")
    session.check("XFCE Terminal: typed shell command exposes output through AT-SPI terminal text")
    session.key("F10")
    item = session.wait(lambda: session.find(app, {"menu", "menu item"},
                                             predicate=lambda node: session.state(node, "FOCUSED")),
                        "Terminal F10 menu focus")
    session.key("Right")
    session.wait(lambda: (node := session.focused(app)) is not None and node != item,
                 "Terminal menu arrow navigation")
    session.key("Escape")
    session.wait(lambda: session.state(terminal, "FOCUSED"), "terminal focus restored after menu")
    session.check("XFCE Terminal: F10 menu, arrow navigation and Escape restore terminal focus")


def panel_config(root):
    directory = root / "config/xfce4/xfconf/xfce-perchannel-xml"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "xfce4-panel.xml").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
 <property name="configver" type="int" value="2"/>
 <property name="panels" type="array"><value type="int" value="1"/>
  <property name="panel-1" type="empty">
   <property name="position" type="string" value="p=6;x=0;y=0"/>
   <property name="length" type="uint" value="100"/>
   <property name="size" type="uint" value="32"/>
   <property name="plugin-ids" type="array"><value type="int" value="1"/></property>
  </property>
 </property>
 <property name="plugins" type="empty"><property name="plugin-1" type="string" value="clock"/></property>
</channel>''')


def calendar_check(session):
    session.launch("calendar", ["xfce4-panel", "--disable-wm-check"])
    app = session.application("xfce4-panel")
    clock = session.wait(lambda: session.find(app, {"toggle button"},
                                             predicate=lambda node: bool(node.get_name())), "named clock")
    action = clock.get_action_iface()
    session.check("XFCE clock: named toggle exposes calendar action", action.get_n_actions() > 0)
    # XFCE 4.16's clock does not accept keyboard focus and its AT-SPI click
    # action toggles state without opening the calendar. Open by pointer on
    # this private display, then verify the popup's real keyboard behavior.
    print("LIMITATION XFCE clock: keyboard activation unavailable; pointer opens calendar", flush=True)
    extents = clock.get_component_iface().get_extents(session.Atspi.CoordType.SCREEN)
    subprocess.run(["xdotool", "mousemove", str(extents.x + extents.width // 2),
                    str(extents.y + extents.height // 2), "click", "1"], check=True, timeout=6,
                   stdout=subprocess.DEVNULL)
    calendar = session.wait(lambda: session.find(app, {"calendar"}), "clock calendar popup")
    session.wait(lambda: session.state(calendar, "FOCUSED"), "calendar popup keyboard focus")
    session.check("XFCE calendar: opening popup exposes calendar role and keyboard focus")
    # GTK3's calendar exposes only Component/Accessible; no selected date,
    # text or table is available over AT-SPI. Do not claim date-change checks.
    if not set(calendar.get_interfaces()).intersection({"Table", "Selection", "Text", "Value"}):
        print("LIMITATION XFCE calendar: AT-SPI provider exposes no selected-date semantics", flush=True)
    session.key("Escape")
    session.wait(lambda: session.find(app, {"calendar"}) is None, "calendar Escape dismissal")
    session.check("XFCE clock: keyboard Escape dismisses accessible calendar popup")


def firefox_check(session):
    profile = session.root / "firefox-profile"
    profile.mkdir()
    (profile / "user.js").write_text('''user_pref("accessibility.force_disabled", -1);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.tabs.warnOnClose", false);
''')
    page = session.root / "firefox.html"
    page.write_text('''<!doctype html><html lang="en"><title>LRD Firefox accessibility fixture</title>
<h1>Browser accessibility fixture</h1><label for="input">Smoke input</label>
<input id="input" autofocus><button onclick="const b=document.createElement('button');
b.textContent='Smoke replacement action';this.replaceWith(b);b.focus()">Smoke action</button>
<a href="#end">Smoke link</a>
<h2 id="end">Destination</h2></html>''')
    session.launch("firefox", ["firefox", "--no-remote", "--profile", str(profile), page.as_uri()])
    app = session.application("firefox")
    session.activate(app)
    # New Firefox profiles may show a first-run Terms of Use welcome dialog
    # even when about:welcome is disabled. It is part of this disposable
    # profile, so dismiss it through the accessible UI before testing HTML.
    def browser_document():
        document = session.find(app, {"document web"})
        if document is not None:
            return document
        welcome = session.find(app, {"dialog"}, predicate=lambda node:
                               "Welcome to Firefox" in node.get_name())
        if welcome is not None:
            buttons = [node for node in walk(welcome) if node.get_role_name() == "push button"]
            for button in buttons:
                if any(word in button.get_name().casefold() for word in
                       ("continue", "accept", "start browsing", "get started")):
                    button.get_action_iface().do_action(0)
                    break
        return None
    session.wait(browser_document, "Firefox document accessibility after welcome", seconds=35)
    entry = session.wait(lambda: session.find(app, {"entry", "text"}, "Smoke input"), "Firefox labelled input")
    session.text_edit(entry, "lrd browser text", "Firefox input")
    session.key("Tab")
    button = session.wait(lambda: session.find(app, {"push button"}, "Smoke action",
                                               lambda node: session.state(node, "FOCUSED")),
                          "Firefox Tab moves to labelled button")
    session.check("Firefox: Tab reaches named HTML button", bool(button.get_name()))
    session.key("shift+Tab")
    session.wait(lambda: session.state(entry, "FOCUSED"), "Firefox Shift+Tab restores HTML input")
    session.check("Firefox: Shift+Tab restores HTML input focus")
    session.key("ctrl+l")
    location = session.wait(lambda: session.find(app, {"entry", "text", "combo box"},
                                                predicate=lambda node: session.state(node, "FOCUSED")
                                                and node != entry), "Firefox URL bar focus")
    session.check("Firefox: Ctrl+L exposes named location control", bool(location.get_name()))
    session.key("Escape")
    session.wait(lambda: session.state(entry, "FOCUSED"), "Firefox Escape returns to document")
    session.check("Firefox: Escape restores document focus")
    old_id = object_id(button)
    session.focus(button)
    session.key("Return")
    replacement = session.wait(lambda: session.find(app, {"push button"}, "Smoke replacement action",
                                                    lambda node: session.state(node, "FOCUSED")),
                               "Firefox replacement button focus")
    payload = build_focus_payload("object:state-changed:focused", 1, replacement)
    objects = {item["id"]: item for item in payload["objects"]}
    session.check("Firefox: DOM replacement has a new semantic object identity",
                  payload["focus_id"] != old_id and old_id not in objects)
    session.check("Firefox: dynamic snapshot names and focuses the replacement control",
                  objects[payload["focus_id"]]["name"] == "Smoke replacement action"
                  and "focused" in objects[payload["focus_id"]]["states"])


def vscode_check(session):
    binary = desktop_code_binary()
    if binary is None:
        raise RuntimeError("VS Code desktop is unavailable (Remote SSH CLI is not a desktop binary); "
                           "install desktop Code or explicitly use --skip vscode")
    user_data = session.root / "code-user"
    settings = user_data / "User"
    settings.mkdir(parents=True)
    (settings / "settings.json").write_text(json.dumps({
        "editor.accessibilitySupport": "on", "workbench.startupEditor": "none",
        "workbench.enableExperiments": False, "security.workspace.trust.enabled": False,
        "update.mode": "none", "telemetry.telemetryLevel": "off", "chat.disableAIFeatures": True,
    }))
    fixture = session.root / "code-fixture.txt"
    fixture.write_text("isolated VS Code fixture\n")
    session.launch("vscode", [binary, "--user-data-dir", str(user_data), "--extensions-dir",
                              str(session.root / "code-extensions"), "--disable-extensions",
                              "--shared-data-dir", str(session.root / "code-shared"),
                              "--agents-user-data-dir", str(session.root / "code-agents-user"),
                              "--agents-extensions-dir", str(session.root / "code-agents-extensions"),
                              "--agent-plugins-dir", str(session.root / "code-agent-plugins"),
                              "--password-store=basic", "--disable-gpu",
                              "--disable-workspace-trust", "--new-window", "--force-renderer-accessibility=complete",
                              str(fixture)])
    app = session.application("code")
    session.activate(app)
    session.key("Escape", "ctrl+1")
    editor = session.wait(lambda: session.find(app, {"entry", "text"},
                                              predicate=lambda node: session.state(node, "FOCUSED")
                                              and "Text" in node.get_interfaces()
                                              and ("code-fixture.txt" in node.get_name()
                                                   or "editor" in node.get_name().casefold())),
                          "Code named editor input")
    session.check("VS Code: opened fixture exposes named editable editor", session.state(editor, "EDITABLE"))
    session.text_edit(editor, "lrd code text", "VS Code editor")
    session.key("ctrl+shift+p")
    # VS Code's palette uses aria-activedescendant: AT-SPI focuses the
    # selected result while the labelled input still receives typed text.
    palette = session.wait(lambda: session.find(app, {"entry", "text", "combo box"},
                                               predicate=lambda node: node != editor
                                               and "command" in node.get_name().casefold()
                                               and "Text" in node.get_interfaces()
                                               and session.state(node, "SHOWING")), "Code command palette")
    session.check("VS Code: command palette exposes named text input", bool(palette.get_name()))
    session.type("Go to Line")
    text = palette.get_text_iface()
    session.wait(lambda: "Go to Line" in session.Atspi.Text.get_text(text, 0, text.get_character_count()), "Code palette text")
    session.wait(lambda: session.find(app, {"list item", "option"},
                                      predicate=lambda node: "go to line" in node.get_name().casefold()
                                      and session.state(node, "FOCUSED")),
                 "Code palette named focused Go to Line result")
    session.key("Escape")
    session.wait(lambda: session.state(editor, "FOCUSED"), "Code original editor focus after palette Escape")
    session.check("VS Code: typed palette query exposes command list and Escape restores editor focus")


def run_inner(skip):
    verify_private_display()
    # Even --inner imports AT-SPI only after clearing inherited bridge state.
    os.environ.pop("AT_SPI_BUS_ADDRESS", None)
    root = Path(os.environ["LRD_GUI_PRIVATE"])
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("A private D-Bus session is required")
    panel_config(root)
    session = Session(root)
    try:
        session.launch("wm", ["xfwm4", "--replace", "--compositor=off"])
        session.launch("atspi", ["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"])
        thunar = None
        for name in APPLICATIONS:
            if name in skip:
                print(f"SKIP {name}: explicitly excluded by --skip", flush=True)
                continue
            if name == "vscode":
                available = desktop_code_binary()
            else:
                available = shutil.which(BINARIES[name])
            if not available:
                raise RuntimeError(f"Required {name} desktop binary unavailable; explicitly use --skip {name}")
            if name == "thunar":
                thunar = thunar_check(session)
            elif name == "mousepad":
                mousepad_check(session, thunar)
            else:
                checks = {"settings": settings_check, "terminal": terminal_check,
                          "calendar": calendar_check, "firefox": firefox_check, "vscode": vscode_check}
                checks[name](session)
        print(json.dumps({"status": "PASS", "checks": len(session.checks), "skipped": sorted(skip),
                          "event_count": len(session.events)}, sort_keys=True), flush=True)
        return 0
    except Exception:
        for node in walk(session.Atspi.get_desktop(0)):
            try:
                role, name = node.get_role_name(), node.get_name()
                if session.state(node, "FOCUSED") or role in {"application", "entry", "autocomplete"}:
                    print(f"AT-SPI {role} {name!r} focused={session.state(node, 'FOCUSED')}", file=sys.stderr)
            except session.GLib.Error:
                continue
        for log in sorted(root.glob("*.log")):
            print(f"--- {log.name} ---\n{log.read_text(errors='replace')[-3000:]}", file=sys.stderr)
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip", choices=APPLICATIONS, action="append", default=[],
                        help="explicitly omit unavailable optional desktop applications")
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inner:
        return run_inner(set(args.skip))
    with tempfile.TemporaryDirectory(prefix="lrd-real-gui-") as temporary:
        env = isolated_environment(Path(temporary))
        command = ["xvfb-run", "-a", "-s", "-screen 0 1280x900x24", "dbus-run-session", "--",
                   sys.executable, str(Path(__file__).resolve()), "--inner"]
        for app in args.skip:
            command.extend(["--skip", app])
        return subprocess.call(command, env=env)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
