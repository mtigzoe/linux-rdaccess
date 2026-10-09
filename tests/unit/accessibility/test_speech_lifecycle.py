"""Native Orca speech interruption uses the API exposed by Orca 42."""

import sys
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import remote_access
from tests.test_compat_lifecycle import Harness


class SpeechLifecycleTests(Harness, unittest.TestCase):
    CONFIG = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "old-key"
connection_type = "slave"
'''
    @staticmethod
    def orca_speech(stop=None):
        orca = types.ModuleType('orca')
        speech = types.ModuleType('orca.speech')
        if stop is not None:
            speech.stop = stop
        orca.speech = speech
        return mock.patch.dict(sys.modules, {'orca': orca, 'orca.speech': speech})

    @staticmethod
    def install_local_stop(controller, stopped):
        namespace = {'old_stop': lambda server: stopped.append(True),
                     'transport': controller.transport, '_want_cancel': False}
        # Verified installed connector shape: local_machine.cancel_speech()
        # delegates _local_only_stop, bypassing the deferred remote my_stop.
        source = remote_access._CUSTOMIZATION_SPEECH_SERVER_SOURCE + '''
def _local_only_stop():
    server = _get_speech_server()
    if server is not None:
        old_stop(server)

def my_stop(server):
    global _want_cancel
    if transport.connected and transport.connection_type == "slave":
        _want_cancel = True
    return old_stop(server)
'''
        exec(remote_access._patch_legacy_customization_speech_server(source), namespace)
        server = types.SimpleNamespace(stop=lambda: namespace['my_stop'](server))
        sys.modules['orca.speech']._speechserver = server
        controller.local_machine.cancel_speech = namespace['_local_only_stop']
        return namespace

    def test_ctrl_stops_orca42_server_without_setting_another_remote_cancel(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, glib = self._fake_glib()
        stopped = []
        with self.orca_speech():
            namespace = self.install_local_stop(c, stopped)
            with glib:
                self._key(c, 0xA2, True)
                self.assertEqual(c.transport.sent, ['cancel'])
                self.assertEqual(stopped, [])
                self.assertEqual(len(queue), 1)
                queue.pop(0)()
        self.assertEqual(stopped, [True])
        self.assertFalse(namespace['_want_cancel'])

    def test_ctrl_repeats_do_not_stop_again_but_a_fresh_press_does(self):
        c, _, _ = self._patched_controller()
        stopped = []
        with self.orca_speech():
            namespace = self.install_local_stop(c, stopped)
            for pressed in (True, True, False, True, False):
                self._key(c, 0xA3, pressed)
        self.assertEqual(stopped, [True, True])
        self.assertEqual(c.transport.sent, ['cancel', 'cancel'])
        self.assertFalse(namespace['_want_cancel'])

    def test_native_stop_is_coalesced_and_expires_after_disconnect(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, glib = self._fake_glib()
        stopped = []
        with self.orca_speech(), glib:
            self.install_local_stop(c, stopped)
            self._key(c, 0xA2, True)
            self._key(c, 0xA2, False)
            self._key(c, 0xA2, True)
            self.assertEqual(len(queue), 1)
            c.transport.connected = False
            queue.pop(0)()
        self.assertEqual(stopped, [])
        self.assertFalse(c._lrd_local_stop_pending)

    def test_name_only_ctrl_interrupts_nvda_once_per_fresh_press(self):
        for name in ("Control_L", "Control_R"):
            with self.subTest(name=name):
                c, _, _ = self._patched_controller()
                c.local_machine.cancel_speech = mock.Mock()
                for pressed in (True, True, False, True, False):
                    c._on_remote_key(key_name=name, pressed=pressed)
                self.assertEqual(c.transport.sent, ["cancel", "cancel"])
                self.assertEqual(c.local_machine.cancel_speech.call_count, 2)
                self.assertFalse(c._lrd_forwarded)

    def test_name_only_non_ctrl_modifier_does_not_interrupt_say_all(self):
        for name in ("Shift_L", "Shift_R", "Alt_L", "Alt_R", "Super_L", "Super_R"):
            with self.subTest(name=name):
                c, _, _ = self._patched_controller()
                c.local_machine.cancel_speech = mock.Mock()
                c._on_remote_key(key_name=name, pressed=True)
                c._on_remote_key(key_name=name, pressed=False)
                c.local_machine.cancel_speech.assert_not_called()
                self.assertEqual(c.transport.sent, [])
                self.assertFalse(c._lrd_forwarded)

    def test_explicit_vk_remains_authoritative_for_speech_interruption(self):
        c, _, _ = self._patched_controller()
        c.local_machine.cancel_speech = mock.Mock()
        c._on_remote_key(key_name="Control_L", vk_code=0x41, pressed=True)
        c._on_remote_key(key_name="Control_L", vk_code=0x41, pressed=False)
        self.assertEqual(c.transport.sent, [])
        c.local_machine.cancel_speech.assert_called_once()

    def test_getter_supports_both_orca42_and_newer_server_slots(self):
        namespace = {}
        exec(remote_access._patch_legacy_customization_speech_server(
            remote_access._CUSTOMIZATION_SPEECH_SERVER_SOURCE), namespace)
        getter = namespace['_get_speech_server']
        with self.orca_speech():
            speech = sys.modules['orca.speech']
            legacy, newer = object(), object()
            speech._speechserver = legacy
            speech._state = types.SimpleNamespace(server=newer)
            self.assertIs(getter(), legacy)
            speech._speechserver = None
            self.assertIs(getter(), newer)
            del speech._state
            self.assertIsNone(getter())

    def test_updater_preserves_original_getter_backup_and_is_idempotent(self):
        source = self.CONFIG + remote_access._CUSTOMIZATION_SPEECH_SERVER_SOURCE
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orca-customizations.py'
            path.write_text(source)
            config = remote_access.RemoteAccessConfig(key='new-key')
            remote_access.update_legacy_orca_customizations(config, path)
            updated = path.read_text()
            self.assertIn(remote_access._CUSTOMIZATION_SPEECH_SERVER_RETURN, updated)
            self.assertEqual(path.with_name(path.name + '.linux-rdaccess-backup').read_text(), source)
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), updated)

    def test_unknown_or_shadowed_getter_leaves_config_and_backup_untouched(self):
        getter = remote_access._CUSTOMIZATION_SPEECH_SERVER_SOURCE
        for shape in (getter.replace('speech._state.server', 'custom_server()'),
                      getter + getter, getter + '\n_get_speech_server = another\n'):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'orca-customizations.py'
                source = self.CONFIG + shape
                path.write_text(source)
                with self.assertRaisesRegex(ValueError, 'unsupported legacy speech-server getter'):
                    remote_access.update_legacy_orca_customizations(
                        remote_access.RemoteAccessConfig(key='new-key'), path)
                self.assertEqual(path.read_text(), source)
                self.assertFalse(path.with_name(path.name + '.linux-rdaccess-backup').exists())


if __name__ == '__main__':
    unittest.main()
