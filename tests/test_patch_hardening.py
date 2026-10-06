"""Source-transformer and installed-patch integrity regressions."""
from __future__ import annotations

from pathlib import Path
import tempfile
import logging
import unittest

import remote_access
from tests import test_remote_access as fixtures


class LocalResultTransformerTests(unittest.TestCase):
    def source(self, body, *, decorator=''):
        return ('class LocalMachine:\n' + decorator +
                '    def send_key(self, vk_code=None, pressed=None):\n' + body +
                '\n    def _send_key_xdotool(self, key, pressed):\n'
                '        return True\n'
                '\n    def _send_key_ydotool(self, key, pressed):\n'
                '        return False\n')

    def machine(self, source):
        namespace = {}
        exec(remote_access._patch_local_key_results(source), namespace)
        return namespace['LocalMachine']()

    def test_explicit_none_return_exposes_verified_backend_success(self):
        machine = self.machine(self.source(
            '        if self._send_key_xdotool(vk_code, pressed):\n'
            '            return None  # legacy success\n'))
        self.assertIs(machine.send_key(0x41, True), True)

    def test_nested_returns_in_a_success_branch_report_success(self):
        machine = self.machine(self.source(
            '        if self._send_key_xdotool(vk_code, pressed):\n'
            '            if pressed:\n'
            '                return\n'
            '            else:\n'
            '                return\n'))
        self.assertIs(machine.send_key(0x41, True), True)
        self.assertIs(machine.send_key(0x41, False), True)

    def test_stored_backend_result_is_rejected_without_changing_source(self):
        source = self.source(
            '        ok = self._send_key_xdotool(vk_code, pressed)\n'
            '        if ok:\n'
            '            return\n')
        with self.assertRaises(ValueError):
            remote_access._patch_local_key_results(source)

    def test_backend_success_fallthrough_is_rejected(self):
        source = self.source(
            '        if self._send_key_xdotool(vk_code, pressed):\n'
            '            if pressed:\n'
            '                return\n')
        with self.assertRaises(ValueError):
            remote_access._patch_local_key_results(source)

    def test_unverified_decorator_and_nonboolean_returns_are_rejected(self):
        for source in (
            self.source('        return\n', decorator='    @unknown_decorator\n'),
            self.source('        return "unknown backend status"\n'),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                remote_access._patch_local_key_results(source)

    def test_inline_return_keeps_its_condition_and_comment(self):
        source = self.source(
            '        if self._send_key_xdotool(vk_code, pressed): return  # success\n')
        transformed = remote_access._patch_local_key_results(source)
        self.assertIn('if self._send_key_xdotool(vk_code, pressed): return True  # success', transformed)
        self.assertIs(self.machine(source).send_key(0x41, True), True)

    def test_multiple_verified_backends_short_circuit_safely(self):
        machine = self.machine(self.source(
            '        if (self._send_key_xdotool(vk_code, pressed)\n'
            '                or self._send_key_ydotool(vk_code, pressed)):\n'
            '            return\n').replace('\n', '\r\n'))
        self.assertIs(machine.send_key(0x41, True), True)


class PatchIntegrityTests(unittest.TestCase):
    def test_legacy_dynamic_logs_cannot_persist_remote_metadata(self):
        for local in (False, True):
            with self.subTest(local=local):
                source = fixtures.LegacyConfigTests.UPSTREAM_LOCAL if local else fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER
                class_name = 'LocalMachine' if local else 'RemoteController'
                source = 'import logging\nlog = logging.getLogger("legacyPrivacy")\n' + source
                source = source.replace('class ' + class_name + ':', 'class ' + class_name + ':\n'
                    '    def diagnostic(self, payload):\n'
                    '        log.error("Server error: %s" % payload)\n'
                    '        log.debug("remote metadata: %s", payload)\n')
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / 'legacy.py'
                    path.write_text(source)
                    patch = remote_access.patch_legacy_orca_local_machine if local else remote_access.patch_legacy_orca_remote_controller
                    patch(path)
                    namespace = {}
                    exec(path.read_text(), namespace)
                instance = object.__new__(namespace[class_name])
                previous = logging.root.manager.disable
                logging.disable(logging.NOTSET)
                try:
                    with self.assertLogs(namespace['log'], level='DEBUG') as logs:
                        instance.diagnostic('private-key-or-channel')
                    self.assertNotIn('private-key-or-channel', str(logs.output))
                finally:
                    logging.disable(previous)

    def patched(self, local=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'patch.py'
        path.write_text(fixtures.LegacyConfigTests.UPSTREAM_LOCAL if local
                        else fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER)
        patch = remote_access.patch_legacy_orca_local_machine if local else remote_access.patch_legacy_orca_remote_controller
        patch(path)
        return path, patch

    def test_debug_guard_is_part_of_current_validation(self):
        for local in (False, True):
            with self.subTest(local=local):
                path, patch = self.patched(local)
                text = path.read_text().replace(remote_access._DBG_GUARD, '', 1)
                path.write_text(text)
                valid = remote_access.legacy_local_machine_patch_current if local else remote_access.legacy_controller_patch_current
                self.assertFalse(valid(text))
                with self.assertRaises(ValueError):
                    patch(path)
                self.assertEqual(path.read_text(), text)

    def test_controller_hook_disconnection_is_not_current(self):
        path, _ = self.patched()
        text = path.read_text() + '\nRemoteController._on_remote_key = _lrd_original_on_key\n'
        self.assertFalse(remote_access.legacy_controller_patch_current(text))

    def test_class_assignment_cannot_override_a_valid_helper(self):
        path, _ = self.patched()
        text = path.read_text().replace(
            '    def _on_remote_key(self,',
            '    _linux_rdaccess_filter_key = lambda *args: False\n\n    def _on_remote_key(self,', 1)
        self.assertFalse(remote_access.legacy_controller_patch_current(text))

    def test_conditional_class_assignment_cannot_override_a_valid_helper(self):
        path, _ = self.patched()
        text = path.read_text().replace(
            '    def _on_remote_key(self,',
            '    if True:\n        _linux_rdaccess_filter_key = lambda *args: False\n\n    def _on_remote_key(self,', 1)
        self.assertFalse(remote_access.legacy_controller_patch_current(text))

    def test_local_injection_after_an_unconditional_return_is_not_current(self):
        path, _ = self.patched(local=True)
        text = path.read_text().replace(
            '    def _send_key_xdotool(self, key, pressed):\n',
            '    def _send_key_xdotool(self, key, pressed):\n        return False\n', 1)
        self.assertFalse(remote_access.legacy_local_machine_patch_current(text))

    def test_disconnected_controller_filter_call_is_not_current(self):
        path, _ = self.patched()
        text = path.read_text().replace('    def _on_remote_key(self,', '    def unrelated_method(self,', 1)
        self.assertFalse(remote_access.legacy_controller_patch_current(text))
