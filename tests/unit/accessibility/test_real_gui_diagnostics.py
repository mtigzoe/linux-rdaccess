"""Isolation and traversal regressions for the real-application GUI runner."""
from pathlib import Path
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
