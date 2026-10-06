"""Real XKB regression checks for completed remote lock-key gestures.

Run with ``xvfb-run -a python3 -m unittest tests.test_lock_toggle_integration``.
The server must be Xvfb: these tests never inject into a desktop X server.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

import orca_adapter
import remote_access
from diagnostics.live_x11 import Xkb
from tests import test_remote_access as fixtures
from tests.test_xtest_injection import UPSTREAM


def _isolated_xvfb() -> bool:
    display = re.fullmatch(r":(\d+)(?:\.\d+)?", os.environ.get("DISPLAY", ""))
    if not display:
        return False
    try:
        pid = int(Path(f"/tmp/.X{display[1]}-lock").read_text().strip())
        return Path(f"/proc/{pid}/comm").read_text().strip() == "Xvfb"
    except (OSError, ValueError):
        return False


@unittest.skipUnless(_isolated_xvfb(), "requires an isolated Xvfb server")
class LockToggleIntegrationTests(unittest.TestCase):
    LOCKS = ((0x14, "Caps_Lock", "Caps Lock"), (0x90, "Num_Lock", "Num Lock"))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        # Use the same upstream send_key/backend shape as the installed addon,
        # including the full payload passed by RemoteController.
        local_source = UPSTREAM.replace(
            "pressed=None, vk_code=None, extended=None",
            "pressed=None, modifiers=None, vk_code=None, scan_code=None, extended=None",
        )
        self.local = self._load(
            local_source, root / "local_machine.py", remote_access.patch_legacy_orca_local_machine
        )
        controller_module = self._load(
            fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER,
            root / "remote_controller.py",
            remote_access.patch_legacy_orca_remote_controller,
        )
        self.machine = self.local.LocalMachine()
        self.machine.cancel_speech = lambda: None
        self.controller = controller_module.RemoteController()
        self.controller.transport = fixtures.LegacyConfigTests.FakeTransport()
        self.controller.local_machine = self.machine

        self.xkb = Xkb(os.environ["DISPLAY"])
        self.addCleanup(self.xkb.close)
        self.initial = {name: self._state(name) for _, _, name in self.LOCKS}
        self.addCleanup(self._restore)
        for _, key, name in self.LOCKS:
            if self._state(name):
                self._physical_gesture(key)

        self.messages = []
        self.commands = []
        script = types.SimpleNamespace(
            presentMessage=self.messages.append,
            presentTitle=lambda event: self.commands.append("title"),
        )
        adapter = mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": orca_adapter})
        adapter.start()
        self.addCleanup(adapter.stop)
        active_script = mock.patch.object(
            orca_adapter.OrcaRuntimeAdapter, "active_script", return_value=script
        )
        active_script.start()
        self.addCleanup(active_script.stop)

        self.queue = []
        gi, repository = types.ModuleType("gi"), types.ModuleType("gi.repository")

        def idle_add(callback):
            self.queue.append(callback)
            return len(self.queue)

        repository.GLib = types.SimpleNamespace(idle_add=idle_add)
        gi.repository = repository
        glib = mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository})
        glib.start()
        self.addCleanup(glib.stop)

    @staticmethod
    def _load(source, path, patch):
        path.write_text(source, encoding="utf-8")
        patch(path)
        module = types.ModuleType(path.stem)
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        return module

    def _state(self, name):
        indicator = self.xkb.snapshot()[name]
        self.assertTrue(indicator["available"])
        return indicator["on"]

    def _physical_gesture(self, key):
        self.assertTrue(self.machine.send_key(key_name=key, pressed=True))
        self.assertTrue(self.machine.send_key(key_name=key, pressed=False))

    def _key(self, vk, pressed):
        self.controller._on_remote_key(
            key_name=None, pressed=pressed, modifiers=None, vk_code=vk,
            scan_code=0, extended=False,
        )

    def _drain(self):
        while self.queue:
            self.queue.pop(0)()

    def _restore(self):
        helper = self.local._LRD_XTEST
        for key in tuple(helper._down_codes):
            self.machine.send_key(key_name=key, pressed=False)
        for _, key, name in self.LOCKS:
            if self._state(name) != self.initial[name]:
                self._physical_gesture(key)
        if helper._dpy:
            helper._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            helper._x11.XCloseDisplay(helper._dpy)
            helper._dpy = None

    def test_xkb_turns_off_only_after_the_second_release(self):
        for _, key, name in self.LOCKS:
            with self.subTest(key=key):
                self.assertFalse(self._state(name))
                self.assertTrue(self.machine.send_key(key_name=key, pressed=True))
                self.assertTrue(self._state(name))
                self.assertTrue(self.machine.send_key(key_name=key, pressed=False))
                self.assertTrue(self._state(name))
                self.assertTrue(self.machine.send_key(key_name=key, pressed=True))
                self.assertTrue(self._state(name))  # Unlock action is not final yet.
                self.assertTrue(self.machine.send_key(key_name=key, pressed=False))
                self.assertFalse(self._state(name))

    def test_controller_announces_completed_release_and_consumes_repeats(self):
        for vk, key, name in self.LOCKS:
            with self.subTest(key=key):
                self.messages.clear()
                for expected, prior_messages in ((True, []), (False, [f"{name} on"])):
                    self._key(vk, True)
                    self._key(vk, True)
                    self._key(vk, True)
                    self._drain()  # Orca becomes idle while the remote key is held.
                    self.assertEqual(self.messages, prior_messages)
                    self._key(vk, False)
                    self.assertEqual(self._state(name), expected)
                    self._drain()
                self.assertEqual(self.messages, [f"{name} on", f"{name} off"])
                self.assertFalse(self.local._LRD_XTEST._down_codes)
                self.assertFalse(self.controller._lrd_forwarded)

    def test_queued_rapid_toggles_present_each_completed_gestures_snapshot(self):
        for vk, key, name in self.LOCKS:
            with self.subTest(key=key):
                self.messages.clear()
                for _ in range(2):
                    self._key(vk, True)
                    self._key(vk, False)
                self.assertFalse(self._state(name))
                self.assertEqual(self.messages, [])
                # The original state is already off by the time Orca can run.
                # Both queued utterances must retain their gesture's snapshot.
                self._drain()
                self.assertEqual(self.messages, [f"{name} on", f"{name} off"])

    def test_caps_lock_nvda_command_preserves_the_real_lock(self):
        for expected in (False, True):
            with self.subTest(caps_lock_on=expected):
                if self._state("Caps Lock") != expected:
                    self._physical_gesture("Caps_Lock")
                self._key(0x14, True)
                self._key(0x54, True)
                self._key(0x54, False)
                self._key(0x14, False)
                self._drain()
                self.assertEqual(self._state("Caps Lock"), expected)
                self.assertEqual(self.messages, [])
        self.assertEqual(self.commands, ["title", "title"])


if __name__ == "__main__":
    unittest.main()
