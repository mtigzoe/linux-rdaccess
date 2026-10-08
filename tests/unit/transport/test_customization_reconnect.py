"""Automatic startup shares the legacy transport's retry/cancellation worker."""

import ast
import os
from pathlib import Path
import socket
import tempfile
import threading
import types
import unittest

import remote_access


# The installed Orca Remote ConnectorThread's loop. Its transport owns
# cancellation and replacement; the customization must start this worker.
class NativeConnectorThread(threading.Thread):
    def __init__(self, connector, sleeper):
        super().__init__(daemon=True)
        self.running = True
        self.connector = connector
        self.sleeper = sleeper

    def run(self):
        while self.running:
            try:
                self.connector.run()
            except socket.error:
                self.sleeper(5)
                continue
            else:
                self.sleeper(5)


class NativeTransport:
    def __init__(self, sleeper):
        self.sleeper = sleeper
        self.attempts = 0
        self.reconnector_thread = NativeConnectorThread(self, sleeper)

    def run(self):
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionRefusedError()
        self.reconnector_thread.running = False

    def close(self):
        self.reconnector_thread.running = False
        self.reconnector_thread = NativeConnectorThread(self, self.sleeper)

    def reconnect(self):
        self.close()
        self.reconnector_thread.start()


class CustomizationReconnectTests(unittest.TestCase):
    SOURCE = remote_access._CUSTOMIZATION_ONESHOT_START
    CONFIG = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "old-key"
connection_type = "slave"
'''

    def patched(self):
        return remote_access._patch_legacy_customization_reconnect(self.SOURCE)

    def test_startup_retries_failed_connection_using_existing_worker(self):
        sleeps = []
        transport = NativeTransport(sleeps.append)
        original_worker = transport.reconnector_thread
        namespace = {"transport": transport, "_has_config": True}
        exec(self.patched(), namespace)
        original_worker.join(2)
        self.assertFalse(original_worker.is_alive())
        self.assertIs(namespace["t"], original_worker)
        self.assertEqual(transport.attempts, 2)
        self.assertEqual(sleeps, [5, 5])

    def test_disconnect_stops_retry_during_wait(self):
        waiting, release = threading.Event(), threading.Event()

        def sleep(_delay):
            waiting.set()
            release.wait(2)

        transport = NativeTransport(sleep)
        namespace = {"transport": transport, "_has_config": True}
        exec(self.patched(), namespace)
        worker = namespace["t"]
        try:
            self.assertTrue(waiting.wait(2))
            transport.close()
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(transport.attempts, 1)
        self.assertFalse(transport.reconnector_thread.is_alive())

    def test_manual_reconnect_replaces_worker_without_reviving_startup_worker(self):
        waiting, release = threading.Event(), threading.Event()

        def sleep(_delay):
            waiting.set()
            release.wait(2)

        transport = NativeTransport(sleep)
        namespace = {"transport": transport, "_has_config": True}
        exec(self.patched(), namespace)
        old_worker = namespace["t"]
        try:
            self.assertTrue(waiting.wait(2))
            transport.reconnect()
            new_worker = transport.reconnector_thread
            self.assertIsNot(new_worker, old_worker)
        finally:
            release.set()
            old_worker.join(2)
            transport.reconnector_thread.join(2)
        self.assertFalse(old_worker.is_alive())
        self.assertFalse(transport.reconnector_thread.is_alive())
        self.assertEqual(transport.attempts, 2)

    def test_absent_connection_configuration_does_not_start_worker(self):
        worker = types.SimpleNamespace(start=lambda: self.fail("unexpected start"))
        namespace = {"transport": types.SimpleNamespace(reconnector_thread=worker),
                     "_has_config": False}
        exec(self.patched(), namespace)
        self.assertNotIn("t", namespace)

    def test_already_running_native_worker_is_not_started_twice(self):
        worker = types.SimpleNamespace(is_alive=lambda: True,
                                       start=lambda: self.fail("duplicate start"))
        namespace = {"transport": types.SimpleNamespace(reconnector_thread=worker),
                     "_has_config": True}
        exec(self.patched(), namespace)
        self.assertIs(namespace["t"], worker)

    def test_patch_is_idempotent_and_validator_checks_actual_startup(self):
        patched = self.patched()
        self.assertTrue(remote_access.legacy_customization_reconnect_patch_current(patched))
        self.assertEqual(remote_access._patch_legacy_customization_reconnect(patched), patched)
        tampered = patched.replace("t.start()", "transport.run()")
        self.assertFalse(remote_access.legacy_customization_reconnect_patch_current(tampered))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            remote_access._patch_legacy_customization_reconnect(tampered)

    def test_missing_startup_is_preserved_and_unknown_or_ambiguous_startup_refused(self):
        self.assertEqual(remote_access._patch_legacy_customization_reconnect(self.CONFIG),
                         self.CONFIG)
        for source in (self.SOURCE.replace("transport.run()", "other_transport.run()"),
                       self.SOURCE + self.SOURCE,
                       self.SOURCE.replace("t.daemon = True", "t.daemon = False")):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    remote_access._patch_legacy_customization_reconnect(source)

    def test_source_spans_preserve_unicode_and_unrelated_statements(self):
        source = '# café\n' + self.SOURCE + '\nuntouched = "value"\n'
        result = remote_access._patch_legacy_customization_reconnect(source)
        self.assertTrue(result.startswith('# café\n'))
        self.assertTrue(result.endswith('\nuntouched = "value"\n'))
        ast.parse(result, feature_version=(3, 10))

    def test_updater_installs_retry_and_preserves_private_original_backup(self):
        source = self.CONFIG + '\n_has_config = True\n' + self.SOURCE
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orca-customizations.py'
            path.write_text(source)
            remote_access.update_legacy_orca_customizations(
                remote_access.RemoteAccessConfig(key='new-key'), path)
            result = path.read_text()
            backup = path.with_name(path.name + '.linux-rdaccess-backup')
            self.assertTrue(remote_access.legacy_customization_reconnect_patch_current(result))
            self.assertEqual(backup.read_text(), source)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(backup).st_mode & 0o777, 0o600)
            remote_access.update_legacy_orca_customizations(
                remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(path.read_text(), result)

    def test_unknown_startup_leaves_configuration_and_backup_untouched(self):
        source = self.CONFIG + self.SOURCE.replace('transport.run()', 'custom_connect()')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orca-customizations.py'
            path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                remote_access.update_legacy_orca_customizations(
                    remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(path.read_text(), source)
            self.assertFalse(path.with_name(path.name + '.linux-rdaccess-backup').exists())


if __name__ == '__main__':
    unittest.main()
