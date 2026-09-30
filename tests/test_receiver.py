import json
import unittest

from rdaccess_dvc import MAX_PENDING_BYTES, XOFF, XON, Receiver


def line(**obj) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode() + b"\n"


class ReceiverTests(unittest.TestCase):
    def test_xon_xoff_toggle_state_and_count(self):
        rx = Receiver()
        rx.feed(bytes([XON]))
        self.assertTrue(rx.xon)
        rx.feed(bytes([XOFF]))
        self.assertFalse(rx.xon)
        rx.feed(bytes([XON]))
        self.assertEqual(rx.xon_count, 2)

    def test_xoff_then_xon_in_one_read_is_still_visible_via_count(self):
        rx = Receiver()
        rx.feed(bytes([XON]))
        before = rx.xon_count
        rx.feed(bytes([XOFF, XON]))  # a reconnecting client, seen in one read
        self.assertTrue(rx.xon)
        self.assertEqual(rx.xon_count, before + 1)

    def test_json_line_split_across_reads(self):
        rx = Receiver()
        data = line(type="index", index=0)
        for i in range(len(data)):
            rx.feed(data[i : i + 1])
        self.assertEqual(rx.drain(), [{"type": "index", "index": 0}])

    def test_legacy_frame_is_skipped_not_parsed(self):
        rx = Receiver()
        payload = b"\x80\x04 pretend pickle"  # must never be unpickled
        frame = b"S" + b"A" + len(payload).to_bytes(2, "little") + payload
        rx.feed(frame[:3])
        self.assertEqual(rx.legacy_frames, 0)
        rx.feed(frame[3:] + line(type="ping"))
        self.assertEqual(rx.legacy_frames, 1)
        self.assertEqual(rx.drain(), [{"type": "ping"}])

    def test_xon_between_messages(self):
        rx = Receiver()
        rx.feed(line(type="ping") + bytes([XON]) + line(type="index", index=3))
        self.assertTrue(rx.xon)
        self.assertEqual([m["type"] for m in rx.drain()], ["ping", "index"])

    def test_bad_json_is_counted_and_skipped(self):
        rx = Receiver()
        rx.feed(b"{not json}\n" + line(type="ping"))
        self.assertEqual(rx.drain(), [{"type": "ping"}])
        self.assertGreater(rx.junk_bytes, 0)

    def test_drain_clears_messages(self):
        """Regression: `messages` grew forever in a long-running process."""
        rx = Receiver()
        for n in range(1000):
            rx.feed(line(type="index", index=n))
            rx.drain()
        self.assertEqual(rx.messages, [])

    def test_unterminated_json_is_bounded(self):
        """Regression: a peer that never sends a newline must not grow the buffer forever."""
        rx = Receiver()
        rx.feed(b"{" + b"a" * (MAX_PENDING_BYTES + 10))
        self.assertEqual(len(rx.buf), 0)
        rx.feed(line(type="ping"))
        self.assertEqual(rx.drain(), [{"type": "ping"}])


if __name__ == "__main__":
    unittest.main()
