"""Regression tests for legacy Orca Remote transport resource cleanup."""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import linux_rdaccess
import remote_access


SOURCE = '''\
class TCPTransport:
    def __init__(self, socket_factory, callback_manager, queue):
        self.socket_factory = socket_factory
        self.callback_manager = callback_manager
        self.queue = queue
        self.address = ("relay.example", 6837)
        self.server_sock = None
        self.queue_thread = None
        self.connected = False

    def create_outbound_socket(self, address):
        return self.socket_factory()

    def run(self):
        try:
            self.server_sock = self.create_outbound_socket(self.address)
            self.server_sock.connect(self.address)
        except Exception:
            self.callback_manager.call_callbacks('transport_connection_failed')
            raise

    def _disconnect(self):
        """Disconnect the transport due to an error, without closing the connector thread."""
        if not self.connected:
            return
        if self.queue_thread is not None:
            self.queue.put(None)
            self.queue_thread.join()
        clear_queue(self.queue)
        self.server_sock.close()
        self.server_sock = None
'''


class FakeSocket:
    def __init__(self, fail_connect=False):
        self.fail_connect = fail_connect
        self.closed = False

    def connect(self, address):
        if self.fail_connect:
            raise OSError("synthetic connect failure")

    def close(self):
        self.closed = True


class FakeCallbacks:
    def __init__(self):
        self.calls = []

    def call_callbacks(self, event):
        self.calls.append(event)


class FakeQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class FakeThread:
    def __init__(self):
        self.joined = False

    def join(self):
        self.joined = True


class TransportCleanupTests(unittest.TestCase):
    @staticmethod
    def patched_class():
        source = remote_access._patch_legacy_transport_cleanup(SOURCE)
        namespace = {"clear_queue": lambda queue: queue.items.clear()}
        exec(source, namespace)
        return source, namespace["TCPTransport"]

    def test_failed_initial_connect_closes_provisional_socket(self):
        source, transport_cls = self.patched_class()
        self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(source))
        sock = FakeSocket(fail_connect=True)
        callbacks = FakeCallbacks()
        transport = transport_cls(lambda: sock, callbacks, FakeQueue())
        with self.assertRaises(OSError):
            transport.run()
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(callbacks.calls, ["transport_connection_failed"])

    def test_disconnect_cleans_resources_even_after_connected_flag_cleared(self):
        _source, transport_cls = self.patched_class()
        sock = FakeSocket()
        queue = FakeQueue()
        queue.items.append(b"stale")
        transport = transport_cls(lambda: sock, FakeCallbacks(), queue)
        worker = FakeThread()
        transport.server_sock = sock
        transport.queue_thread = worker
        transport.connected = False  # upstream run() does this before _disconnect()
        transport._disconnect()
        self.assertTrue(sock.closed)
        self.assertTrue(worker.joined)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(queue.items, [])

    def test_cleanup_patch_is_idempotent_and_rejects_tampering(self):
        source = remote_access._patch_legacy_transport_cleanup(SOURCE)
        self.assertEqual(remote_access._patch_legacy_transport_cleanup(source), source)
        tampered = source.replace(
            "if self.server_sock is None and self.queue_thread is None:",
            "if not self.connected:",
        )
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(tampered))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            remote_access._patch_legacy_transport_cleanup(tampered)

    def test_doctor_reports_transport_cleanup(self):
        source = remote_access._patch_legacy_transport_cleanup(SOURCE)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "orca-customizations.py"
            config.write_text("", encoding="utf-8")
            transport = root / remote_access.LEGACY_TRANSPORT_RELATIVE
            transport.parent.mkdir(parents=True)
            transport.write_text(source, encoding="utf-8")
            rows = dict(linux_rdaccess.patch_status(config))
            self.assertEqual(rows["relay transport cleanup (transport.py)"], "current")
            transport.write_text(SOURCE, encoding="utf-8")
            rows = dict(linux_rdaccess.patch_status(config))
            self.assertIn(
                "not patched",
                rows["relay transport cleanup (transport.py)"],
            )


if __name__ == "__main__":
    unittest.main()
