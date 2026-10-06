"""Failure, session and privacy regressions for generated runtime code."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import sys
import types
import unittest
from unittest import mock

import remote_access
from tests.test_compat_lifecycle import Harness
from tests import test_remote_access as fixtures


class RuntimeStateTests(Harness, unittest.TestCase):
    @staticmethod
    def _slow_monotonic():
        value = [100.0]
        def tick():
            current = value[0]
            value[0] += 0.03
            return current
        return tick

    def test_generated_log_descriptors_close_if_stream_creation_fails(self):
        c, _, _ = self._patched_controller()
        for trace in (True, False):
            with self.subTest(trace=trace), tempfile.TemporaryDirectory() as temp:
                descriptors = []
                original = os.open
                def record(*args):
                    fd = original(*args)
                    descriptors.append(fd)
                    return fd
                (Path(temp) / '.local/share/orca').mkdir(parents=True)
                try:
                    with mock.patch.dict(os.environ, {'HOME': temp, 'LINUX_RDACCESS_BRAILLE_TRACE': '1', 'LINUX_RDACCESS_DEBUG': '1'}), \
                            mock.patch('os.open', side_effect=record), \
                            mock.patch('os.fdopen', side_effect=OSError('stream unavailable')), \
                            mock.patch('time.monotonic', side_effect=self._slow_monotonic()):
                        if trace:
                            with self.assertRaises(OSError):
                                c._linux_rdaccess_trace_braille({'action': 'pan_back'})
                        else:
                            self._key(c, 0x41, True)
                    self.assertTrue(descriptors)
                    with self.assertRaises(OSError):
                        os.fstat(descriptors[-1])
                finally:
                    for fd in descriptors:
                        try:
                            os.close(fd)
                        except OSError:
                            pass

    def test_braille_type_boundaries_do_not_route_or_persist_untrusted_metadata(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        invalid = (
            {'routingIndex': True}, {'routingIndex': 1.0}, {'routingIndex': -1},
            {'routingIndex': 10 ** 100}, {'routingIndex': None}, {'cellIndexes': []},
            {'cellIndexes': [True]}, {'cellIndexes': [1.0]},
            {'cellIndexes': [[1]]}, {'cellIndexes': b'private-text'},
            {'dots': True, 'routingIndex': 1}, {'dots': 1.0, 'routingIndex': 1},
            {'dots': -1, 'routingIndex': 1}, {'space': 2, 'routingIndex': 1},
            {'scriptPath': ['private-text'], 'routingIndex': 1},
            {'scriptPath': b'private-text', 'routingIndex': 1},
            {'identifiers': [b'private-text'], 'routingIndex': 1},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                c._on_remote_braille_input(**payload)
                _, record = c._linux_rdaccess_classify_braille(payload)
                self.assertNotIn('private-text', str(record))
        self.assertEqual(calls, [])
        for cells in ([0], (0,)):
            c._on_remote_braille_input(cellIndexes=cells, dots=0, space=False)
        self.assertEqual([args[1].event['argument'] for args in calls], [0, 0])

    def test_failed_idle_registration_does_not_drop_typing_or_leave_pending_speech(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        with patches:
            with mock.patch.object(sys.modules['gi.repository'].GLib, 'idle_add', side_effect=RuntimeError('private application text')):
                self._key(c, 0x41, True)
        self.assertFalse(c._lrd_local_stop_pending)
        self.assertEqual([kw[:3] for kw in c.local_machine.events if kw[0] == 'key'], [('key', 0x41, True)])

    def test_zero_idle_source_does_not_leave_pass_next_latch(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        with patches:
            with mock.patch.object(sys.modules['gi.repository'].GLib, 'idle_add', return_value=0):
                self._key(c, 0x2D, True)
                self._key(c, 0x71, True)
        self.assertFalse(c._lrd_bypass_next)
        self.assertFalse(c._lrd_local_stop_pending)

    def test_changed_repeat_and_release_metadata_keep_initial_injection_identity(self):
        c, _, _ = self._patched_controller()
        events = []
        c.local_machine.send_key = lambda **kw: events.append(kw)
        for pressed, name, scan in ((True, 'a', 30), (True, 'b', 48), (False, 'b', 48)):
            c._on_remote_key(key_name=name, pressed=pressed, vk_code=0x41, scan_code=scan, extended=False)
        self.assertEqual([(kw['key_name'], kw['scan_code'], kw['pressed']) for kw in events],
                         [('a', 30, True), ('a', 30, True), ('a', 30, False)])
        self.assertEqual(c._lrd_forwarded, {})

    def test_departure_transition_is_atomic_across_overlapping_receivers(self):
        c, _, _ = self._patched_controller()
        c.connected_clients = {8: {'connection_type': 'master'}}
        self._key(c, 0x41, True)
        reset_done, resume, key_done = (threading.Event() for _ in range(3))
        original = c._linux_rdaccess_reset_keys
        def paused_reset():
            original()
            reset_done.set()
            resume.wait(2)
        c._linux_rdaccess_reset_keys = paused_reset
        departure = threading.Thread(target=lambda: c._on_client_left(client={'id': 8}))
        incoming = threading.Thread(target=lambda: (self._key(c, 0x42, True), key_done.set()))
        departure.start()
        try:
            self.assertTrue(reset_done.wait(1))
            incoming.start()
            self.assertFalse(key_done.wait(0.05))
        finally:
            resume.set()
            departure.join(2)
            if incoming.ident is not None:
                incoming.join(2)
        self.assertFalse(departure.is_alive())
        self.assertFalse(incoming.is_alive())
        self.assertNotIn(8, c.connected_clients)
        self.assertIsNotNone(c._lrd_state)

    def test_timing_debug_is_private_and_never_contains_key_metadata(self):
        c, _, _ = self._patched_controller()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.local/share/orca/orca-remote-slow-events.log'
            path.parent.mkdir(parents=True)
            path.write_text('old timing\n')
            path.chmod(0o644)
            with mock.patch.dict(os.environ, {'HOME': temp, 'LINUX_RDACCESS_DEBUG': '1'}), \
                    mock.patch('time.monotonic', side_effect=self._slow_monotonic()):
                c._on_remote_key(key_name='private-key-name', vk_code=0x41, pressed=True, extended=False)
            record = path.read_text()
            self.assertIn('key-event handling took', record)
            self.assertNotIn('private-key-name', record)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_trace_descriptor_closes_when_permissions_fail(self):
        c, _, _ = self._patched_controller()
        descriptors = []
        open_file = os.open
        def track_open(*args):
            fd = open_file(*args)
            descriptors.append(fd)
            return fd
        def cleanup():
            for fd in descriptors:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.addCleanup(cleanup)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / '.local/share/orca').mkdir(parents=True)
            with mock.patch.dict(os.environ, {'HOME': temp, 'LINUX_RDACCESS_BRAILLE_TRACE': '1'}), \
                    mock.patch('os.open', side_effect=track_open), \
                    mock.patch('os.fchmod', side_effect=PermissionError('permissions unavailable')):
                with self.assertRaises(PermissionError):
                    c._linux_rdaccess_trace_braille({'redacted': 'unknown-braille-input'})
            with self.assertRaises(OSError):
                os.fstat(descriptors[-1])


class LocalSpeechLifetimeTests(unittest.TestCase):
    def test_old_hook_upgrade_and_live_transport_changes_restore_original_output(self):
        calls = []
        original = lambda *args, **kwargs: calls.append('speech')
        peer = types.SimpleNamespace(connected=True, connection_type='slave')
        namespace = {'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH': True,
                     'transport': peer, 'old_speak': original}
        exec(remote_access._LOCAL_SPEECH_PREF_HOOK_V2, namespace)
        exec(remote_access._LOCAL_SPEECH_PREF_HOOK, namespace)
        self.assertIs(namespace['_linux_rdaccess_saved_old_speak'], original)
        for connected, role, expected in ((True, 'slave', 0), (False, 'slave', 1),
                                          (True, 'slave', 1), (True, 'master', 2)):
            peer.connected, peer.connection_type = connected, role
            namespace['old_speak']()
            self.assertEqual(len(calls), expected)
        namespace['transport'] = types.SimpleNamespace(connected=True, connection_type='slave')
        namespace['old_speak']()
        self.assertEqual(len(calls), 2)
        del namespace['transport']
        namespace['old_speak']()
        self.assertEqual(len(calls), 3)

    def test_v30_speech_hook_upgrades_on_disk_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(fixtures.LegacyConfigTests.CONFIG_SOURCE +
                            'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH = True\n' + remote_access._LOCAL_SPEECH_PREF_HOOK_V2)
            config = remote_access.RemoteAccessConfig(key='synthetic')
            remote_access.update_legacy_orca_customizations(config, path)
            once = path.read_text()
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(once, path.read_text())
            self.assertEqual(once.count(remote_access.LOCAL_SPEECH_PREF_MARKER), 1)
            self.assertIn(remote_access._LOCAL_SPEECH_PREF_HOOK, once)

    def test_executing_preference_hook_again_does_not_stack_or_recurse(self):
        calls = []
        speak = lambda *args, **kwargs: calls.append('speech')
        character = lambda *args, **kwargs: calls.append('character')
        namespace = {'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH': True,
                     'transport': types.SimpleNamespace(connected=False, connection_type='slave'),
                     'old_speak': speak, 'old_speakCharacter': character}
        exec(remote_access._LOCAL_SPEECH_PREF_HOOK, namespace)
        first = namespace['old_speak']
        exec(remote_access._LOCAL_SPEECH_PREF_HOOK, namespace)
        namespace['old_speak']()
        namespace['old_speakCharacter']()
        self.assertEqual(calls, ['speech', 'character'])
        self.assertIs(namespace['old_speak'], first)
        self.assertIs(namespace['_linux_rdaccess_saved_old_speak'], speak)
