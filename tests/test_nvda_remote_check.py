from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import nvda_remote_check


class ParseRemoteConfigTests(unittest.TestCase):
    def test_python_values_with_comments_and_escapes_are_parsed_without_execution(self):
        text = ('YOUR_NVDAREMOTE_SERVER_ADDRESS = "relay\\u00e9.example" # host\n'
                'YOUR_NVDAREMOTE_SERVER_PORT = 6837 # port\n'
                'YOUR_NVDAREMOTE_KEY = ("private\\\\key") # key\n'
                'raise RuntimeError("must not execute")\n')
        config = nvda_remote_check.parse_remote_config(text)
        self.assertEqual(config.server, 'relayé.example')
        self.assertEqual(config.port, 6837)
        self.assertTrue(config.key_configured)
        self.assertNotIn('private', repr(config))

    def test_ambiguous_or_invalid_configuration_does_not_report_ready(self):
        source = ('YOUR_NVDAREMOTE_SERVER_ADDRESS = "relay.example"\n'
                  'YOUR_NVDAREMOTE_SERVER_PORT = 6837\n'
                  'YOUR_NVDAREMOTE_KEY = "private"\n')
        for tail in ('YOUR_NVDAREMOTE_KEY = "key"\n', 'if invalid\n'):
            config = nvda_remote_check.parse_remote_config(source + tail)
            self.assertFalse(config.key_configured)
            self.assertNotIn('private', repr(config))

    def test_parses_config_without_returning_key(self):
        text = """
YOUR_NVDAREMOTE_SERVER_ADDRESS = "192.168.1.81"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "super-secret-value"
"""
        config = nvda_remote_check.parse_remote_config(text)

        self.assertEqual(config.server, "192.168.1.81")
        self.assertEqual(config.port, 6837)
        self.assertTrue(config.key_configured)
        self.assertNotIn("super-secret-value", repr(config))

    def test_placeholders_are_not_ready(self):
        text = """
YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "key"
"""
        config = nvda_remote_check.parse_remote_config(text)
        self.assertIsNone(config.server)
        self.assertEqual(config.port, 6837)
        self.assertFalse(config.key_configured)

    def test_installer_rewritten_host_still_counts_as_configured(self):
        text = """
YOUR_NVDAREMOTE_SERVER_ADDRESS = "nvdaremote.com"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "1234567"
"""
        config = nvda_remote_check.parse_remote_config(text)
        self.assertEqual(config.server, "nvdaremote.com")
        self.assertTrue(config.key_configured)


class CollectStatusTests(unittest.TestCase):
    def test_json_status_never_contains_key(self):
        secret = "do-not-print-this"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "orca-customizations.py"
            path.write_text(
                'YOUR_NVDAREMOTE_SERVER_ADDRESS = "192.168.1.81"\n'
                'YOUR_NVDAREMOTE_SERVER_PORT = 6837\n'
                f'YOUR_NVDAREMOTE_KEY = "{secret}"\n',
                encoding="utf-8",
            )
            with mock.patch("nvda_remote_check.shutil.which", return_value="/usr/bin/tool"):
                status = nvda_remote_check.collect_status(
                    path,
                    environ={"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"},
                )

        encoded = json.dumps(status.__dict__)
        self.assertNotIn(secret, encoded)
        self.assertTrue(status.ready)
        self.assertEqual(status.display, ":0")
        self.assertEqual(status.session_type, "x11")
        self.assertTrue(status.xdotool_available)

    def test_missing_config_is_not_ready(self):
        status = nvda_remote_check.collect_status(
            Path("/definitely/not/present"),
            environ={},
        )
        self.assertFalse(status.config_exists)
        self.assertFalse(status.key_configured)
        self.assertFalse(status.ready)


if __name__ == "__main__":
    unittest.main()
