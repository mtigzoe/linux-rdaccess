"""Regression tests for injection backend ownership and failure recovery."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import logging
import os
import types
from unittest import mock

import remote_access
from tests.test_compat_lifecycle import Harness
from tests import test_remote_access as fixtures


class XTestOwnershipTests(Harness, unittest.TestCase):
    def test_legacy_backend_exception_log_does_not_persist_private_text(self):
        self.addCleanup(logging.disable, logging.root.manager.disable)
        logging.disable(logging.NOTSET)
        source = self.UPSTREAM_LOCAL.replace('class LocalMachine:', '''import logging
log = logging.getLogger(__name__)
class LocalMachine:
    def failing_speech(self):
        try:
            raise ValueError("private remote speech")
        except Exception:
            log.exception("Failed to speak remote text")
''')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'local_machine.py'
            path.write_text(source)
            remote_access.patch_legacy_orca_local_machine(path)
            module = types.ModuleType('private_backend')
            exec(path.read_text(), module.__dict__)
        with self.assertLogs(module.log, level='ERROR') as logs:
            module.LocalMachine().failing_speech()
        self.assertNotIn('private remote speech', '\n'.join(logs.output))

    def test_local_send_key_exposes_backend_result_to_controller(self):
        source = self.UPSTREAM_LOCAL.replace('    @staticmethod\n', '''    def send_key(self, key_name=None, pressed=None, modifiers=None,
                 vk_code=None, scan_code=None, extended=None, **kwargs):
        if pressed is None:
            return
        key = self._resolve_key(key_name, vk_code, extended)
        if key is None:
            return
        if self._send_key_xdotool(key, pressed):
            return

    @staticmethod
''')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'local_machine.py'
            path.write_text(source)
            remote_access.patch_legacy_orca_local_machine(path)
            module = types.ModuleType('local_results')
            exec(path.read_text(), module.__dict__)
            machine = module.LocalMachine()
            machine._send_key_xdotool = lambda *args: False
            self.assertIs(machine.send_key(vk_code=0x28, extended=True, pressed=True), False)
            machine._send_key_xdotool = lambda *args: True
            self.assertIs(machine.send_key(vk_code=0x28, extended=True, pressed=True), True)

    def helper(self, *, results=(1, 1), flush_error=False):
        module, _, _ = self._patched_local()
        events = []
        answers = iter(results)
        helper = module._LrdXTest()
        helper._dpy = object()
        helper._x11 = types.SimpleNamespace(
            XStringToKeysym=lambda name: 1,
            XKeysymToKeycode=lambda *args: 38,
            XFlush=mock.Mock(side_effect=OSError('flush failed') if flush_error else None))

        def inject(display, code, pressed, delay):
            events.append((code, pressed))
            return next(answers)

        helper._xt = types.SimpleNamespace(XTestFakeKeyEvent=inject)
        return helper, events

    def test_fallback_press_owns_repeat_and_release(self):
        helper, events = self.helper(results=(0, 1, 1))
        self.assertFalse(helper.key('a', True))
        self.assertFalse(helper.key('a', True))
        self.assertFalse(helper.key('a', False))
        self.assertEqual(events, [(38, 1)])
        self.assertTrue(helper.key('a', True))  # fresh gesture retries fast path

    def test_flush_exception_after_injection_never_replays_event_in_fallback(self):
        helper, events = self.helper(flush_error=True)
        self.assertTrue(helper.key('a', True))
        self.assertTrue(helper.key('a', False))
        self.assertEqual(events, [(38, 1), (38, 0)])
        self.assertEqual(helper._down_codes, {})

    def test_initial_display_failure_retries_only_when_environment_changes(self):
        module, _, _ = self._patched_local()
        helper = module._LrdXTest()
        calls = []

        def open_display():
            calls.append(os.environ['DISPLAY'])
            if len(calls) == 1:
                raise OSError('display unavailable')
            helper._dpy = object()
            helper._x11 = types.SimpleNamespace(XStringToKeysym=lambda name: 1,
                XKeysymToKeycode=lambda *args: 38, XFlush=lambda *args: None)
            helper._xt = types.SimpleNamespace(XTestFakeKeyEvent=lambda *args: 1)

        helper._open = open_display
        with mock.patch.dict(os.environ, {'DISPLAY': ':99'}):
            self.assertFalse(helper.key('a', True))
            self.assertFalse(helper.key('a', False))
            self.assertFalse(helper.key('b', True))
            self.assertFalse(helper.key('b', False))
            self.assertEqual(calls, [':99'])
            os.environ['DISPLAY'] = ':100'
            self.assertTrue(helper.key('c', True))
        self.assertEqual(calls, [':99', ':100'])
