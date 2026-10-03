from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import remote_access


class RemoteAccessConfigTests(unittest.TestCase):
    def test_defaults_use_public_nvda_remote_relay(self):
        config = remote_access.RemoteAccessConfig()
        self.assertEqual(config.host, "nvdaremote.com")
        self.assertEqual(config.port, 6837)
        self.assertEqual(config.role, "host")
        self.assertEqual(config.orca_connection_type, "slave")
        self.assertFalse(config.ready)

    def test_client_maps_to_master(self):
        config = remote_access.RemoteAccessConfig(role="client")
        self.assertEqual(config.orca_connection_type, "master")

    def test_generated_keys_are_nonempty_and_distinct(self):
        first = remote_access.generate_key()
        second = remote_access.generate_key()
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_redacted_status_never_contains_key(self):
        secret = "super-secret-channel-key"
        config = remote_access.RemoteAccessConfig(key=secret)
        encoded = json.dumps(config.redacted())
        self.assertNotIn(secret, encoded)
        self.assertTrue(config.redacted()["key_configured"])

    def test_save_uses_private_permissions_when_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote.json"
            config = remote_access.RemoteAccessConfig(key="secret")
            remote_access.save_config(config, path)
            loaded = remote_access.load_config(path)
            self.assertEqual(loaded, config)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class LegacyConfigTests(unittest.TestCase):
    def test_apply_updates_endpoint_key_and_role(self):
        original = """YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "key"
transport = RelayTransport(
    serializer,
    ("host", 6837),
    channel="key",
    connection_type="slave"
)
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "orca-customizations.py"
            path.write_text(original, encoding="utf-8")
            config = remote_access.RemoteAccessConfig(
                host="nvdaremote.com",
                port=6837,
                role="client",
                key="abc123",
            )
            remote_access.update_legacy_orca_customizations(config, path)
            result = path.read_text(encoding="utf-8")

            self.assertIn('YOUR_NVDAREMOTE_SERVER_ADDRESS = "nvdaremote.com"', result)
            self.assertIn("YOUR_NVDAREMOTE_SERVER_PORT = 6837", result)
            self.assertIn('YOUR_NVDAREMOTE_KEY = "abc123"', result)
            self.assertIn('connection_type="master"', result)
            self.assertTrue(path.with_name(path.name + ".linux-rdaccess-backup").exists())


    def test_legacy_controller_patch_adds_speech_cancel_and_braille_trace(self):
        original = '''class RemoteController:
    def _on_remote_key(self, key_name=None, pressed=None, modifiers=None, **kwargs):
        self.local_machine.send_key(
            key_name=key_name, pressed=pressed, modifiers=modifiers,
        )

    def _on_remote_braille_input(self, **kwargs):
        log.debug("Remote braille input: %s" % kwargs)
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(original, encoding="utf-8")

            changed = remote_access.patch_legacy_orca_remote_controller(path)
            result = path.read_text(encoding="utf-8")

            self.assertTrue(changed)
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertIn("self.local_machine.cancel_speech()", result)
            self.assertIn("orca-remote-braille-input.log", result)
            self.assertIn('"routingIndex"', result)
            self.assertTrue(path.with_name(path.name + ".linux-rdaccess-backup").exists())

    def test_legacy_controller_patch_is_idempotent(self):
        original = '''class RemoteController:
    def _on_remote_key(self, key_name=None, pressed=None, modifiers=None, **kwargs):
        self.local_machine.send_key(
            key_name=key_name, pressed=pressed, modifiers=modifiers,
        )

    def _on_remote_braille_input(self, **kwargs):
        log.debug("Remote braille input: %s" % kwargs)
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(original, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            once = path.read_text(encoding="utf-8")
            self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))
            self.assertEqual(path.read_text(encoding="utf-8"), once)


class ValidationTests(unittest.TestCase):
    def test_bad_port_rejected(self):
        with self.assertRaises(ValueError):
            remote_access.validate_port(0)

    def test_whitespace_host_rejected(self):
        with self.assertRaises(ValueError):
            remote_access.validate_host("bad host")


if __name__ == "__main__":
    unittest.main()
