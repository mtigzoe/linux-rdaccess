import json
import unittest
from unittest import mock

from a11y_link import A11Y_CHANNEL, NvdaA11yLink, decode_action_request, decode_pong
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


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class HeartbeatDecodeTests(unittest.TestCase):
    def test_valid_pong_decodes(self):
        self.assertEqual(decode_pong({"type": "a11y_pong", "nonce": 4}), 4)

    def test_invalid_pong_is_rejected(self):
        for message in (
            {"type": "a11y_pong", "nonce": -1},
            {"type": "a11y_pong", "nonce": True},
            {"type": "a11y_pong", "nonce": 0x80000000},
            {"type": "other", "nonce": 4},
        ):
            with self.subTest(message=message):
                self.assertIsNone(decode_pong(message))


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

    def test_action_write_failure_stops_batch_before_reconnect_handshake(self):
        clock = FakeClock()
        self.link._clock = clock
        ch = self.connect()

        def action(object_id, index):
            self.actions.append((object_id, index))
            self.link.send_focus(focus_id=object_id, objects=[])

        self.link._on_action = action
        ch.incoming.append(
            b'{"type":"a11y_action","object_id":"target","action_index":0}\n'
            + b'{"type":"a11y_action","object_id":"later","action_index":0}\n'
        )
        with mock.patch.object(
            ch, "write", side_effect=ConnectionError("channel lost")
        ) as write:
            self.link.poll()
        self.assertEqual(write.call_count, 1)
        self.assertEqual(self.actions, [("target", 0)])
        self.assertTrue(ch.closed)
        self.assertIsNone(self.link._channel)
        self.assertFalse(self.link.ready)

        clock.advance(2.0)
        self.link.poll()
        self.assertEqual(len(self.channels), 1)
        clock.advance(1.0)
        self.link.poll()
        self.assertEqual(len(self.channels), 2)
        replacement = self.channels[-1]
        self.assertFalse(self.link.ready)
        replacement.incoming.append(bytes([XON]))
        self.link.poll()
        self.assertTrue(self.link.ready)
        self.assertEqual(replacement.written[0]["type"], "protocol_version")
        self.assertEqual(
            replacement.written[1],
            {"type": "a11y_focus", "focus_id": "target", "objects": []},
        )
        self.assertEqual(self.actions, [("target", 0)])

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

    def test_text_update_is_sent_after_xon(self):
        ch = self.connect()
        ch.written.clear()
        self.assertTrue(
            self.link.send_text_update(
                object_id="editor",
                event="caret",
                text_supported=True,
                text="hello",
                text_truncated=False,
                caret_offset=3,
                selection_start=None,
                selection_end=None,
            ),
        )
        self.assertEqual(
            ch.written,
            [
                {
                    "type": "a11y_text",
                    "object_id": "editor",
                    "event": "caret",
                    "text_supported": True,
                    "text": "hello",
                    "text_truncated": False,
                    "caret_offset": 3,
                    "selection_start": None,
                    "selection_end": None,
                },
            ],
        )

    def test_latest_text_update_is_replayed_after_handshake(self):
        self.link.poll()
        ch = self.channels[-1]
        self.assertFalse(
            self.link.send_text_update(
                object_id="editor",
                event="caret",
                text_supported=True,
                text="one",
                text_truncated=False,
                caret_offset=1,
                selection_start=None,
                selection_end=None,
            ),
        )
        self.assertFalse(
            self.link.send_text_update(
                object_id="editor",
                event="caret",
                text_supported=True,
                text="two",
                text_truncated=False,
                caret_offset=2,
                selection_start=None,
                selection_end=None,
            ),
        )
        ch.incoming.append(bytes([XON]))
        self.link.poll()

        self.assertEqual(ch.written[0]["type"], "protocol_version")
        self.assertEqual(ch.written[-1]["type"], "a11y_text")
        self.assertEqual(ch.written[-1]["text"], "two")
        self.assertEqual(ch.written[-1]["caret_offset"], 2)

    def test_text_update_replays_after_xoff_xon(self):
        ch = self.connect()
        ch.written.clear()
        ch.incoming.append(bytes([XOFF]))
        self.link.poll()
        self.assertFalse(
            self.link.send_text_update(
                object_id="editor",
                event="textChange",
                text_supported=True,
                text="changed",
                text_truncated=False,
                caret_offset=7,
                selection_start=None,
                selection_end=None,
            ),
        )
        ch.incoming.append(bytes([XON]))
        self.link.poll()
        self.assertEqual(ch.written[0]["type"], "protocol_version")
        self.assertEqual(ch.written[1]["type"], "a11y_text")
        self.assertEqual(ch.written[1]["event"], "textChange")

    def test_valid_action_message_is_dispatched_after_handshake(self):
        ch = self.connect()
        ch.incoming.append(
            b'{"type":"a11y_action","object_id":"abc","action_index":1}\n'
        )
        self.link.poll()
        self.assertEqual(self.actions, [("abc", 1)])

    def test_xon_and_action_in_same_batch_handshake_before_dispatch(self):
        seen = []
        link = NvdaA11yLink(
            self._open,
            on_action=lambda object_id, index: seen.append(
                (object_id, index, list(self.channels[-1].written))
            ),
        )
        link.poll()
        ch = self.channels[-1]
        ch.incoming.append(
            bytes([XON])
            + b'{"type":"a11y_action","object_id":"abc","action_index":0}\n'
        )
        link.poll()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:2], ("abc", 0))
        self.assertTrue(seen[0][2])
        self.assertEqual(seen[0][2][0]["type"], "protocol_version")

    def test_failed_same_batch_handshake_prevents_action_dispatch(self):
        seen = []
        link = NvdaA11yLink(
            self._open,
            on_action=lambda object_id, index: seen.append((object_id, index)),
        )
        link.poll()
        ch = self.channels[-1]
        ch.incoming.append(
            bytes([XON])
            + b'{"type":"a11y_action","object_id":"abc","action_index":0}\n'
        )
        with mock.patch.object(ch, "write", side_effect=ConnectionError("handshake lost")):
            link.poll()
        self.assertEqual(seen, [])
        self.assertFalse(link.ready)
        self.assertTrue(ch.closed)

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

    def test_heartbeat_pong_keeps_channel_ready(self):
        clock = FakeClock()
        link = NvdaA11yLink(
            self._open,
            clock=clock,
            heartbeat_interval=5.0,
            heartbeat_timeout=10.0,
        )
        link.poll()
        ch = self.channels[-1]
        ch.incoming.append(bytes([XON]))
        link.poll()
        ch.written.clear()

        clock.advance(5.0)
        link.poll()
        self.assertEqual(ch.written, [{"nonce": 0, "type": "a11y_ping"}])

        ch.incoming.append(b'{"type":"a11y_pong","nonce":0}\n')
        link.poll()
        self.assertTrue(link.ready)
        self.assertFalse(ch.closed)

    def test_missing_heartbeat_pong_drops_and_reopens_channel(self):
        clock = FakeClock()
        link = NvdaA11yLink(
            self._open,
            clock=clock,
            retry_interval=3.0,
            heartbeat_interval=5.0,
            heartbeat_timeout=10.0,
        )
        link.poll()
        first = self.channels[-1]
        first.incoming.append(bytes([XON]))
        link.poll()

        clock.advance(5.0)
        link.poll()
        self.assertEqual(first.written[-1], {"nonce": 0, "type": "a11y_ping"})

        clock.advance(10.0)
        link.poll()
        self.assertFalse(link.ready)
        self.assertTrue(first.closed)

        clock.advance(3.0)
        link.poll()
        self.assertEqual(len(self.channels), 2)
        self.assertIsNot(self.channels[-1], first)

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


def _objs(name="Save"):
    return [{"id": "1", "parent_id": None, "name": name, "role": "push button"}]


def _text(object_id="1", text="hello"):
    return dict(
        object_id=object_id,
        event="caret",
        text_supported=True,
        text=text,
        text_truncated=False,
        caret_offset=1,
        selection_start=None,
        selection_end=None,
    )


class A11yReplayAfterReconnectTests(unittest.TestCase):
    """Focus/bootstrap regressions: state must survive channel sessions."""

    def setUp(self):
        self.clock = FakeClock()
        self.channels = []
        self.ready_calls = 0
        self.resync = None
        self.link = NvdaA11yLink(
            self._open,
            clock=self.clock,
            retry_interval=3.0,
            heartbeat_interval=5.0,
            heartbeat_timeout=15.0,
            on_ready=self._on_ready,
        )

    def _open(self):
        ch = FakeChannel()
        self.channels.append(ch)
        return ch

    def _on_ready(self):
        self.ready_calls += 1
        if self.resync is not None:
            self.resync(self.link)

    def connect(self):
        self.link.poll()
        ch = self.channels[-1]
        ch.incoming.append(bytes([XON]))
        self.link.poll()
        return ch

    def kinds(self, ch):
        return [m["type"] for m in ch.written]

    def reconnect_via_heartbeat(self):
        old = self.channels[-1]
        self.clock.advance(5.0)
        self.link.poll()  # ping goes out, no pong
        self.clock.advance(15.0)
        self.link.poll()  # heartbeat timeout drops the channel
        self.assertFalse(self.link.ready)
        self.assertTrue(old.closed)
        self.clock.advance(3.0)
        return self.connect()

    def test_focus_before_channel_open_is_delivered_once_connected(self):
        self.assertFalse(self.link.send_focus(focus_id="1", objects=_objs()))
        self.assertEqual(self.channels, [])
        ch = self.connect()
        self.assertEqual(self.kinds(ch), ["protocol_version", "a11y_focus"])

    def test_current_focus_is_replayed_after_heartbeat_reconnect(self):
        first = self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        self.assertEqual(self.kinds(first), ["protocol_version", "a11y_focus"])

        second = self.reconnect_via_heartbeat()

        # No new AT-SPI event happened, yet the new session is populated.
        self.assertEqual(self.kinds(second), ["protocol_version", "a11y_focus"])
        self.assertEqual(second.written[1]["focus_id"], "1")
        self.assertEqual(second.written[1]["objects"], _objs())

    def test_heartbeat_reconnect_never_leaves_focus_empty(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        for _ in range(3):
            ch = self.reconnect_via_heartbeat()
            self.assertIn("a11y_focus", self.kinds(ch))

    def test_replay_after_xoff_xon_flap(self):
        ch = self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        ch.written.clear()
        ch.incoming.append(bytes([XOFF]))
        self.link.poll()
        ch.incoming.append(bytes([XON]))
        self.link.poll()
        self.assertEqual(self.kinds(ch), ["protocol_version", "a11y_focus"])

    def test_each_session_gets_exactly_one_focus_message(self):
        ch = self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        for _ in range(10):  # idle polling must not resend anything
            self.link.poll()
        self.assertEqual(self.kinds(ch).count("a11y_focus"), 1)

        second = self.reconnect_via_heartbeat()
        for _ in range(10):
            self.link.poll()
        self.assertEqual(self.kinds(second).count("a11y_focus"), 1)

    def test_resync_result_and_cached_focus_do_not_double_send(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        self.resync = lambda link: link.refresh_focus(focus_id="1", objects=_objs())
        second = self.reconnect_via_heartbeat()
        self.assertEqual(self.kinds(second).count("a11y_focus"), 1)

    def test_resync_before_first_focus_event_delivers_current_focus(self):
        # Bridge started after the desktop already had focus: no event exists.
        self.resync = lambda link: link.refresh_focus(focus_id="9", objects=_objs("Terminal"))
        ch = self.connect()
        self.assertEqual(self.kinds(ch), ["protocol_version", "a11y_focus"])
        self.assertEqual(ch.written[1]["focus_id"], "9")

    def test_stale_focus_is_replaced_by_fresh_snapshot_on_reconnect(self):
        self.connect()
        self.link.send_focus(focus_id="old", objects=_objs("Old"))
        self.resync = lambda link: link.refresh_focus(focus_id="new", objects=_objs("New"))
        second = self.reconnect_via_heartbeat()
        focus = [m for m in second.written if m["type"] == "a11y_focus"]
        self.assertEqual([m["focus_id"] for m in focus], ["new"])

    def test_stale_focus_is_not_replayed_when_nothing_is_focused(self):
        self.connect()
        self.link.send_focus(focus_id="old", objects=_objs("Old"))
        self.resync = lambda link: link.clear_focus()
        second = self.reconnect_via_heartbeat()
        self.assertEqual(self.kinds(second), ["protocol_version"])

    def test_failing_resync_falls_back_to_cached_focus(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())

        def boom(link):
            raise RuntimeError("AT-SPI went away")

        self.resync = boom
        second = self.reconnect_via_heartbeat()
        self.assertEqual(self.kinds(second), ["protocol_version", "a11y_focus"])
        self.assertTrue(self.link.ready)

    def test_text_for_focused_object_is_replayed_after_focus(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        self.link.send_text_update(**_text("1", "hello"))
        second = self.reconnect_via_heartbeat()
        self.assertEqual(
            self.kinds(second), ["protocol_version", "a11y_focus", "a11y_text"]
        )
        self.assertEqual(second.written[2]["text"], "hello")

    def test_text_for_other_object_is_not_replayed(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        self.link.send_text_update(**_text("2", "elsewhere"))
        second = self.reconnect_via_heartbeat()
        self.assertEqual(self.kinds(second), ["protocol_version", "a11y_focus"])

    def test_new_focus_discards_text_of_previous_focus(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        self.link.send_text_update(**_text("1", "hello"))
        self.link.send_focus(focus_id="2", objects=_objs("Next"))
        second = self.reconnect_via_heartbeat()
        self.assertEqual(self.kinds(second), ["protocol_version", "a11y_focus"])
        self.assertEqual(second.written[1]["focus_id"], "2")

    def test_fresh_snapshot_supersedes_cached_text(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        self.link.send_text_update(**_text("1", "stale"))
        self.resync = lambda link: link.refresh_focus(focus_id="1", objects=_objs())
        second = self.reconnect_via_heartbeat()
        self.assertEqual(self.kinds(second), ["protocol_version", "a11y_focus"])

    def test_live_focus_after_reconnect_is_sent_normally(self):
        self.connect()
        self.link.send_focus(focus_id="1", objects=_objs())
        second = self.reconnect_via_heartbeat()
        self.assertTrue(self.link.send_focus(focus_id="2", objects=_objs("Next")))
        self.assertEqual(second.written[-1]["focus_id"], "2")

    def test_without_on_ready_cached_focus_is_still_replayed(self):
        link = NvdaA11yLink(
            self._open,
            clock=self.clock,
            heartbeat_interval=5.0,
            heartbeat_timeout=15.0,
        )
        link.poll()
        self.channels[-1].incoming.append(bytes([XON]))
        link.poll()
        link.send_focus(focus_id="1", objects=_objs())
        self.clock.advance(5.0)
        link.poll()
        self.clock.advance(15.0)
        link.poll()
        self.clock.advance(3.0)
        link.poll()
        self.channels[-1].incoming.append(bytes([XON]))
        link.poll()
        self.assertEqual(
            [m["type"] for m in self.channels[-1].written],
            ["protocol_version", "a11y_focus"],
        )
