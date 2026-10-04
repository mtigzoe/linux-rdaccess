"""Regression tests for safe configuration updates and installation."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import linux_rdaccess
import remote_access
from tests import test_remote_access as fixtures


class ConfigurationValidationTests(unittest.TestCase):
    def test_connection_update_removes_transport_constructor_channel_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'orca-customizations.py'
            path.write_text(fixtures.LegacyConfigTests.CONFIG_SOURCE)
            transport = root / 'orca-scripts/transport.py'
            transport.parent.mkdir()
            original = ('class RelayTransport:\n'
                        '    def __init__(self, address, channel):\n'
                        '        log.info("Connecting to %s channel %s" % (address, channel))\n')
            transport.write_text(original)
            config = remote_access.RemoteAccessConfig(key='private-channel')
            remote_access.update_legacy_orca_customizations(config, path)
            messages = []
            class Log:
                def info(self, *args):
                    messages.append(args)
            namespace = {'log': Log()}
            exec(transport.read_text(), namespace)
            namespace['RelayTransport'](('relay.example', 6837), 'private-channel')
            self.assertNotIn('private-channel', str(messages))
            backup = transport.with_name(transport.name + '.linux-rdaccess-backup')
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(transport.stat().st_mode & 0o777, 0o600)
            once = transport.read_text()
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(transport.read_text(), once)

    def test_previous_local_speech_hook_upgrades_idempotently(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(fixtures.LegacyConfigTests.CONFIG_SOURCE + (
                'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH = True\n\n'
                + remote_access._LOCAL_SPEECH_PREF_HOOK_V1))
            config = remote_access.RemoteAccessConfig(key='k')
            remote_access.update_legacy_orca_customizations(config, path)
            once = path.read_text()
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), once)
            self.assertIn(remote_access._LOCAL_SPEECH_PREF_HOOK, once)
            self.assertNotIn(remote_access._LOCAL_SPEECH_PREF_HOOK_V1, once)


    def test_chained_config_assignment_is_rejected_without_changing_other_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            original = fixtures.LegacyConfigTests.CONFIG_SOURCE.replace(
                'YOUR_NVDAREMOTE_KEY = ', 'sentinel = YOUR_NVDAREMOTE_KEY = ')
            path.write_text(original)
            with self.assertRaises(ValueError):
                remote_access.update_legacy_orca_customizations(remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(path.read_text(), original)


    def test_duplicate_speech_preferences_are_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            original = fixtures.LegacyConfigTests.CONFIG_SOURCE + (
                'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH = True\n'
                'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH = False\n')
            path.write_text(original)
            with self.assertRaises(ValueError):
                remote_access.update_legacy_orca_customizations(remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(path.read_text(), original)


    def test_legal_unicode_escapes_multiline_values_and_comments_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            source = ('# YOUR_NVDAREMOTE_KEY = "comment"\r\n'
                      'sentinel = "é"; YOUR_NVDAREMOTE_SERVER_ADDRESS = "old" # host\r\n'
                      'YOUR_NVDAREMOTE_SERVER_PORT = 6837 # port\r\n'
                      'YOUR_NVDAREMOTE_KEY = (\r\n    "old"\r\n) # key\r\n'
                      'connection_type = "slave" # role\r\n')
            path.write_bytes(source.encode('utf-8'))
            config = remote_access.RemoteAccessConfig(host='relay-é.example', key='"é\\1\\g<key>"')
            remote_access.update_legacy_orca_customizations(config, path)
            namespace = {}
            exec(path.read_text(), namespace)
            self.assertEqual(namespace['YOUR_NVDAREMOTE_KEY'], config.key)
            self.assertEqual(namespace['YOUR_NVDAREMOTE_SERVER_ADDRESS'], config.host)
            self.assertEqual(namespace['sentinel'], 'é')
            self.assertIn('# key', path.read_text())
            self.assertIn('# YOUR_NVDAREMOTE_KEY = "comment"', path.read_text())


    def test_local_speech_returns_when_transport_disconnects(self):
        source = fixtures.LegacyConfigTests.CONFIG_SOURCE + '''
class Transport:
    connection_type = "slave"
    connected = True
transport = Transport()
events = []
def old_speak(*args, **kwargs):
    events.append("speak")
def old_speakCharacter(*args, **kwargs):
    events.append("character")
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(source)
            remote_access.update_legacy_orca_customizations(remote_access.RemoteAccessConfig(key='k'), path)
            namespace = {}
            exec(path.read_text(), namespace)
            namespace['old_speak']()
            namespace['old_speakCharacter']()
            self.assertEqual(namespace['events'], [])
            namespace['transport'].connected = False
            namespace['old_speak']()
            namespace['old_speakCharacter']()
            self.assertEqual(namespace['events'], ['speak', 'character'])


    def test_duplicate_assignments_fail_before_any_config_write(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            original = fixtures.LegacyConfigTests.CONFIG_SOURCE + 'YOUR_NVDAREMOTE_KEY = "later-key"\n'
            path.write_text(original)
            with self.assertRaises(ValueError):
                remote_access.update_legacy_orca_customizations(
                    remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(path.read_text(), original)
            self.assertFalse(path.with_name(path.name + '.linux-rdaccess-backup').exists())


    def test_role_comment_does_not_override_actual_transport_role(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            original = '# connection_type="slave"\n' + fixtures.LegacyConfigTests.CONFIG_SOURCE
            path.write_text(original)
            remote_access.update_legacy_orca_customizations(
                remote_access.RemoteAccessConfig(key='key', role='client'), path)
            self.assertIn('\nconnection_type="master"\n', path.read_text())


    def test_invalid_python_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            original = fixtures.LegacyConfigTests.CONFIG_SOURCE + 'if broken\n'
            path.write_text(original)
            with self.assertRaises(ValueError):
                remote_access.update_legacy_orca_customizations(
                    remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(path.read_text(), original)


    def test_install_can_run_from_installed_runtime_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('linux_rdaccess.py', 'remote_access.py', 'nvda_remote_check.py', 'orca_adapter.py'):
                (root / name).write_text('# fixture\n')
            linux_rdaccess.install_user_files(root, share_dir=root, bin_path=root / 'bin' / 'linux-rdaccess')
            self.assertTrue((root / 'bin' / 'linux-rdaccess').exists())
