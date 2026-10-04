"""Integration test for low-latency key injection; needs a real X server.

Skipped unless DISPLAY is set and libX11/libXtst load. CI runs it under
``xvfb-run``.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from pathlib import Path
import tempfile
import time
import types
import unittest

import remote_access

UPSTREAM = '''import os, time
def _dbg(msg):
    pass

class LocalMachine:
    def _send_key_xdotool(self, key, pressed):
        raise AssertionError("fell back to the xdotool process")

    @staticmethod
    def _resolve_key(key_name, vk_code, extended):
        return key_name or {0x28: "Down"}.get(vk_code)
'''


def _x_available() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        return bool(x11.XOpenDisplay(None))
    except OSError:
        return False


@unittest.skipUnless(_x_available(), "needs an X server (run under xvfb-run)")
class XTestInjectionTests(unittest.TestCase):
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

    def test_keys_really_reach_the_server_without_a_subprocess(self):
        for name in ("Down", "KP_Add", "KP_Enter", "KP_Up", "Insert"):
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
