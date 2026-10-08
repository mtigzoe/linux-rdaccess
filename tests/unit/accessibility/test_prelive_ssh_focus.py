"""Regressions found while reviewing SSH startup and the semantic focus bridge."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import linux_rdaccess
from a11y_model import build_focus_payload, find_focused_object_ex
from tests.bridge_stubs import GLibError, import_braille_bridge
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeValue
from tests.unit.accessibility.test_a11y_model_bounds import Node
from tests.unit.accessibility.test_bridge_focus_resync import FakeA11yLink, SpeechLink


bridge = import_braille_bridge()


class SemanticValueTests(unittest.TestCase):
    def test_integer_zero_is_preserved_as_the_controls_value(self):
        slider = FakeAccessible("Volume", "slider", value_iface=FakeValue(current=0))
        payload = build_focus_payload("object:state-changed:focused", 1, slider)
        self.assertEqual(payload["objects"][0]["value"], "0")


class GraphicalSessionTests(unittest.TestCase):
    @staticmethod
    def session(root, environment):
        entry = root / "100"
        entry.mkdir()
        (entry / "comm").write_text("xfce4-session\n", encoding="utf-8")
        (entry / "status").write_text("Uid:\t1000\t1000\t1000\t1000\n", encoding="utf-8")
        (entry / "environ").write_bytes(
            b"\0".join(f"{key}={value}".encode() for key, value in environment.items())
        )

    def test_discovered_desktop_does_not_inherit_ssh_xauthority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.session(root, {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/desktop/bus",
                                "XDG_RUNTIME_DIR": "/run/user/1000"})
            env = linux_rdaccess.graphical_session_env(
                proc_root=root,
                base_env={"PATH": "/usr/bin", "DISPLAY": "localhost:10.0",
                          "XAUTHORITY": "/tmp/ssh-forwarding-auth"},
                uid=1000,
            )
        self.assertEqual(env["DISPLAY"], ":0")
        self.assertNotIn("XAUTHORITY", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_discovered_wayland_session_does_not_keep_forwarded_x11_display(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.session(root, {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland",
                                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/desktop/bus",
                                "XDG_RUNTIME_DIR": "/run/user/1000"})
            env = linux_rdaccess.graphical_session_env(
                proc_root=root,
                base_env={"PATH": "/usr/bin", "DISPLAY": "localhost:10.0", "XDG_SESSION_TYPE": "tty"},
                uid=1000,
            )
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-0")
        self.assertNotIn("DISPLAY", env)
        self.assertEqual(env["XDG_SESSION_TYPE"], "wayland")

    def test_complete_ssh_environment_still_discovers_the_local_desktop(self):
        for display in ("localhost:10.0", "127.0.0.1:11", "[::1]:12.0"):
            with self.subTest(display=display), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.session(root, {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/desktop/bus",
                                    "XDG_RUNTIME_DIR": "/run/user/1000", "XDG_SESSION_TYPE": "x11"})
                env = linux_rdaccess.graphical_session_env(
                    proc_root=root,
                    base_env={"PATH": "/usr/bin", "DISPLAY": display,
                              "DBUS_SESSION_BUS_ADDRESS": "unix:path=/ssh/bus",
                              "XDG_RUNTIME_DIR": "/run/user/1000", "XDG_SESSION_TYPE": "tty",
                              "XAUTHORITY": "/tmp/ssh-auth", "AT_SPI_BUS_ADDRESS": "unix:path=/ssh/a11y"},
                    uid=1000,
                )
                self.assertEqual(env["DISPLAY"], ":0")
                self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/desktop/bus")
                self.assertEqual(env["XDG_SESSION_TYPE"], "x11")
                self.assertNotIn("XAUTHORITY", env)
                self.assertNotIn("AT_SPI_BUS_ADDRESS", env)
                self.assertEqual(env["PATH"], "/usr/bin")

    def test_discovery_uses_the_selected_desktops_accessibility_bus(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.session(root, {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/desktop/bus",
                                "XDG_RUNTIME_DIR": "/run/user/1000",
                                "AT_SPI_BUS_ADDRESS": "unix:path=/desktop/a11y"})
            env = linux_rdaccess.graphical_session_env(
                proc_root=root, base_env={"AT_SPI_BUS_ADDRESS": "unix:path=/ssh/a11y"}, uid=1000,
            )
        self.assertEqual(env["AT_SPI_BUS_ADDRESS"], "unix:path=/desktop/a11y")

    def test_unavailable_local_desktop_preserves_forwarded_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            base = {"DISPLAY": "localhost:10.0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/ssh/bus",
                    "XDG_RUNTIME_DIR": "/run/user/1000", "AT_SPI_BUS_ADDRESS": "unix:path=/ssh/a11y"}
            env = linux_rdaccess.graphical_session_env(proc_root=Path(temp), base_env=base, uid=1000)
        self.assertEqual(env, base)


class FocusQueryFailureTests(unittest.TestCase):
    def test_failed_child_count_does_not_mean_nothing_is_focused(self):
        desktop = Node("desktop")
        with mock.patch.object(desktop, "get_child_count", side_effect=GLibError("unavailable")):
            self.assertEqual(find_focused_object_ex(desktop), (None, False))

    def test_failed_child_proxy_does_not_mean_nothing_is_focused(self):
        desktop = Node("desktop", kids=[Node("app", kids=[Node("window")])])
        with mock.patch.object(desktop, "get_child_at_index", side_effect=GLibError("unavailable")):
            self.assertEqual(find_focused_object_ex(desktop), (None, False))

    def test_failed_state_query_does_not_mean_nothing_is_focused(self):
        window = Node("window")
        desktop = Node("desktop", kids=[Node("app", kids=[window])])
        with mock.patch.object(window, "get_state_set", side_effect=GLibError("unavailable")):
            self.assertEqual(find_focused_object_ex(desktop), (None, False))

    def test_reconnect_keeps_cached_focus_when_the_desktop_query_fails(self):
        link = FakeA11yLink()
        instance = bridge.Bridge(SpeechLink(), a11y_link=link)
        desktop = Node("desktop")
        with mock.patch.object(bridge.Atspi, "get_desktop", return_value=desktop), mock.patch.object(
            desktop, "get_child_count", side_effect=GLibError("unavailable")
        ):
            instance.resync_focus()
        self.assertEqual((link.cleared, link.refreshed), (0, []))


class FocusTargetTests(unittest.TestCase):
    def test_focused_descendant_wins_over_its_focused_ancestors(self):
        target = Node("checkbox", "focused")
        panel = Node("panel", "focused", role="panel", kids=[target])
        frame = Node("frame", "active", "focused", role="frame", kids=[panel])
        desktop = Node("desktop", kids=[Node("app", kids=[frame])])
        self.assertEqual(find_focused_object_ex(desktop), (target, True))

    def test_active_window_control_wins_over_a_window_managers_focused_window(self):
        manager_window = Node("", "active", "focused", role="window")
        target = Node("checkbox", "focused")
        frame = Node("application", "active", role="frame", kids=[target])
        desktop = Node("desktop", kids=[Node("xfwm4", kids=[manager_window]), Node("app", kids=[frame])])
        self.assertEqual(find_focused_object_ex(desktop), (target, True))

    def test_active_window_fallback_wins_over_an_inactive_windows_control(self):
        active = Node("active", "active", "focused", role="frame")
        inactive = Node("inactive", role="frame", kids=[Node("old control", "focused")])
        desktop = Node("desktop", kids=[Node("app", kids=[inactive, active])])
        self.assertEqual(find_focused_object_ex(desktop), (active, True))

    def test_cached_top_level_window_does_not_bypass_the_current_control_search(self):
        previous = Node("", "focused", role="window")
        target = Node("checkbox", "focused")
        link = FakeA11yLink(last_focus_id=bridge.object_id(previous))
        instance = bridge.Bridge(SpeechLink(), a11y_link=link)
        instance._a11y_objects[bridge.object_id(previous)] = previous
        with mock.patch.object(bridge, "is_focused", return_value=True), mock.patch.object(
            bridge, "find_focused_object_ex", return_value=(target, True)
        ) as search:
            instance.resync_focus()
        search.assert_called_once()
        self.assertEqual(link.refreshed[0]["focus_id"], bridge.object_id(target))


if __name__ == "__main__":
    unittest.main()
