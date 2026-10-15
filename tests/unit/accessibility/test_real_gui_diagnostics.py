"""Isolation and traversal regressions for the real-application GUI runner."""
from pathlib import Path
from collections import deque
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools.diagnostics import real_gui_atspi_smoke as smoke


class Accessible:
    def __init__(self, *children):
        self.children = list(children)

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]

    def get_process_id(self):
        return 17

    def get_role_name(self):
        return "text"

    def get_name(self):
        return ""


class RealGuiDiagnosticTests(unittest.TestCase):
    def continuation_fixture(self, model_caret):
        state = {"model": model_caret, "visible": 1, "keys": []}
        text = SimpleNamespace(get_caret_offset=lambda: state["visible"])
        node = SimpleNamespace(get_text_iface=lambda: text)
        session = smoke.Session.__new__(smoke.Session)

        def key(name):
            state["keys"].append(name)
            state["model"] += 1 if name == "Right" else -1
            state["visible"] = state["model"]

        def wait(predicate, label):
            if not predicate():
                raise AssertionError(label)

        session.key = key
        session.wait = wait
        session.check = lambda label: None
        return session, node, state

    def test_routed_caret_continuation_checks_model_right_and_left(self):
        session, node, state = self.continuation_fixture(1)
        session.verify_routed_caret_continuation(node, 1)
        self.assertEqual(state["keys"], ["Right", "Left"])
        self.assertEqual(state["visible"], 1)

    def test_routed_caret_readback_alone_cannot_hide_stale_editor_model(self):
        session, node, state = self.continuation_fixture(12)
        with self.assertRaisesRegex(AssertionError, "Right=2"):
            session.verify_routed_caret_continuation(node, 1)
        self.assertEqual(state["visible"], 13)
        self.assertEqual(state["keys"], ["Right"], "No routing retry or extra key after failure")

    def test_routed_caret_events_are_target_only_and_relative_to_the_request(self):
        target, other = object(), object()
        events = [(9.0, 12, target), (10.01, 7, other), (10.02, 1, target), (10.07, 12, target)]
        self.assertEqual(smoke.routed_caret_events(events, target, 10.0), [(20.0, 1), (70.0, 12)])

    def test_routed_caret_events_are_bounded_without_reading_labels_or_text(self):
        class PrivateNode:
            def get_name(self):
                raise AssertionError("Diagnostics must not access private labels")

            def get_text_iface(self):
                raise AssertionError("Diagnostics must not access private text")

        node = PrivateNode()
        events = [(float(index), index, node) for index in range(30)]
        self.assertEqual(smoke.routed_caret_events(events, node, 0.0),
                         [(float(index * 1000), index) for index in range(20, 30)])

    def test_caret_timestamps_are_recorded_only_for_caret_events_and_bounded(self):
        session = smoke.Session.__new__(smoke.Session)
        session.events = []
        session.caret_events = deque(maxlen=80)
        session.GLib = SimpleNamespace(Error=RuntimeError)
        source = object()
        event = SimpleNamespace(type="object:text-caret-moved", detail1=1, source=source)
        with patch.object(smoke.time, "monotonic", return_value=123.0):
            for index in range(100):
                event.detail1 = index
                session.on_event(event)
            event.type = "object:state-changed:focused"
            session.on_event(event)
        self.assertEqual(len(session.events), 101)
        self.assertEqual(list(session.caret_events), [(123.0, index, source) for index in range(20, 100)])

    def test_walk_keeps_equally_named_sibling_controls_and_their_children(self):
        leaf = Accessible()
        first, second = Accessible(), Accessible(leaf)
        root = Accessible(first, second)
        self.assertEqual(list(smoke.walk(root)), [root, first, second, leaf])

    def test_walk_stops_a_proxy_cycle(self):
        root, child = Accessible(), Accessible()
        root.children = [child]
        child.children = [root]
        self.assertEqual(list(smoke.walk(root)), [root, child])

    def test_inner_rejects_an_active_desktop_bus_before_changing_a11y_status(self):
        env = dict(LRD_GUI_PRIVATE="/tmp/lrd-real-gui-owned", DISPLAY=":123",
                   XDG_RUNTIME_DIR="/tmp/lrd-real-gui-owned/runtime")
        owned = b"\0".join((key + "=" + value).encode() for key, value in env.items())
        smoke.verify_private_bus_environment(owned, env)
        desktop = b"DISPLAY=:0\0XDG_RUNTIME_DIR=/run/user/1000\0"
        with self.assertRaisesRegex(RuntimeError, "outside the private Xvfb"):
            smoke.verify_private_bus_environment(desktop, env)
        mismatched = dict(env, XDG_RUNTIME_DIR="/run/user/1000")
        with self.assertRaisesRegex(RuntimeError, "runtime directory"):
            smoke.verify_private_bus_environment(owned, mismatched)

    def test_focused_descendant_wins_over_focused_container(self):
        control = Accessible()
        container = Accessible(control)
        root = Accessible(container)
        session = smoke.Session.__new__(smoke.Session)
        session.state = lambda node, _state: node in (container, control)
        self.assertIs(session.focused(root), control)

    def test_environment_removes_desktop_bus_and_editor_ipc_before_launch(self):
        inherited = dict(AT_SPI_BUS_ADDRESS="unix:path=/active-atspi",
                         DBUS_SESSION_BUS_ADDRESS="unix:path=/active-dbus",
                         WAYLAND_DISPLAY="wayland-0", SESSION_MANAGER="desktop-session",
                         VSCODE_IPC_HOOK_CLI="/active-code.sock", NO_AT_BRIDGE="1",
                         ELECTRON_RUN_AS_NODE="1", DISPLAY=":0")
        with tempfile.TemporaryDirectory() as directory:
            env = smoke.isolated_environment(Path(directory), inherited)
            for key in inherited.keys() - {"DISPLAY"}:
                self.assertNotIn(key, env)
            self.assertEqual(env["GSETTINGS_BACKEND"], "memory")
            self.assertEqual(env["GVFS_DISABLE_FUSE"], "1")
            for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
                self.assertEqual(Path(env[key]).parent, Path(directory))
                self.assertEqual(Path(env[key]).stat().st_mode & 0o777, 0o700)
        self.assertEqual(inherited["AT_SPI_BUS_ADDRESS"], "unix:path=/active-atspi")

    def test_focus_waits_for_a_mapped_realized_component_before_grabbing_focus(self):
        ready = {"showing": False, "focused": False}
        extents = SimpleNamespace(width=0, height=24, x=30, y=40)
        grabbed = []

        def grab_focus():
            grabbed.append((ready["showing"], extents.width))
            self.assertTrue(ready["showing"], "native focus must not target an unmapped widget")
            self.assertGreater(extents.width, 0, "native focus must wait for realized geometry")
            ready["focused"] = True
            return True

        component = SimpleNamespace(get_extents=lambda _coordinates: extents, grab_focus=grab_focus)
        node = SimpleNamespace(get_component_iface=lambda: component)
        session = smoke.Session.__new__(smoke.Session)
        session.Atspi = SimpleNamespace(CoordType=SimpleNamespace(SCREEN=0))
        session.state = lambda _node, state: ready["focused"] if state == "FOCUSED" else ready["showing"]
        session.showing = lambda _node: ready["showing"]

        def wait_until_ready(predicate, label):
            for _attempt in range(3):
                result = predicate()
                if result:
                    return result
                if not ready["showing"]:
                    ready["showing"] = True
                else:
                    extents.width = 100
            self.fail("readiness never established: " + label)

        session.wait = wait_until_ready
        session.focus(node)
        self.assertEqual(grabbed, [(True, 100)])
        self.assertTrue(ready["focused"])

    def test_desktop_code_uses_owned_native_executable_instead_of_detached_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            cli = root / "bin/code"
            native = root / "code"
            cli.write_text("#!/bin/sh\n")
            cli.chmod(0o700)
            native.write_text("native executable fixture")
            native.chmod(0o700)
            with patch.object(smoke.shutil, "which", return_value=str(cli)):
                self.assertEqual(smoke.desktop_code_binary(), str(native))

    def test_code_remote_cli_is_never_treated_as_local_desktop(self):
        with patch.object(smoke.shutil, "which", return_value="/tmp/.vscode-server/bin/remote-cli/code"), \
                patch.object(Path, "is_file", return_value=False):
            self.assertIsNone(smoke.desktop_code_binary())


if __name__ == "__main__":
    unittest.main()
