import json
import unittest

from braille_link import NvdaBrailleLink
from rdaccess_dvc import XON
from tests.unit.braille.test_braille_link import FakeChannel


class BrailleReplayTests(unittest.TestCase):
    def setUp(self):
        self.channel = FakeChannel()
        self.ready_calls = 0
        self.link = NvdaBrailleLink(lambda: self.channel, default_cells=80, on_ready=self._ready)
        self.on_ready_action = None

    def _ready(self):
        self.ready_calls += 1
        if self.on_ready_action:
            self.on_ready_action()

    def handshake(self):
        self.link.poll()
        self.channel.incoming.append(bytes([XON]))
        self.link.poll()
        self.channel.incoming.append(
            b'{"type":"protocol_version","version":2,"channel":"NVDA-BRAILLE"}\n'
        )
        self.link.poll()

    def displays(self):
        out = []
        for data in self.channel.writes:
            for line in data.split(b"\n"):
                if line.startswith(b"{"):
                    msg = json.loads(line)
                    if msg["type"] == "display":
                        out.append(msg["cells"])
        return out

    def test_content_offered_before_ready_is_delivered_once_ready(self):
        self.assertFalse(self.link.display([1, 2, 3]))
        self.assertFalse(self.link.display([4, 5]))  # newest wins
        self.handshake()
        shown = self.displays()
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0][:3], [4, 5, 0])
        self.assertEqual(len(shown[0]), 80)

    def test_on_ready_fires_once_per_session_and_its_display_is_not_duplicated(self):
        self.on_ready_action = lambda: self.link.display([9])
        self.link.display([1])  # stale content from before the connection
        self.handshake()
        shown = self.displays()
        self.assertEqual(self.ready_calls, 1)
        self.assertEqual([c[0] for c in shown], [9])

    def test_repeated_protocol_version_does_not_refire_on_ready(self):
        self.handshake()
        self.channel.incoming.append(
            b'{"type":"protocol_version","version":2,"channel":"NVDA-BRAILLE"}\n'
        )
        self.link.poll()
        self.assertEqual(self.ready_calls, 1)

    def test_width_change_refires_on_ready_so_content_can_be_refitted(self):
        self.handshake()
        self.channel.incoming.append(b'{"type":"attribute_value","attribute":"numCells","value":40}\n')
        self.link.poll()
        self.assertEqual(self.ready_calls, 2)
        self.channel.incoming.append(b'{"type":"attribute_value","attribute":"numCells","value":40}\n')
        self.link.poll()
        self.assertEqual(self.ready_calls, 2)  # same width: nothing to refit

    def test_failing_on_ready_does_not_break_the_link(self):
        self.on_ready_action = lambda: 1 / 0
        logging_disabled = __import__("logging")
        logging_disabled.disable(logging_disabled.NOTSET)
        self.addCleanup(logging_disabled.disable, logging_disabled.CRITICAL)
        with self.assertLogs("brailleLink", level="ERROR") as logs:
            self.handshake()
        self.assertTrue(self.link.ready)
        self.assertIn("ZeroDivisionError", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
