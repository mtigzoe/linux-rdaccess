import json
import unittest

from a11y_link import A11Y_CHANNEL, NvdaA11yLink, decode_action_request
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


class ActionRequestDecodeTests(unittest.TestCase):
    def test_valid_request_decodes(self):
        self.assertEqual(
            decode_action_request(
                {"type": "a11y_action", "object_id": "abc", "action_index": 2},
            ),
            ("abc", 2),
        )

    def test_non_action_message_is_ignored(self):
        self.assertIsNone(decode_action_request({"type": "ping"}))

    def test_invalid_request_is_rejected(self):
        for message in (
            {"type": "a11y_action", "object_id": "", "action_index": 0},
            {"type": "a11y_action", "object_id": "abc", "action_index": -1},
            {"type": "a11y_action", "object_id": "abc", "action_index": 32},
            {"type": "a11y_action", "object_id": "abc", "action_index": True},
        ):
            with self.subTest(message=message):
                self.assertIsNone(decode_action_request(message))


class A11yLinkTests(unittest.TestCase):
    def setUp(self):
        self.channels = []
        self.actions = []
        self.link = NvdaA11yLink(self._open, on_action=lambda object_id, index: self.actions.append((object_id, index)))

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
        self.assertEqual(
            ch.written,
            [{"focus_id": "1", "objects": objects, "type": "a11y_focus"}],
        )

    def test_focus_before_xon_is_replayed_after_handshake(self):
        self.link.poll()
        ch = self.channels[-1]
        objects = [{"id": "1", "parent_id": None, "name": "Save", "role": "push button"}]
        self.assertFalse(self.link.send_focus(focus_id="1", objects=objects))
        self.assertEqual(ch.written, [])

        ch.incoming.append(bytes([XON]))
        self.link.poll()

        self.assertEqual(ch.written[0]["type"], "protocol_version")
        self.assertEqual(
            ch.written[1],
            {"focus_id": "1", "objects": objects, "type": "a11y_focus"},
        )

    def test_only_latest_focus_is_replayed_after_handshake(self):
        self.link.poll()
        ch = self.channels[-1]
        first = [{"id": "1", "parent_id": None, "name": "First", "role": "push button"}]
        second = [{"id": "2", "parent_id": None, "name": "Second", "role": "push button"}]
        self.assertFalse(self.link.send_focus(focus_id="1", objects=first))
        self.assertFalse(self.link.send_focus(focus_id="2", objects=second))

        ch.incoming.append(bytes([XON]))
        self.link.poll()

        self.assertEqual(len(ch.written), 2)
        self.assertEqual(ch.written[1]["focus_id"], "2")
        self.assertEqual(ch.written[1]["objects"], second)

    def test_valid_action_message_is_dispatched_after_handshake(self):
        ch = self.connect()
        ch.incoming.append(
            b'{"type":"a11y_action","object_id":"abc","action_index":1}\n'
        )
        self.link.poll()
        self.assertEqual(self.actions, [("abc", 1)])

    def test_action_before_xon_is_ignored(self):
        self.link.poll()
        ch = self.channels[-1]
        ch.incoming.append(
            b'{"type":"a11y_action","object_id":"abc","action_index":0}\n'
        )
        self.link.poll()
        self.assertEqual(self.actions, [])

    def test_invalid_action_messages_are_ignored(self):
        ch = self.connect()
        for payload in (
            b'{"type":"a11y_action","object_id":"","action_index":0}\n',
            b'{"type":"a11y_action","object_id":"abc","action_index":-1}\n',
            b'{"type":"a11y_action","object_id":"abc","action_index":32}\n',
            b'{"type":"a11y_action","object_id":"abc","action_index":true}\n',
        ):
            ch.incoming.append(payload)
        self.link.poll()
        self.assertEqual(self.actions, [])

    def test_action_callback_exception_does_not_drop_channel(self):
        def fail(_object_id, _index):
            raise RuntimeError("boom")

        link = NvdaA11yLink(self._open, on_action=fail)
        link.poll()
        ch = self.channels[-1]
        ch.incoming.append(bytes([XON]))
        link.poll()
        ch.incoming.append(
            b'{"type":"a11y_action","object_id":"abc","action_index":0}\n'
        )
        link.poll()
        self.assertTrue(link.ready)
        self.assertFalse(ch.closed)

    def test_xoff_queues_latest_focus_until_next_xon(self):
        ch = self.connect()
        ch.written.clear()
        ch.incoming.append(bytes([XOFF]))
        self.link.poll()
        self.assertFalse(self.link.ready)

        objects = [{"id": "2", "parent_id": None, "name": "Reconnect", "role": "push button"}]
        self.assertFalse(self.link.send_focus(focus_id="2", objects=objects))
        self.assertEqual(ch.written, [])

        ch.incoming.append(bytes([XON]))
        self.link.poll()

        self.assertEqual(ch.written[0]["type"], "protocol_version")
        self.assertEqual(ch.written[1]["focus_id"], "2")


if __name__ == "__main__":
    unittest.main()
