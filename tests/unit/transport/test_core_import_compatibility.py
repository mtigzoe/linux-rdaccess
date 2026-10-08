"""Regression guards for core-module moves and stable public imports.

The xrdp bridge and existing tests still import modules from the repository
root. Keep their public classes and functions identical to the package ones.
"""
from __future__ import annotations

import unittest

import announcer
import a11y_link
import braille_link
import rdaccess_dvc
import nvda_remote_check
from linux_rdaccess_core.connection import nvda_remote_check as connection_check
from linux_rdaccess_core import announcer as core_announcer
from linux_rdaccess_core import a11y_link as core_a11y_link
from linux_rdaccess_core import braille_link as core_braille_link
from linux_rdaccess_core import rdaccess_dvc as core_rdaccess_dvc
from linux_rdaccess_core.accessibility import announcer as accessibility_announcer
from linux_rdaccess_core.transport import a11y_link as transport_a11y_link
from linux_rdaccess_core.transport import braille_link as transport_braille_link
from linux_rdaccess_core.transport import rdaccess_dvc as transport_rdaccess_dvc


class RootImportCompatibilityTests(unittest.TestCase):
    def test_implementations_are_in_named_subpackages(self):
        self.assertIs(core_announcer.Announcer, accessibility_announcer.Announcer)
        self.assertIs(core_a11y_link.NvdaA11yLink, transport_a11y_link.NvdaA11yLink)
        self.assertIs(core_braille_link.NvdaBrailleLink, transport_braille_link.NvdaBrailleLink)
        self.assertIs(core_rdaccess_dvc.DvcChannel, transport_rdaccess_dvc.DvcChannel)

    def test_connection_check_keeps_original_api(self):
        for name in ("RemoteConfig", "RemoteStatus", "parse_remote_config", "collect_status", "main"):
            with self.subTest(name=name):
                self.assertIs(getattr(nvda_remote_check, name), getattr(connection_check, name))

    def test_announcer_remains_same_class_and_constants(self):
        self.assertIs(announcer.Announcer, core_announcer.Announcer)
        self.assertIs(announcer.HANDLED, core_announcer.HANDLED)

    def test_a11y_link_still_exposes_protocol_and_class(self):
        for name in ("NvdaA11yLink", "decode_pong", "decode_action_request"):
            with self.subTest(name=name):
                self.assertIs(getattr(a11y_link, name), getattr(core_a11y_link, name))

    def test_braille_link_still_exposes_transport(self):
        self.assertIs(braille_link.NvdaBrailleLink, core_braille_link.NvdaBrailleLink)

    def test_dvc_transport_still_exposes_protocol_helpers(self):
        for name in ("DvcChannel", "Receiver", "NvdaSpeechLink",
                     "send_json", "load_xrdpapi", "PROTOCOL_VERSION"):
            with self.subTest(name=name):
                self.assertIs(getattr(rdaccess_dvc, name), getattr(core_rdaccess_dvc, name))


if __name__ == "__main__":
    unittest.main()
