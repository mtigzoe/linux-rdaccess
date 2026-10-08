import ctypes
import unittest

from rdaccess_dvc import DvcChannel


class FakeLib:
    """Mimics the parts of libxrdpapi that DvcChannel calls."""

    def __init__(self):
        self.open_results = [1]  # handle values; 0/None means failure
        self.writes = []
        self.write_script = []  # bytes accepted per call; [] -> accept everything
        self.read_chunks = []
        self.read_ok = True
        self.closed = []

    def WTSVirtualChannelOpenEx(self, session, name, flags):
        self.opened = (session, name, flags)
        return self.open_results.pop(0) if self.open_results else 0

    def WTSVirtualChannelWrite(self, h, data, length, written):
        accept = self.write_script.pop(0) if self.write_script else length
        self.writes.append(bytes(data[:accept]))
        written._obj.value = accept
        return 1

    def WTSVirtualChannelRead(self, h, timeout, buf, size, nread):
        if not self.read_ok:
            return 0
        chunk = self.read_chunks.pop(0) if self.read_chunks else b""
        ctypes.memmove(buf, chunk, len(chunk))
        nread._obj.value = len(chunk)
        return 1

    def WTSVirtualChannelClose(self, h):
        self.closed.append(h)
        return 1


class DvcChannelTests(unittest.TestCase):
    def test_opens_dynamic_channel_by_name(self):
        lib = FakeLib()
        DvcChannel(lib, "NVDA-SPEECH")
        session, name, flags = lib.opened
        self.assertEqual((session, name, flags), (0xFFFFFFFF, b"NVDA-SPEECH", 1))

    def test_open_retries_then_raises(self):
        lib = FakeLib()
        lib.open_results = [0, 0, 0]
        with self.assertRaises(RuntimeError):
            DvcChannel(lib, "NVDA-SPEECH", attempts=3, retry_delay=0)

    def test_open_succeeds_on_a_later_attempt(self):
        lib = FakeLib()
        lib.open_results = [0, 0, 7]
        DvcChannel(lib, "NVDA-SPEECH", attempts=3, retry_delay=0)

    def test_write_resumes_after_partial_acceptance(self):
        lib = FakeLib()
        ch = DvcChannel(lib, "x")
        lib.write_script = [0, 3]  # first call: would block; second: takes 3 bytes; then the rest
        ch.write(b"abcdefgh")
        self.assertEqual(b"".join(lib.writes), b"abcdefgh")

    def test_read_returns_bytes_and_empty_when_idle(self):
        lib = FakeLib()
        ch = DvcChannel(lib, "x")
        lib.read_chunks = [b"\x11"]
        self.assertEqual(ch.read(0), b"\x11")
        self.assertEqual(ch.read(0), b"")

    def test_read_failure_raises_connection_error(self):
        lib = FakeLib()
        ch = DvcChannel(lib, "x")
        lib.read_ok = False
        with self.assertRaises(ConnectionError):
            ch.read(0)

    def test_close_is_idempotent(self):
        lib = FakeLib()
        ch = DvcChannel(lib, "x")
        ch.close()
        ch.close()
        self.assertEqual(len(lib.closed), 1)


if __name__ == "__main__":
    unittest.main()
