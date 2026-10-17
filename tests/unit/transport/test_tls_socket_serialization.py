"""Post-connect SSL operations share one socket without overlapping I/O.

These unit tests exercise the patched legacy transport without creating or
touching any desktop, live relay, or user accessibility session.
"""
import json
import ssl
import sys
import threading
import types
import unittest
from unittest import mock

from linux_rdaccess_core.connection import remote_access
from tests.unit.transport.test_transport_stream_boundaries import (
    UPSTREAM, Callbacks,
)


def patched_transport():
    source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
    callback_module = types.ModuleType("callback_manager")
    callback_module.CallbackManager = Callbacks
    namespace = {}
    with mock.patch.dict(sys.modules, callback_manager=callback_module):
        exec(compile(source, "isolated-patched-tls-transport", "exec"),
             namespace)
    return namespace


class FakeTLS:
    """A nonblocking plaintext-read simulation with an SSL I/O gate."""
    def __init__(self):
        self.timeout = None
        self.nonblocking = False
        self.events = []
        self.receiver_entered = threading.Event()
        self.release_receiver = threading.Event()
        self.pause_recv = False

    def gettimeout(self):
        return self.timeout

    def setblocking(self, flag):
        self.nonblocking = not flag
        self.events.append(("blocking", flag))

    def settimeout(self, value):
        self.timeout = value
        self.nonblocking = value == 0
        self.events.append(("timeout", value))

    def recv(self, size):
        assert self.nonblocking, "TLS receive must be nonblocking under lock"
        self.events.append(("recv", size))
        if self.pause_recv:
            self.receiver_entered.set()
            if not self.release_receiver.wait(2):
                raise AssertionError("test never released TLS receiver")
        raise ssl.SSLWantReadError(ssl.SSL_ERROR_WANT_READ,
                                   "only TLS ticket was available")

    def sendall(self, payload):
        assert not self.nonblocking, "TLS send did not restore timeout"
        self.events.append(("sendall", payload))

    def pending(self):
        return 0

    def fileno(self):
        return 1

    def shutdown(self, how):
        self.events.append(("shutdown", how))

    def close(self):
        self.events.append(("close",))


class SerialTLSSocketTests(unittest.TestCase):
    def test_receive_want_read_restores_original_blocking_mode(self):
        namespace = patched_transport()
        inner = FakeTLS()
        wrapper = namespace["_linux_rdaccess_serial_ssl_socket"](inner)
        with self.assertRaises(ssl.SSLWantReadError):
            wrapper.recv(64)
        self.assertEqual(inner.timeout, None)
        self.assertFalse(inner.nonblocking)
        self.assertEqual(inner.events[:3],
                         [("blocking", False), ("recv", 64),
                          ("timeout", None)])
        wrapper.sendall(b'{"type":"speak"}\n')
        self.assertEqual(inner.events[-1],
                         ("sendall", b'{"type":"speak"}\n'))

    def test_send_cannot_overlap_read_of_same_tls_socket(self):
        namespace = patched_transport()
        inner = FakeTLS()
        inner.pause_recv = True
        wrapped = namespace["_linux_rdaccess_serial_ssl_socket"](inner)
        receive_errors = []
        sent = threading.Event()

        def read():
            try:
                wrapped.recv(64)
            except ssl.SSLWantReadError:
                pass
            except BaseException as error:
                receive_errors.append(error)

        receiver = threading.Thread(target=read)
        sender = threading.Thread(target=lambda: (
            wrapped.sendall(b"subsequent-message"), sent.set()))
        receiver.start()
        self.assertTrue(inner.receiver_entered.wait(2))
        sender.start()
        try:
            self.assertFalse(sent.wait(0.05),
                             "SSL_write overlapped an in-progress SSL_read")
        finally:
            inner.release_receiver.set()
            receiver.join(2)
            sender.join(2)
        self.assertFalse(receiver.is_alive())
        self.assertFalse(sender.is_alive())
        self.assertEqual(receive_errors, [])
        self.assertTrue(sent.is_set())
        self.assertEqual(inner.events[-1],
                         ("sendall", b"subsequent-message"))

    def test_decrypted_pending_frames_are_drained_before_next_select(self):
        """Buffered plaintext must not be stranded behind an idle TCP fd."""
        namespace = patched_transport()
        serializer = types.SimpleNamespace(
            deserialize=lambda frame: json.loads(frame),
        )
        transport = namespace["TCPTransport"](
            serializer, ("127.0.0.1", 6837))
        inner = FakeTLS()
        frames = [b'{"type":"first"}\n', b'{"type":"second"}\n']
        kinds = []

        def recv_frame(_size):
            assert inner.nonblocking
            return frames.pop(0)

        inner.recv = recv_frame
        inner.pending = lambda: len(frames)
        transport.callback_manager.register_callback(
            "msg_first", lambda **event: kinds.append("first"))
        transport.callback_manager.register_callback(
            "msg_second", lambda **event: kinds.append("second"))
        transport.server_sock = namespace[
            "_linux_rdaccess_serial_ssl_socket"](inner)
        transport.connected = True
        transport.handle_server_data()
        self.assertEqual(kinds, ["first", "second"])
        self.assertTrue(transport.connected)
        self.assertEqual(frames, [])
        self.assertEqual(inner.timeout, None)
        transport._disconnect()

    def test_tls_post_handshake_want_read_keeps_transport_connected(self):
        namespace = patched_transport()
        serializer = types.SimpleNamespace(
            deserialize=lambda frame: json.loads(frame),
        )
        transport = namespace["TCPTransport"](
            serializer, ("127.0.0.1", 6837))
        inner = FakeTLS()
        transport.server_sock = namespace[
            "_linux_rdaccess_serial_ssl_socket"](inner)
        transport.connected = True
        transport.handle_server_data()
        self.assertTrue(transport.connected)
        self.assertIsNotNone(transport.server_sock)
        self.assertEqual(transport.buffer, b"")
        self.assertFalse(inner.nonblocking)
        self.assertEqual(inner.timeout, None)
        # Cleanup is intentionally local; no relay connection exists.
        transport._disconnect()


if __name__ == "__main__":
    unittest.main()
