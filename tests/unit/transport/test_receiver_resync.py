import json
import unittest

from rdaccess_dvc import XON, Receiver


def line(**obj) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode() + b"\n"


class ReceiverResyncTests(unittest.TestCase):
    def test_tail_of_interrupted_line_does_not_swallow_next_messages(self):
        """A control byte inside a JSON line leaves a tail containing 'S'/'B'.

        Those must not be read as a legacy frame header whose 16-bit length
        makes the receiver wait for tens of KiB and swallow what follows.
        """
        rx = Receiver()
        rx.feed(b'{"type":"ind' + bytes([XON]) + b'ex Speech Bold"}\n')
        rx.feed(line(type="index", index=1))
        self.assertEqual(rx.legacy_frames, 0)
        self.assertEqual(rx.drain(), [{"type": "index", "index": 1}])

    def test_real_legacy_frames_of_every_known_command_still_parse(self):
        for driver in (b"S", b"B"):
            for command in b"@SCPxBWDG":
                rx = Receiver()
                payload = b"\x80\x04pickle"
                frame = driver + bytes([command]) + len(payload).to_bytes(2, "little") + payload
                rx.feed(frame + line(type="ping"))
                self.assertEqual(rx.legacy_frames, 1, (driver, command))
                self.assertEqual(rx.drain(), [{"type": "ping"}], (driver, command))

    def test_unknown_command_after_driver_byte_is_junk_one_byte_at_a_time(self):
        rx = Receiver()
        rx.feed(b"S" + b"?" + b"\xff\xff" + line(type="ping"))
        self.assertEqual(rx.legacy_frames, 0)
        self.assertEqual(rx.drain(), [{"type": "ping"}])


if __name__ == "__main__":
    unittest.main()
