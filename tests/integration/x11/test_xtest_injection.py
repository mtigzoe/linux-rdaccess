"""Integration test for low-latency key injection; needs a real X server.

Skipped unless DISPLAY points to a private Xvfb server and libX11/libXtst load. CI runs it under
``xvfb-run``.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest import mock

import remote_access
from tests.test_compat_lifecycle import Harness

UPSTREAM = '''import os, time
def _dbg(msg):
    pass

class LocalMachine:
    def send_key(self, key_name=None, pressed=None, vk_code=None, extended=None):
        key = self._resolve_key(key_name, vk_code, extended)
        if self._send_key_xdotool(key, pressed):
            return

    def _send_key_xdotool(self, key, pressed):
        raise AssertionError("fell back to the xdotool process")

    @staticmethod
    def _resolve_key(key_name, vk_code, extended):
        return key_name or {0x28: "Down", 0x2D: "Insert", 0x59: "y", 0x4A: "j"}.get(vk_code)
'''


def _x_available() -> bool:
    display = re.fullmatch(r":(\d+)(?:\.\d+)?", os.environ.get("DISPLAY", ""))
    if not display:
        return False
    try:
        pid = int(Path(f"/tmp/.X{display[1]}-lock").read_text().strip())
        if Path(f"/proc/{pid}/comm").read_text().strip() != "Xvfb":
            return False
        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        return bool(x11.XOpenDisplay(None))
    except (OSError, ValueError):
        return False


class XTestDisplaySafetyTests(unittest.TestCase):
    def test_regular_desktop_is_rejected_before_loading_x11(self):
        with mock.patch.dict(os.environ, DISPLAY=":42"), \
             mock.patch.object(Path, "read_text", side_effect=["123", "Xorg\n"]), \
             mock.patch.object(ctypes, "CDLL") as load:
            self.assertFalse(_x_available())
            load.assert_not_called()

    def test_unverifiable_display_is_rejected_before_loading_x11(self):
        with mock.patch.dict(os.environ, DISPLAY=":42"), \
             mock.patch.object(Path, "read_text", side_effect=FileNotFoundError), \
             mock.patch.object(ctypes, "CDLL") as load:
            self.assertFalse(_x_available())
            load.assert_not_called()


@unittest.skipUnless(_x_available(), "needs a private Xvfb server (run under xvfb-run)")
class XTestInjectionTests(Harness, unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "local_machine.py"
        path.write_text(UPSTREAM, encoding="utf-8")
        remote_access.patch_legacy_orca_local_machine(path)
        self.module = types.ModuleType("xtest_lm")
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), self.module.__dict__)
        self.machine = self.module.LocalMachine()
        self.x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.x11.XStringToKeysym.restype = ctypes.c_ulong
        self.x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.observer = self.x11.XOpenDisplay(None)

    def _is_down(self, name: str) -> bool:
        code = self.x11.XKeysymToKeycode(self.observer, self.x11.XStringToKeysym(name.encode()))
        buf = ctypes.create_string_buffer(32)
        self.x11.XQueryKeymap(self.observer, buf)
        return bool(buf.raw[code // 8] & (1 << (code % 8)))

    def test_complete_send_key_retains_failed_release_until_retry(self):
        self.assertTrue(self.machine.send_key(key_name='Down', pressed=True))
        time.sleep(0.02)
        self.assertTrue(self._is_down('Down'))
        helper = self.module._LRD_XTEST
        original_code = helper._down_codes['Down']
        with mock.patch.object(helper._xt, 'XTestFakeKeyEvent', return_value=0):
            with self.assertRaises(AssertionError):
                self.machine.send_key(key_name='Down', pressed=False)
        self.assertEqual(helper._down_codes['Down'], original_code)
        self.assertTrue(self._is_down('Down'))
        self.assertTrue(self.machine.send_key(key_name='Down', pressed=False))
        time.sleep(0.02)
        self.assertFalse(self._is_down('Down'))
        self.assertNotIn('Down', helper._down_codes)

    def test_controller_retries_failed_insert_before_next_chord_key(self):
        controller, _, _ = self._patched_controller()
        controller.local_machine = self.machine
        self.machine.cancel_speech = lambda: None
        original_send = self.machine.send_key
        observations = []
        helper = self.module._LRD_XTEST

        def send(**payload):
            if payload['vk_code'] == 0x4A and payload['pressed']:
                helper._x11.XSync(helper._dpy, 0)
                observations.append(self._is_down('Insert'))
            return original_send(**{
                field: payload.get(field)
                for field in ('key_name', 'pressed', 'vk_code', 'extended')
            })

        self.machine.send_key = send
        self.addCleanup(controller._linux_rdaccess_reset_keys)
        self._key(controller, 0x2D, True, extended=True)
        # Open the real backend, then reject one native press. The fixture's
        # fallback raises, reproducing a complete unsuccessful Insert replay.
        helper._open()
        with mock.patch.object(helper._xt, 'XTestFakeKeyEvent', return_value=0):
            self._key(controller, 0x59, True)
            self._key(controller, 0x59, False)
        helper._x11.XSync(helper._dpy, 0)
        self.assertFalse(self._is_down('Insert'))
        self.assertFalse(self._is_down('y'))
        self.assertEqual(controller._lrd_forwarded, {})

        self._key(controller, 0x4A, True)
        helper._x11.XSync(helper._dpy, 0)
        self.assertEqual(observations, [True])
        self.assertTrue(self._is_down('j'))
        self.assertEqual(set(controller._lrd_forwarded), {(0x2D, True), (0x4A, False)})
        self._key(controller, 0x4A, False)
        self._key(controller, 0x2D, False, extended=True)
        helper._x11.XSync(helper._dpy, 0)
        self.assertFalse(self._is_down('Insert'))
        self.assertFalse(self._is_down('j'))
        self.assertEqual(helper._down_codes, {})
        self.assertEqual(controller._lrd_forwarded, {})

    def test_keys_really_reach_the_server_without_a_subprocess(self):
        for name in ("Down", "KP_Add", "KP_Enter", "KP_End", "KP_Down",
                     "KP_Next", "KP_Left", "KP_Begin", "KP_Right",
                     "KP_Home", "KP_Up", "KP_Prior", "KP_Delete", "KP_Insert",
                     "Shift_L", "Control_L", "Alt_L", "Super_L", "Insert", "Scroll_Lock"):
            with self.subTest(key=name):
                self.assertTrue(self.machine._send_key_xdotool(name, True))
                time.sleep(0.02)
                self.assertTrue(self._is_down(name))
                self.assertTrue(self.machine._send_key_xdotool(name, False))
                time.sleep(0.02)
                self.assertFalse(self._is_down(name))

    def test_unknown_keysym_falls_back_instead_of_injecting_garbage(self):
        with self.assertRaises(AssertionError):
            self.machine._send_key_xdotool("NotARealKeysymName", True)

    def test_same_vk_keypad_and_navigation_keys_have_independent_releases(self):
        resolve = self.machine._resolve_key
        arrow = resolve(None, 0x28, True)
        keypad = resolve(None, 0x28, False)
        self.machine._send_key_xdotool(arrow, True)
        self.machine._send_key_xdotool(keypad, True)
        self.addCleanup(self.machine._send_key_xdotool, keypad, False)
        self.addCleanup(self.machine._send_key_xdotool, arrow, False)
        time.sleep(0.02)
        self.assertTrue(self._is_down('Down'))
        self.assertTrue(self._is_down('KP_Down'))
        self.machine._send_key_xdotool(arrow, False)
        time.sleep(0.02)
        self.assertFalse(self._is_down('Down'))
        self.assertTrue(self._is_down('KP_Down'))
        self.machine._send_key_xdotool(keypad, False)
        time.sleep(0.02)
        self.assertFalse(self._is_down('KP_Down'))

    def test_injection_is_far_faster_than_a_process_per_event(self):
        start = time.perf_counter()
        for _ in range(200):
            self.machine._send_key_xdotool("Down", True)
            self.machine._send_key_xdotool("Down", False)
        per_keystroke_ms = (time.perf_counter() - start) * 1000 / 200
        # upstream's xdotool-per-event path measures ~76 ms per keystroke
        self.assertLess(per_keystroke_ms, 5.0)


if __name__ == "__main__":
    unittest.main()
