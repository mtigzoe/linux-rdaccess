import json
import unittest
from unittest import mock

from braille_link import NvdaBrailleLink
from rdaccess_dvc import LEGACY_GENERIC_ATTRIBUTE, XON


class FakeChannel:
    def __init__(self):
        self.incoming = []
        self.writes = []
        self.closed = False

    def read(self, timeout_ms=0):
        return self.incoming.pop(0) if self.incoming else b""

    def write(self, data, timeout=5.0):
        self.writes.append(bytes(data))

    def close(self):
        self.closed = True


class BrailleLinkTests(unittest.TestCase):
    def setUp(self):
        self.channel = FakeChannel()
        self.link = NvdaBrailleLink(lambda: self.channel, default_cells=80)

    def connect_v2(self):
        self.link.poll()
        self.channel.incoming.append(bytes([XON]))
        self.link.poll()
        legacy = self.channel.writes[-1]
        self.assertEqual(legacy[0], ord("B"))
        self.assertEqual(legacy[1], LEGACY_GENERIC_ATTRIBUTE)
        self.assertIn(b"protocolVersion", legacy)
        self.channel.incoming.append(
            json.dumps(
                {"type": "protocol_version", "version": 2, "channel": "NVDA-BRAILLE"}
            ).encode()
            + b"\n"
        )
        self.link.poll()

    def json_writes(self):
        result = []
        for data in self.channel.writes:
            for line in data.split(b"\n"):
                if line.startswith(b"{"):
                    result.append(json.loads(line))
        return result

    def test_xon_starts_with_legacy_protocol_version_then_json(self):
        self.connect_v2()
        messages = self.json_writes()
        self.assertEqual(messages[0]["type"], "protocol_version")
        self.assertEqual(messages[0]["channel"], "NVDA-BRAILLE")
        self.assertEqual(messages[1], {"attribute": "numCells", "type": "attribute_request"})
        self.assertTrue(self.link.ready)

    def test_legacy_focus_request_gets_legacy_zero_reply(self):
        self.connect_v2()
        self.channel.writes.clear()
        sep = bytes((0x60,))
        payload = sep + b"timeSinceInput" + sep
        frame = (
            b"B"
            + bytes((LEGACY_GENERIC_ATTRIBUTE,))
            + len(payload).to_bytes(2, "little")
            + payload
        )
        self.channel.incoming.append(frame)
        self.link.poll()
        self.assertEqual(len(self.channel.writes), 1)
        reply = self.channel.writes[0]
        self.assertEqual(reply[:2], b"B@")
        self.assertIn(sep + b"timeSinceInput" + sep + (0).to_bytes(4, "little"), reply)

    def test_num_cells_updates_and_display_is_padded(self):
        self.connect_v2()
        self.channel.incoming.append(
            b'{"type":"attribute_value","attribute":"numCells","value":4}\n'
        )
        self.link.poll()
        self.assertEqual(self.link.num_cells, 4)
        self.channel.writes.clear()
        self.assertTrue(self.link.display([1, 2]))
        msg = self.json_writes()[-1]
        self.assertEqual(msg["type"], "display")
        self.assertEqual(msg["cells"], [1, 2, 0, 0])

    def test_failed_handshake_stops_batch_and_reconnects_cleanly(self):
        replacement = FakeChannel()
        channels = iter((self.channel, replacement))
        now = [0.0]
        link = NvdaBrailleLink(lambda: next(channels), clock=lambda: now[0])
        link.poll()
        self.channel.incoming.append(
            bytes([XON])
            + b'{"type":"protocol_version","version":2}\n'
            + b'{"type":"attribute_value","attribute":"numCells","value":128}\n'
        )
        with mock.patch.object(
            self.channel, "write", side_effect=ConnectionError("channel lost")
        ) as write:
            link.poll()
        self.assertEqual(write.call_count, 1)
        self.assertTrue(self.channel.closed)
        self.assertIsNone(link._channel)
        self.assertFalse(link.ready)
        self.assertEqual(link.num_cells, 80)

        now[0] = 2.0
        link.poll()
        self.assertIsNone(link._channel)
        now[0] = 3.0
        link.poll()
        self.assertIs(link._channel, replacement)
        replacement.incoming.append(
            bytes([XON])
            + b'{"type":"protocol_version","version":2}\n'
            + b'{"type":"attribute_value","attribute":"numCells","value":4}\n'
        )
        link.poll()
        self.assertTrue(link.ready)
        self.assertEqual(link.num_cells, 4)

    def test_failed_attribute_reply_stops_remaining_drained_messages(self):
        self.connect_v2()
        self.channel.incoming.append(
            b'{"type":"attribute_request","attribute":"protocolVersion"}\n'
            + b'{"type":"protocol_version","version":2}\n'
            + b'{"type":"attribute_value","attribute":"numCells","value":128}\n'
        )
        with mock.patch.object(
            self.channel, "write", side_effect=ConnectionError("channel lost")
        ) as write:
            self.link.poll()
        self.assertEqual(write.call_count, 1)
        self.assertTrue(self.channel.closed)
        self.assertIsNone(self.link._channel)
        self.assertFalse(self.link.ready)
        self.assertEqual(self.link.num_cells, 80)


if __name__ == "__main__":
    unittest.main()
