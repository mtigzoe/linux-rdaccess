"""Failure and ownership regressions for the installed compatibility patches."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

import remote_access
from tests import test_remote_access as fixtures


class Harness:
    UPSTREAM_CONTROLLER = fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER
    UPSTREAM_LOCAL = fixtures.LegacyConfigTests.UPSTREAM_LOCAL
    FakeLocal = fixtures.LegacyConfigTests.FakeLocal
    FakeTransport = fixtures.LegacyConfigTests.FakeTransport
    _patched_controller = fixtures.LegacyConfigTests._patched_controller
    _patched_local = fixtures.LegacyConfigTests._patched_local
    _key = fixtures.LegacyConfigTests._key
    _fake_glib = fixtures.LegacyConfigTests._fake_glib


class InputOwnershipTests(Harness, unittest.TestCase):
    def test_remote_key_exception_cannot_reach_upstream_traceback_logger(self):
        c, _, _ = self._patched_controller()
        def send(**kwargs):
            raise ValueError('private typed input')
        c.local_machine.send_key = send
        with mock.patch.object(c._module.log, 'error') as error:
            self._key(c, 0x41, True)
        self.assertTrue(error.called)
        self.assertNotIn('private typed input', str(error.call_args_list))

    def test_handoff_waits_for_an_inflight_press_and_releases_it(self):
        c, _, _ = self._patched_controller()
        started, resume, attempted, finished = (threading.Event() for _ in range(4))
        events = []

        def send(**kw):
            if kw['pressed']:
                started.set()
                resume.wait(2)
            events.append(kw['pressed'])

        def handoff():
            attempted.set()
            c.toggle_control()
            finished.set()

        c.local_machine.send_key = send
        key_thread = threading.Thread(target=lambda: self._key(c, 0x41, True))
        handoff_thread = threading.Thread(target=handoff)
        key_thread.start()
        try:
            self.assertTrue(started.wait(1))
            handoff_thread.start()
            self.assertTrue(attempted.wait(1))
            # Before the fix, reset completed before the backend acquired the
            # press, leaving it held after handoff. Correct serialization waits.
            self.assertFalse(finished.wait(0.05))
        finally:
            resume.set()
            key_thread.join(2)
            if handoff_thread.ident is not None:
                handoff_thread.join(2)
        self.assertFalse(key_thread.is_alive())
        self.assertFalse(handoff_thread.is_alive())
        self.assertEqual(events, [True, False])
        self.assertEqual(c._lrd_forwarded, {})

    def test_failed_press_never_acquires_a_release(self):
        c, _, _ = self._patched_controller()
        events = []

        def send(**kw):
            if kw['pressed']:
                raise OSError('backend unavailable')
            events.append(kw)

        c.local_machine.send_key = send
        self._key(c, 0x41, True)
        self._key(c, 0x41, False)
        c.toggle_control()
        self.assertEqual(events, [])

    def test_failed_deferred_caps_press_never_acquires_a_release(self):
        c, _, _ = self._patched_controller()
        events = []

        def send(**kw):
            if kw['vk_code'] == 0x14 and kw['pressed']:
                raise OSError('backend unavailable')
            events.append((kw['vk_code'], kw['pressed']))

        c.local_machine.send_key = send
        self._key(c, 0x14, True)
        self._key(c, 0x41, True)
        self._key(c, 0x14, False)
        c.toggle_control()
        self.assertEqual(events, [(0x41, True), (0x41, False)])

    def test_name_only_keys_keep_distinct_release_payloads_on_reset(self):
        c, _, _ = self._patched_controller()
        events = []
        c.local_machine.send_key = lambda **kw: events.append(kw)
        for name in ('a', 'b'):
            c._on_remote_key(key_name=name, pressed=True, extended=False)
        self._key(c, 0xA2, True)
        c.toggle_control()
        released = [kw['key_name'] for kw in events if not kw['pressed']]
        self.assertCountEqual(released, [None, 'a', 'b'])

    def test_late_release_after_reset_is_not_forwarded_twice(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x41, True)
        c.toggle_control()
        self._key(c, 0x41, False)
        keys = [event[:3] for event in c.local_machine.events if event[0] == 'key']
        self.assertEqual(keys, [('key', 0x41, True), ('key', 0x41, False)])

    def test_failed_release_remains_owned_for_reset_retry(self):
        c, _, _ = self._patched_controller()
        events = []
        failures = [True]

        def send(**kw):
            if not kw['pressed'] and failures and failures.pop():
                raise OSError('temporary failure')
            events.append(kw['pressed'])

        c.local_machine.send_key = send
        self._key(c, 0x41, True)
        self._key(c, 0x41, False)
        c.toggle_control()
        self.assertEqual(events, [True, False])

    def test_role_transition_expires_queued_actions_without_another_key(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with patches:
            self._key(c, 0x2D, True)
            self._key(c, 0x54, True)
            c.transport.connection_type = 'master'
            for callback in queue:
                callback()
        self.assertEqual(calls, [])

    def test_clipboard_callback_expires_at_handoff(self):
        source = self.UPSTREAM_CONTROLLER.replace(
            '    def _on_remote_sas(',
            '    def _on_remote_clipboard(self, text=None, **kwargs):\n'
            '        self.local_machine.set_clipboard_text(text=text)\n\n'
            '    def _on_remote_sas(')
        c, _, _ = self._patched_controller(source=source, inline=False)
        queue, patches = self._fake_glib()
        calls = []
        c.local_machine.set_clipboard_text = lambda **kw: calls.append(kw)
        with patches:
            c._on_remote_clipboard(text='old clipboard')
            c.toggle_control()
            for callback in queue:
                callback()
        self.assertEqual(calls, [])

    def test_elements_fallback_releases_letter_if_keyup_raises(self):
        c, _, _ = self._patched_controller()
        held = set()
        failed = []

        def send(**kw):
            vk = kw['vk_code']
            if not kw['pressed'] and vk == 0x4D and not failed:
                failed.append(True)
                raise OSError('temporary failure')
            if kw['pressed']:
                held.add(vk)
            else:
                held.discard(vk)

        c.local_machine.send_key = send
        with self.assertRaises(OSError):
            c._linux_rdaccess_send_structural_list('m', None)
        self.assertEqual(held, set())

    def test_elements_fallback_does_not_release_an_existing_shift(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0xA0, True)
        c._linux_rdaccess_send_structural_list('m', None)
        keys = [event[:3] for event in c.local_machine.events if event[0] == 'key']
        self.assertNotIn(('key', 0xA0, False), keys)

    def test_elements_fallback_borrows_generic_left_modifier_aliases(self):
        for vk, left in ((0x10, 0xA0), (0x12, 0xA4)):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, vk, True)
                c._linux_rdaccess_send_structural_list('m', None)
                keys = [event[:3] for event in c.local_machine.events if event[0] == 'key']
                self.assertNotIn(('key', left, False), keys)

    def test_elements_fallback_aborts_if_a_modifier_was_not_injected(self):
        c, _, _ = self._patched_controller()
        events = []

        def send(**kw):
            events.append((kw['vk_code'], kw['pressed']))
            return kw['vk_code'] != 0xA4

        c.local_machine.send_key = send
        c._linux_rdaccess_send_structural_list('m', None)
        self.assertEqual(events, [(0xA0, True), (0xA4, True), (0xA0, False)])

    def test_elements_fallback_does_not_release_an_existing_letter(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x4D, True)
        c._linux_rdaccess_send_structural_list('m', None)
        keys = [event[:3] for event in c.local_machine.events if event[0] == 'key']
        self.assertEqual(keys, [('key', 0x4D, True)])

    def test_elements_dialog_selection_expires_during_nested_main_loop(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_open_structural_list = lambda *args: calls.append(args)
        adapter = types.ModuleType('linux_rdaccess_orca_adapter')

        def show(callback):
            c.toggle_control()  # Gtk.Dialog.run() can process a handoff.
            callback('m')
            return True

        adapter.show_elements_list = show
        with mock.patch.dict(sys.modules, {'linux_rdaccess_orca_adapter': adapter}):
            c._linux_rdaccess_show_elements_list(None)
        self.assertEqual(calls, [])

    def test_declined_adapter_call_uses_verified_legacy_handler(self):
        c, _, _ = self._patched_controller()
        calls = []
        adapter = types.ModuleType('linux_rdaccess_orca_adapter')
        adapter.OrcaRuntimeAdapter = types.SimpleNamespace(say_all=lambda: False)
        orca = types.ModuleType('orca')
        orca.orca_state = types.SimpleNamespace(activeScript=types.SimpleNamespace(
            sayAll=lambda event: calls.append(event)))
        with mock.patch.dict(sys.modules, {'linux_rdaccess_orca_adapter': adapter, 'orca': orca}):
            self.assertTrue(c._linux_rdaccess_script_call('sayAll'))
        self.assertEqual(calls, [None])

    def test_unavailable_script_api_reports_failure_without_resynthesizing_input(self):
        c, _, _ = self._patched_controller()
        adapter = types.ModuleType('linux_rdaccess_orca_adapter')
        adapter.OrcaRuntimeAdapter = types.SimpleNamespace(say_all=lambda: False)
        orca = types.ModuleType('orca')
        orca.orca_state = types.SimpleNamespace(activeScript=types.SimpleNamespace())
        with mock.patch.dict(sys.modules, {'linux_rdaccess_orca_adapter': adapter, 'orca': orca}), \
                mock.patch.object(c._module.log, 'error') as error:
            self.assertFalse(c._linux_rdaccess_script_call('sayAll'))
        self.assertTrue(error.called)
        self.assertEqual(c.local_machine.events, [])

    def test_failed_bypass_api_does_not_leave_receive_latch_armed(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_script_call = lambda *args: False
        self._key(c, 0x2D, True)
        self._key(c, 0x71, True)
        self.assertFalse(c._lrd_bypass_next)

    def test_queued_exception_does_not_persist_application_text(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()

        def operation():
            raise ValueError('private application text')

        with patches, mock.patch.object(c._module.log, 'error') as error:
            c._linux_rdaccess_run_main(operation)
            self.assertFalse(queue.pop()())
        self.assertTrue(error.called)
        self.assertNotIn('private application text', str(error.call_args_list))


class BrailleValidationTests(Harness, unittest.TestCase):
    def test_rotated_trace_is_private_before_replacement(self):
        c, _, _ = self._patched_controller()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / '.local/share/orca/orca-remote-braille-input.log'
            path.parent.mkdir(parents=True)
            path.write_text('old trace')
            path.chmod(0o644)
            c._LRD_TRACE_MAX_BYTES = 1
            replace = os.replace
            permissions = []

            def observe_replace(source, target):
                permissions.append(Path(source).stat().st_mode & 0o777)
                return replace(source, target)

            with mock.patch.dict(os.environ, {'HOME': temp, 'LINUX_RDACCESS_BRAILLE_TRACE': '1'}), \
                    mock.patch('os.replace', side_effect=observe_replace):
                c._linux_rdaccess_trace_braille({'redacted': 'unknown-braille-input'})
            self.assertEqual(permissions, [0o600])
            self.assertEqual(Path(str(path) + '.1').stat().st_mode & 0o777, 0o600)

    def test_falsey_malformed_script_metadata_does_not_authorize_routing(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        for value in (False, 0, '', {}, [], ['braille_routeTo']):
            c._on_remote_braille_input(scriptPath=value, routingIndex=2)
        self.assertEqual(calls, [])

    def test_noninteger_legacy_routing_index_cannot_equal_modern_cell(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        c._on_remote_braille_input(routingIndex=2.0, cellIndexes=[2])
        self.assertEqual(calls, [])

    def test_unknown_identifiers_are_redacted_instead_of_persisted(self):
        c, _, _ = self._patched_controller()
        action, record = c._linux_rdaccess_classify_braille({
            'id': 'literal-password', 'identifiers': ['bk:literal-password'],
            'scriptPath': ['custom', 'Commands', 'kb:literal-password'],
            'source': 'literal-password', 'model': 'literal-password'})
        self.assertEqual(action, 'keyboard')
        self.assertNotIn('literal-password', str(record))

    def test_malformed_arrays_are_ignored_and_redacted_without_raising(self):
        c, _, _ = self._patched_controller()
        for payload in ({'identifiers': 4}, {'scriptPath': {'name': 'kb:x'}},
                        {'scriptPath': 2}, {'identifiers': 'dot1'},
                        {'dots': -1, 'routingIndex': 2}):
            action, record = c._linux_rdaccess_classify_braille(payload)
            self.assertNotIn(action, ('route', 'pan_back', 'pan_forward', 'to_focus'))
            self.assertNotIn('scriptPath', record)


class CompatibilityPatchTests(unittest.TestCase):
    def test_previous_remote_and_local_versions_upgrade_without_duplicate_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, source, marker, previous, patch, valid in (
                ('controller', fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER,
                 remote_access.LEGACY_COMPAT_MARKER, remote_access.LEGACY_COMPAT_MARKER_V29,
                 remote_access.patch_legacy_orca_remote_controller, remote_access.legacy_controller_patch_current),
                ('local', fixtures.LegacyConfigTests.UPSTREAM_LOCAL,
                 remote_access.LOCAL_MACHINE_MARKER, remote_access.LOCAL_MACHINE_MARKER_V6,
                 remote_access.patch_legacy_orca_local_machine, remote_access.legacy_local_machine_patch_current)):
                with self.subTest(patch=name):
                    path = Path(temp) / (name + '.py')
                    path.write_text(source)
                    patch(path)
                    backup = path.with_name(path.name + '.linux-rdaccess-backup')
                    backup.chmod(0o644)  # Older patchers used ordinary writes.
                    path.write_text(path.read_text().replace(marker, previous))
                    self.assertTrue(patch(path))
                    self.assertTrue(valid(path.read_text()))
                    self.assertNotIn(previous + '\n', path.read_text())
                    self.assertEqual(backup.read_text(), source)
                    self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                    self.assertFalse(patch(path))


    def test_comment_marker_does_not_report_a_complete_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, source, marker, patch in (
                ('controller', fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER,
                 remote_access.LEGACY_COMPAT_MARKER, remote_access.patch_legacy_orca_remote_controller),
                ('local', fixtures.LegacyConfigTests.UPSTREAM_LOCAL,
                 remote_access.LOCAL_MACHINE_MARKER, remote_access.patch_legacy_orca_local_machine)):
                path = Path(temp) / (name + '.py')
                text = source + '\n' + marker + '\n'
                path.write_text(text)
                with self.assertRaises(ValueError):
                    patch(path)
                self.assertEqual(path.read_text(), text)
