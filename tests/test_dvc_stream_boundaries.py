"""DVC malformed-frame and reconnect boundaries must not stop the shared poller."""

import json
import unittest

from a11y_link import NvdaA11yLink
from braille_link import NvdaBrailleLink
from rdaccess_dvc import Receiver, XOFF, XON, NvdaSpeechLink


class Channel:
    def __init__(self):
        self.incoming = []
        self.written = []
        self.closed = False

    def read(self, timeout=0):
        return self.incoming.pop(0) if self.incoming else b""

    def write(self, data):
        self.written.append(data)

    def close(self):
        self.closed = True


def message(**kwargs):
    return json.dumps(kwargs).encode() + b"\n"


class ReceiverBoundaryTests(unittest.TestCase):
    def test_excessively_nested_json_is_rejected_and_next_message_is_read(self):
        receiver = Receiver()
        receiver.feed(b'{"data":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}\n"
                      + message(type="ping"))
        self.assertEqual(receiver.drain(), [{"type": "ping"}])
        self.assertGreater(receiver.junk_bytes, 0)

    def test_truncated_json_cannot_swallow_disconnect_and_reconnect(self):
        receiver = Receiver()
        receiver.feed(bytes([XON]) + b'{"type":"index","index":')
        receiver.feed(bytes([XOFF]))
        self.assertFalse(receiver.xon)
        receiver.feed(bytes([XON]) + message(type="protocol_version", version=2))
        self.assertTrue(receiver.xon)
        self.assertEqual(receiver.xon_count, 2)
        self.assertEqual(receiver.drain(), [{"type": "protocol_version", "version": 2}])

    def test_escaped_control_characters_remain_json_payload(self):
        receiver = Receiver()
        receiver.feed(bytes([XON]) + message(type="example", text="before\x13after\x11"))
        self.assertEqual(receiver.drain(), [{"type": "example", "text": "before\x13after\x11"}])
        self.assertTrue(receiver.xon)
        self.assertEqual(receiver.xon_count, 1)

    def test_binary_control_bytes_remain_inside_legacy_payload(self):
        receiver = Receiver()
        receiver.feed(bytes([XON]) + b"SA\x02\x00" + bytes([XOFF, XON]))
        self.assertEqual(receiver.legacy_frames, 1)
        self.assertTrue(receiver.xon)
        self.assertEqual(receiver.xon_count, 1)


class LinkBoundaryTests(unittest.TestCase):
    def test_a11y_action_callback_reopen_cannot_dispatch_remaining_old_batch(self):
        channels = [Channel(), Channel()]
        pending = iter(channels)
        actions = []
        link = None

        def action(object_id, index):
            actions.append((object_id, index))
            if object_id == "first":
                link.close()
                link.poll()
                channels[1].incoming.append(bytes([XON]))
                link.poll()

        link = NvdaA11yLink(lambda: next(pending), retry_interval=0, on_action=action)
        link.poll()
        channels[0].incoming.append(bytes([XON]))
        link.poll()
        channels[0].incoming.append(
            message(type="a11y_action", object_id="first", action_index=0)
            + message(type="a11y_action", object_id="stale", action_index=0))
        link.poll()
        self.assertTrue(channels[0].closed)
        self.assertIs(link._channel, channels[1])
        self.assertTrue(link.ready)
        self.assertEqual(actions, [("first", 0)])

    def test_ready_callback_close_without_reopen_preserves_queued_focus(self):
        first, second = Channel(), Channel()
        channels = iter((first, second))
        link = None
        callbacks = []

        def ready():
            callbacks.append(1)
            if len(callbacks) == 1:
                link.close()

        link = NvdaA11yLink(lambda: next(channels), retry_interval=0, on_ready=ready)
        link.send_focus(focus_id="target", objects=[])
        link.poll()
        first.incoming.append(bytes([XON]))
        link.poll()
        self.assertFalse(link.ready)
        self.assertEqual([json.loads(data)["type"] for data in first.written], ["protocol_version"])
        link.poll()
        second.incoming.append(bytes([XON]))
        link.poll()
        self.assertEqual([json.loads(data)["type"] for data in second.written],
                         ["protocol_version", "a11y_focus"])

    def test_xon_followed_by_xoff_does_not_announce_ready_or_start_handshake(self):
        for cls in (NvdaSpeechLink, NvdaA11yLink, NvdaBrailleLink):
            with self.subTest(link=cls.__name__):
                channel = Channel()
                calls = []
                kwargs = {} if cls is NvdaBrailleLink else {"on_ready": lambda: calls.append(1)}
                link = cls(lambda: channel, **kwargs)
                link.poll()
                channel.incoming.append(bytes([XON, XOFF]))
                link.poll()
                self.assertFalse(link.ready)
                self.assertEqual(channel.written, [])
                self.assertEqual(calls, [])
                channel.incoming.append(bytes([XON]))
                link.poll()
                self.assertEqual(len(channel.written), 1)

    def test_speech_ready_callback_exception_does_not_stop_next_poll(self):
        channel = Channel()
        calls = []

        def callback():
            calls.append(1)
            raise RuntimeError("callback failed")

        link = NvdaSpeechLink(lambda: channel, on_ready=callback)
        link.poll()
        channel.incoming.append(bytes([XON]))
        link.poll()
        self.assertTrue(link.ready)
        channel.incoming.append(message(type="index", index=1))
        link.poll()
        self.assertEqual(link._rx.messages, [])
        channel.incoming.append(bytes([XOFF, XON]))
        link.poll()
        self.assertEqual(calls, [1, 1])

    def test_braille_nonfinite_numbers_do_not_stop_negotiation_and_updates(self):
        for kind, field in (("protocol_version", "version"), ("attribute_value", "value")):
            with self.subTest(kind=kind):
                channel = Channel()
                link = NvdaBrailleLink(lambda: channel)
                link.poll()
                channel.incoming.append(bytes([XON]))
                link.poll()
                malformed = {"type": kind, field: float("inf"), "attribute": "numCells"}
                channel.incoming.append(message(**malformed)
                    + message(type="protocol_version", version=2)
                    + message(type="attribute_value", attribute="numCells", value=4))
                link.poll()
                self.assertTrue(link.ready)
                self.assertEqual(link.num_cells, 4)
                self.assertTrue(link.display([1, 2]))

    def test_braille_forged_legacy_driver_metadata_does_not_kill_polling(self):
        for driver in ("bad", None, -1, 256, True, float("inf")):
            with self.subTest(driver=driver):
                channel = Channel()
                link = NvdaBrailleLink(lambda: channel)
                link.poll()
                channel.incoming.append(bytes([XON]) + message(type="protocol_version", version=2))
                link.poll()
                channel.written.clear()
                malformed = message(type="attribute_request", attribute="protocolVersion",
                                    _legacy_driver_type=driver)
                channel.incoming.append(malformed + message(type="attribute_request", attribute="timeSinceInput"))
                link.poll()
                self.assertTrue(link.ready)
                self.assertEqual(json.loads(channel.written[-1]),
                                 {"type": "attribute_value", "attribute": "timeSinceInput", "value": 0})


if __name__ == "__main__":
    unittest.main()
