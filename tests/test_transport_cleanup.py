"""Regression tests for legacy Orca Remote transport resource cleanup."""
from __future__ import annotations

import socket
import tempfile
from pathlib import Path
import types
import unittest

import linux_rdaccess
import remote_access


SOURCE = '''\
import socket

class TCPTransport:
    def __init__(self, socket_factory, callback_manager, queue, handler=None):
        self.socket_factory = socket_factory
        self.callback_manager = callback_manager
        self.queue = queue
        self.address = ("relay.example", 6837)
        self.server_sock = None
        self.queue_thread = None
        self.connected = False
        self.buffer = b""
        self.handler = handler or (lambda: None)

    def create_outbound_socket(self, address):
        return self.socket_factory()

    def handle_server_data(self):
        self.handler()

    def run(self):
        try:
            self.server_sock = self.create_outbound_socket(self.address)
            self.server_sock.connect(self.address)
        except Exception:
            self.callback_manager.call_callbacks('transport_connection_failed')
            raise
        self.connected = True
        while self.server_sock is not None:
            try:
                readers, writers, error = select.select(
                    [self.server_sock], [], [self.server_sock])
            except socket.error:
                self.buffer = b''
                break
            if self.server_sock in error:
                self.buffer = b""
                break
            if self.server_sock in readers:
                try:
                    self.handle_server_data()
                except socket.error:
                    self.buffer = b''
                    break
        self.connected = False
        self.callback_manager.call_callbacks('transport_disconnected')
        self._disconnect()

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
    def __init__(self, fail_connect=False, events=None, shutdown_raises=False):
        self.fail_connect = fail_connect
        self.closed = False
        self.events = events if events is not None else []
        self.shutdown_raises = shutdown_raises

    def connect(self, address):
        if self.fail_connect:
            raise OSError("synthetic connect failure")

    def shutdown(self, how):
        self.events.append("shutdown")
        if self.shutdown_raises:
            raise OSError("not connected")

    def close(self):
        self.events.append("close")
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
    def __init__(self, events=None):
        self.joined = False
        self.events = events if events is not None else []

    def join(self):
        self.events.append("join")
        self.joined = True


class TransportCleanupTests(unittest.TestCase):
    @staticmethod
    def patched_class(selector=None):
        source = remote_access._patch_legacy_transport_cleanup(SOURCE)
        if selector is None:
            selector = lambda readers, writers, errors: ([], [], [])
        namespace = {
            "clear_queue": lambda queue: queue.items.clear(),
            "select": types.SimpleNamespace(select=selector),
        }
        exec(source, namespace)
        return source, namespace["TCPTransport"]

    def test_failed_initial_connect_closes_provisional_socket(self):
        source, transport_cls = self.patched_class()
        self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(source))
        sock = FakeSocket(fail_connect=True, shutdown_raises=True)
        callbacks = FakeCallbacks()
        transport = transport_cls(lambda: sock, callbacks, FakeQueue())
        with self.assertRaises(OSError):
            transport.run()
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(callbacks.calls, ["transport_connection_failed"])

    def test_disconnect_cleans_resources_even_after_connected_flag_cleared(self):
        _source, transport_cls = self.patched_class()
        events = []
        sock = FakeSocket(events=events)
        queue = FakeQueue()
        queue.items.append(b"stale")
        transport = transport_cls(lambda: sock, FakeCallbacks(), queue)
        worker = FakeThread(events)
        transport.server_sock = sock
        transport.queue_thread = worker
        transport.connected = False  # upstream run() does this before _disconnect()
        transport._disconnect()
        self.assertTrue(sock.closed)
        self.assertTrue(worker.joined)
        self.assertLess(events.index("shutdown"), events.index("join"))
        self.assertLess(events.index("join"), events.index("close"))
        self.assertIsNone(transport.server_sock)
        self.assertEqual(queue.items, [])

    def test_malformed_frame_disconnects_cleanly_instead_of_escaping(self):
        selected = [True]

        def selector(readers, writers, errors):
            if selected.pop():
                return (readers, [], [])
            return ([], [], [])

        source, transport_cls = self.patched_class(selector)
        self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(source))
        sock = FakeSocket()
        callbacks = FakeCallbacks()
        transport = transport_cls(
            lambda: sock,
            callbacks,
            FakeQueue(),
            handler=lambda: (_ for _ in ()).throw(ValueError("malformed JSON")),
        )
        transport.run()
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(
            callbacks.calls,
            ["transport_disconnected"],
        )

    def test_v1_cleanup_patch_upgrades_to_v3(self):
        # Reconstruct the v1 transformation: resource-aware guard plus failed
        # connect cleanup, but no pre-join socket shutdown yet.
        source = SOURCE.replace(
            "if not self.connected:",
            "if self.server_sock is None and self.queue_thread is None:",
        ).replace(
            "        except Exception:\n"
            "            self.callback_manager.call_callbacks('transport_connection_failed')",
            "        except Exception:\n"
            "            self._disconnect()\n"
            "            self.callback_manager.call_callbacks('transport_connection_failed')",
        )
        source = source.rstrip("\n") + "\n\n" + remote_access.TRANSPORT_CLEANUP_MARKER_V1 + "\n"
        updated = remote_access._patch_legacy_transport_cleanup(source)
        self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(updated))
        self.assertIn(remote_access.TRANSPORT_CLEANUP_MARKER, updated)
        self.assertNotIn(remote_access.TRANSPORT_CLEANUP_MARKER_V1 + "\n", updated)
        disconnect = updated.split("def _disconnect", 1)[1]
        self.assertLess(
            disconnect.index("shutdown(socket.SHUT_RDWR)"),
            disconnect.index("self.queue_thread.join()"),
        )

    def test_v2_cleanup_patch_upgrades_to_v3(self):
        current = remote_access._patch_legacy_transport_cleanup(SOURCE)
        v2 = current.replace(
            "self.handle_server_data()\n                except Exception:",
            "self.handle_server_data()\n                except socket.error:",
            1,
        ).replace(
            remote_access.TRANSPORT_CLEANUP_MARKER,
            remote_access.TRANSPORT_CLEANUP_MARKER_V2,
            1,
        )
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(v2))
        updated = remote_access._patch_legacy_transport_cleanup(v2)
        self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(updated))
        self.assertNotIn(remote_access.TRANSPORT_CLEANUP_MARKER_V2 + "\n", updated)

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
            v1 = SOURCE.replace(
                "if not self.connected:",
                "if self.server_sock is None and self.queue_thread is None:",
            ).replace(
                "        except Exception:\n"
                "            self.callback_manager.call_callbacks('transport_connection_failed')",
                "        except Exception:\n"
                "            self._disconnect()\n"
                "            self.callback_manager.call_callbacks('transport_connection_failed')",
            )
            v1 = v1.rstrip("\n") + "\n\n" + remote_access.TRANSPORT_CLEANUP_MARKER_V1 + "\n"
            transport.write_text(v1, encoding="utf-8")
            rows = dict(linux_rdaccess.patch_status(config))
            self.assertIn(
                "outdated",
                rows["relay transport cleanup (transport.py)"],
            )
            transport.write_text(SOURCE, encoding="utf-8")
            rows = dict(linux_rdaccess.patch_status(config))
            self.assertIn(
                "not patched",
                rows["relay transport cleanup (transport.py)"],
            )


if __name__ == "__main__":
    unittest.main()
