import json
import unittest

from a11y_link import A11Y_CHANNEL, NvdaA11yLink
from rdaccess_dvc import XOFF, XON


class FakeChannel:
    def __init__(self):
        self.incoming = []
        self.written = []
        self.closed = False

    def read(self, timeout_ms=0):
        return self.incoming.pop(0) if self.incoming else b""

    def write(self, data, timeout=5.0):
        for raw in data.split(b"\n"):
            if raw:
                self.written.append(json.loads(raw))

    def close(self):
        self.closed = True


class A11yLinkTests(unittest.TestCase):
    def setUp(self):
        self.channels = []
        self.link = NvdaA11yLink(self._open)

    def _open(self):
        ch = FakeChannel()
        self.channels.append(ch)
        return ch

    def connect(self):
        self.link.poll()
        ch = self.channels[-1]
        ch.incoming.append(bytes([XON]))
        self.link.poll()
        return ch

    def test_xon_announces_protocol_and_channel(self):
        ch = self.connect()
        self.assertTrue(self.link.ready)
        self.assertEqual(ch.written[0]["type"], "protocol_version")
        self.assertEqual(ch.written[0]["version"], 2)
        self.assertEqual(ch.written[0]["channel"], A11Y_CHANNEL)

    def test_focus_tree_is_sent_after_xon(self):
        ch = self.connect()
        ch.written.clear()
        objects = [{"id": "1", "parent_id": None, "name": "Save", "role": "push button"}]
        self.assertTrue(self.link.send_focus(focus_id="1", objects=objects))
        self.assertEqual(ch.written, [{"focus_id": "1", "objects": objects, "type": "a11y_focus"}])

    def test_focus_is_dropped_until_xon(self):
        self.link.poll()
        self.assertFalse(self.link.send_focus(focus_id="1", objects=[]))

    def test_xoff_stops_object_updates(self):
        ch = self.connect()
        ch.incoming.append(bytes([XOFF]))
        self.link.poll()
        self.assertFalse(self.link.ready)
        self.assertFalse(self.link.send_focus(focus_id="1", objects=[]))


if __name__ == "__main__":
    unittest.main()
