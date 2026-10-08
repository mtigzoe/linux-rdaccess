"""Logging must not copy protocol payloads or backend exception messages."""
import json
import logging
import unittest
from unittest import mock

import a11y_link
import braille_link
import rdaccess_dvc
from tests.unit.transport import test_speech_link as fixtures

SECRET = 'private-text-DO-NOT-LOG'


class LoggingPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(logging.disable, logging.root.manager.disable)
        logging.disable(logging.NOTSET)

    def test_receiver_logs_only_byte_counts(self):
        data = json.dumps({'type': 'unknown', 'text': SECRET}).encode() + b'\n'
        with self.assertLogs('rdaccess', level='DEBUG') as logs:
            rdaccess_dvc.Receiver().feed(data)
        self.assertNotIn(SECRET, str(logs.output))
        self.assertNotIn(data[:80].hex(' '), str(logs.output))

    def test_speech_logs_neither_unknown_messages_nor_dropped_text(self):
        channel = fixtures.FakeChannel()
        link = rdaccess_dvc.NvdaSpeechLink(lambda: channel)
        link.poll()
        channel.incoming.append(json.dumps({'type': SECRET, 'sequence': [SECRET]}).encode() + b'\n')
        with self.assertLogs('rdaccess', level='DEBUG') as logs:
            link.poll()
            link.speak(SECRET)
        self.assertNotIn(SECRET, str(logs.output))

    def test_links_do_not_log_open_or_read_exception_text(self):
        for cls, logger in ((rdaccess_dvc.NvdaSpeechLink, 'rdaccess'),
                            (braille_link.NvdaBrailleLink, 'brailleLink'),
                            (a11y_link.NvdaA11yLink, 'a11yLink')):
            with self.subTest(link=cls):
                link = cls(mock.Mock(side_effect=RuntimeError(SECRET)))
                with self.assertLogs(logger, level='DEBUG') as logs:
                    link.poll()
                self.assertNotIn(SECRET, str(logs.output))
                channel = fixtures.FakeChannel()
                link = cls(lambda: channel)
                link.poll()
                channel.read_error = OSError(SECRET)
                with self.assertLogs(logger, level='DEBUG') as logs:
                    link.poll()
                self.assertNotIn(SECRET, str(logs.output))

    def test_a11y_callback_exception_and_unknown_payload_are_private(self):
        channel = fixtures.FakeChannel()
        link = a11y_link.NvdaA11yLink(lambda: channel, on_action=mock.Mock(side_effect=RuntimeError(SECRET)))
        link.poll()
        channel.incoming.append(bytes([rdaccess_dvc.XON]))
        link.poll()
        channel.incoming.append(json.dumps({'type': 'a11y_action', 'object_id': SECRET, 'action_index': 0}).encode() + b'\n')
        with self.assertLogs('a11yLink', level='DEBUG') as logs:
            link.poll()
        self.assertNotIn(SECRET, str(logs.output))
