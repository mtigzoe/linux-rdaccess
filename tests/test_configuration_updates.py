"""Regression tests for safe configuration updates and installation."""
from __future__ import annotations

from pathlib import Path
import os
import contextlib
import io
import logging
import tempfile
import unittest
from unittest import mock

import linux_rdaccess
import remote_access
from tests import test_remote_access as fixtures


class ConfigurationValidationTests(unittest.TestCase):
    def test_verified_gui_reconnect_role_is_preserved(self):
        source = ('transport = RelayTransport(connection_type="slave")\n'
                  'def gui_connect(role):\n    transport.reconnect(connection_type=role)\n')
        updated = remote_access._replace_configuration_values(source, {}, role='master')
        self.assertIn('RelayTransport(connection_type="master")', updated)
        self.assertIn('transport.reconnect(connection_type=role)', updated)

    def test_optional_patch_warnings_do_not_print_exception_text(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(fixtures.LegacyConfigTests.CONFIG_SOURCE)
            scripts = path.parent / 'orca-scripts'
            scripts.mkdir()
            for name in ('transport.py', 'remote_controller.py', 'local_machine.py'):
                (scripts / name).write_text('# placeholder\n')
            output = io.StringIO()
            with mock.patch.object(remote_access, '_patch_legacy_transport_logging', side_effect=OSError('private-backend-text')), \
                    mock.patch.object(remote_access, 'patch_legacy_orca_remote_controller', side_effect=OSError('private-backend-text')), \
                    mock.patch.object(remote_access, 'patch_legacy_orca_local_machine', side_effect=OSError('private-backend-text')), \
                    contextlib.redirect_stderr(output):
                remote_access.update_legacy_orca_customizations(remote_access.RemoteAccessConfig(key='synthetic'), path)
            self.assertNotIn('private-backend-text', output.getvalue())
            self.assertEqual(output.getvalue().count('warning:'), 3)

    def test_updater_redacts_configuration_fallback_and_callback_tracebacks(self):
        source = fixtures.LegacyConfigTests.CONFIG_SOURCE + '''
import traceback
def private_fallback(text):
    try:
        raise RuntimeError(text)
    except Exception:
        print("Orca Remote: %s" % text)
        traceback.print_exc()
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(source)
            callbacks = path.parent / 'orca-scripts/callback_manager.py'
            callbacks.parent.mkdir()
            callbacks.write_text('import logging\nlogger = logging.getLogger("callbackPrivacy")\n'
                                 'def call(callback):\n    try:\n        callback()\n'
                                 '    except Exception:\n        logger.exception("callback failed: %r" % callback)\n')
            remote_access.update_legacy_orca_customizations(remote_access.RemoteAccessConfig(key='synthetic'), path)
            namespace = {}
            exec(path.read_text(), namespace)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                namespace['private_fallback']('private-application-text')
            self.assertNotIn('private-application-text', output.getvalue())
            exec(callbacks.read_text(), namespace)
            previous = logging.root.manager.disable
            logging.disable(logging.NOTSET)
            try:
                with self.assertLogs('callbackPrivacy', level='ERROR') as logs:
                    namespace['call'](mock.Mock(side_effect=RuntimeError('private-callback-text')))
                self.assertNotIn('private-callback-text', str(logs.output))
            finally:
                logging.disable(previous)

    def test_private_writer_closes_descriptor_when_fdopen_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'private.json'
            descriptors = []
            create = remote_access.tempfile.mkstemp
            def record(*args, **kwargs):
                result = create(*args, **kwargs)
                descriptors.append(result[0])
                return result
            try:
                with mock.patch.object(remote_access.tempfile, 'mkstemp', side_effect=record), \
                        mock.patch.object(remote_access.os, 'fdopen', side_effect=OSError('cannot open stream')):
                    with self.assertRaises(OSError):
                        remote_access._write_private_text(path, 'secret')
                with self.assertRaises(OSError):
                    os.fstat(descriptors[0])
                self.assertEqual(list(path.parent.iterdir()), [])
            finally:
                for fd in descriptors:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def test_annotated_role_assignment_is_updated(self):
        source = 'connection_type: str = "slave"\n'
        updated = remote_access._replace_configuration_values(source, {}, role='master')
        namespace = {}
        exec(updated, namespace)
        self.assertEqual(namespace['connection_type'], 'master')

    def test_nested_transport_or_conditional_override_is_rejected(self):
        for source, values in (
            ('def unused():\n    return RelayTransport(connection_type="slave")\n', {}),
            ('YOUR_NVDAREMOTE_KEY = "old"\nif True:\n    YOUR_NVDAREMOTE_KEY = "overridden"\nconnection_type = "slave"\n', {'YOUR_NVDAREMOTE_KEY': '"new"'}),
            ('connection_type = "slave"\ntransport = factory(connection_type="slave")\n', {}),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                remote_access._replace_configuration_values(source, values, role='master')

    def test_missing_bundle_member_does_not_partially_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, installed = root / 'source', root / 'installed'
            source.mkdir()
            installed.mkdir()
            for name in ('linux_rdaccess.py', 'remote_access.py', 'nvda_remote_check.py'):
                (source / name).write_text('# new\n')
                (installed / name).write_text('# old\n')
            with self.assertRaises(FileNotFoundError):
                linux_rdaccess.install_user_files(source, share_dir=installed, bin_path=root / 'bin/tool')
            self.assertEqual((installed / 'remote_access.py').read_text(), '# old\n')

    def test_doctor_detects_stale_runtime_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            adapter = path.parent / 'orca-scripts/linux_rdaccess_orca_adapter.py'
            adapter.parent.mkdir()
            adapter.write_text('# stale adapter\n')
            rows = dict(linux_rdaccess.patch_status(path))
            label = 'Orca API adapter (linux_rdaccess_orca_adapter.py)'
            self.assertEqual(rows.get(label), 'outdated - run: linux-rdaccess connect')
            adapter.write_text((Path(linux_rdaccess.__file__).parent / 'orca_adapter.py').read_text())
            self.assertEqual(dict(linux_rdaccess.patch_status(path)).get(label), 'current')

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
