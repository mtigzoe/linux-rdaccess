import json
import unittest

from rdaccess_dvc import XOFF, XON, NvdaSpeechLink


class FakeChannel:
    def __init__(self):
        self.incoming = []  # chunks returned by read()
        self.written = []  # decoded JSON messages
        self.read_error = None
        self.write_error = None
        self.closed = False

    def read(self, timeout_ms=0):
        if self.read_error:
            raise self.read_error
        return self.incoming.pop(0) if self.incoming else b""

    def write(self, data, timeout=5.0):
        if self.write_error:
            raise self.write_error
        for raw in data.split(b"\n"):
            if raw:
                self.written.append(json.loads(raw))

    def close(self):
        self.closed = True

    def types(self):
        return [m["type"] for m in self.written]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class SpeechLinkTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.channels = []
        self.ready_calls = 0
        self.open_failures = 0
        self.link = NvdaSpeechLink(
            self._open, on_ready=self._on_ready, retry_interval=3.0, clock=self.clock
        )

    def _open(self):
        if self.open_failures:
            self.open_failures -= 1
            raise RuntimeError("Could not open DVC")
        ch = FakeChannel()
        self.channels.append(ch)
        return ch

    def _on_ready(self):
        self.ready_calls += 1

    def connect(self):
        self.link.poll()  # opens
        ch = self.channels[-1]
        ch.incoming.append(bytes([XON]))
        self.link.poll()
        return ch

    def test_speech_is_dropped_until_xon(self):
        self.link.poll()
        ch = self.channels[-1]
        self.assertFalse(self.link.speak("too early"))
        self.assertEqual(ch.written, [])

    def test_xon_triggers_v2_handshake_and_ready_callback(self):
        ch = self.connect()
        self.assertEqual(ch.written[0]["type"], "protocol_version")
        self.assertEqual(ch.written[0]["version"], 2)
        self.assertEqual(ch.written[0]["channel"], "NVDA-SPEECH")
        self.assertEqual(self.ready_calls, 1)
        self.assertTrue(self.link.ready)

    def test_speak_with_interrupt_sends_cancel_then_speak(self):
        ch = self.connect()
        ch.written.clear()
        self.assertTrue(self.link.speak("hello", interrupt=True))
        self.assertEqual(ch.types(), ["cancel", "speak"])
        self.assertEqual(ch.written[1]["sequence"], ["hello"])

    def test_speak_without_interrupt_sends_only_speak(self):
        ch = self.connect()
        ch.written.clear()
        self.link.speak("hello")
        self.assertEqual(ch.types(), ["speak"])

    def test_xoff_stops_speech(self):
        """Regression: the old bridge wrote regardless of XOFF."""
        ch = self.connect()
        ch.incoming.append(bytes([XOFF]))
        self.link.poll()
        ch.written.clear()
        self.assertFalse(self.link.ready)
        self.assertFalse(self.link.speak("nobody is listening"))
        self.assertEqual(ch.written, [])

    def test_client_reconnect_rehandshakes(self):
        """Regression: a reconnecting client restarts in legacy mode and needs v2 again."""
        ch = self.connect()
        ch.incoming.append(bytes([XOFF]))
        self.link.poll()
        ch.incoming.append(bytes([XON]))
        self.link.poll()
        self.assertEqual(ch.types().count("protocol_version"), 2)
        self.assertEqual(self.ready_calls, 2)

    def test_poll_keeps_draining_so_the_client_never_backs_up(self):
        """Regression: nothing read the DVC after startup; index replies piled up."""
        ch = self.connect()
        for n in range(200):
            ch.incoming.append(json.dumps({"type": "index", "index": n}).encode() + b"\n")
        for _ in range(20):
            self.link.poll()
        self.assertEqual(ch.incoming, [])
        self.assertEqual(self.link._rx.messages, [])  # drained, not accumulated

    def test_split_reads_and_legacy_frames_do_not_break_polling(self):
        ch = self.connect()
        ch.incoming += [b"SS\x03", b"\x00abc", b'{"type":"ind', b'ex","index":0}\n']
        for _ in range(4):
            self.link.poll()
        self.assertEqual(self.link._rx.legacy_frames, 1)

    def test_read_error_drops_channel_and_reopens_after_interval(self):
        ch = self.connect()
        ch.read_error = ConnectionError("channel closed by chansrv")
        self.link.poll()
        self.assertTrue(ch.closed)
        self.assertFalse(self.link.ready)
        self.link.poll()  # too soon
        self.assertEqual(len(self.channels), 1)
        self.clock.now += 3.1
        self.link.poll()
        self.assertEqual(len(self.channels), 2)
        self.assertFalse(self.link.ready)  # fresh channel needs its own XON

    def test_write_error_drops_channel(self):
        ch = self.connect()
        ch.write_error = TimeoutError("write timed out")
        self.assertFalse(self.link.speak("hello"))
        self.assertTrue(ch.closed)
        self.assertFalse(self.link.ready)

    def test_open_failure_is_retried_with_delay_and_does_not_raise(self):
        self.open_failures = 2
        self.link.poll()
        self.assertEqual(self.channels, [])
        self.link.poll()  # still inside the retry interval
        self.assertEqual(self.open_failures, 1)
        self.clock.now += 3.1
        self.link.poll()
        self.assertEqual(self.open_failures, 0)
        self.clock.now += 3.1
        self.link.poll()
        self.assertEqual(len(self.channels), 1)

    def test_close_is_idempotent(self):
        ch = self.connect()
        self.link.close()
        self.link.close()
        self.assertTrue(ch.closed)


if __name__ == "__main__":
    unittest.main()
