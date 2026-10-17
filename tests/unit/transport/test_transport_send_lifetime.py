"""Outgoing packets must belong to the session which requested the send."""

import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from linux_rdaccess_core.connection import remote_access
from tests.unit.transport.test_transport_stream_boundaries import (
    UPSTREAM, Callbacks, StreamSocket, transport_from_source,
)


class TransportSendLifetimeTests(unittest.TestCase):
    def transport(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, _ = transport_from_source(source, [])
        transport.server_sock = sock
        transport.connected = True
        transport.serializer.serialize = lambda **kw: json.dumps(kw).encode() + b"\n"
        self.addCleanup(transport.close)
        return transport

    def test_serialization_across_reconnect_cannot_send_old_output_to_new_peer(self):
        for kind in ("speak", "display", "lrd_a11y_focus", "cancel"):
            with self.subTest(kind=kind):
                transport = self.transport()
                entered, release = threading.Event(), threading.Event()
                errors = []

                def serialize(**kwargs):
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("serialization was never released")
                    return json.dumps(kwargs).encode() + b"\n"

                def send():
                    try:
                        transport.send(type=kind, payload="old-session")
                    except BaseException as error:
                        errors.append(error)

                transport.serializer.serialize = serialize
                worker = threading.Thread(target=send)
                worker.start()
                try:
                    self.assertTrue(entered.wait(2))
                    transport.close()
                    transport.server_sock = StreamSocket([])
                    transport.connected = True
                finally:
                    release.set()
                    worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertTrue(transport.queue.empty(), "old output leaked into the new session")
                transport.send(type=kind, payload="new-session")
                self.assertEqual(json.loads(transport.queue.get_nowait())["payload"], "new-session")

    def test_disconnect_cannot_clear_queue_before_an_accepted_enqueue_finishes(self):
        transport = self.transport()
        entered, release = threading.Event(), threading.Event()
        attempted, closed = threading.Event(), threading.Event()
        errors = []

        class PausedQueue(queue.Queue):
            def put(self, item, *args, **kwargs):
                if item is not None:
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("enqueue was never released")
                return super().put(item, *args, **kwargs)

        transport.queue = PausedQueue()

        def send():
            try:
                transport.send(type="speak", sequence=["old-session"])
            except BaseException as error:
                errors.append(error)

        def disconnect():
            attempted.set()
            try:
                transport._disconnect()
            except BaseException as error:
                errors.append(error)
            finally:
                closed.set()

        sender, closer = threading.Thread(target=send), threading.Thread(target=disconnect)
        sender.start()
        try:
            self.assertTrue(entered.wait(2))
            closer.start()
            self.assertTrue(attempted.wait(2))
            cleared_before_enqueue = closed.wait(0.05)
        finally:
            release.set()
            sender.join(2)
            if closer.ident is not None:
                closer.join(2)
        self.assertFalse(sender.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(cleared_before_enqueue)
        self.assertFalse(transport.connected)
        self.assertTrue(transport.queue.empty())

    def test_send_does_not_wait_for_the_connection_callback_lock(self):
        transport = self.transport()
        delivered = threading.Event()
        with transport._linux_rdaccess_connection_lock:
            worker = threading.Thread(target=lambda: (
                transport.send(type="cancel"), delivered.set()))
            worker.start()
            completed = delivered.wait(2)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(completed, "send would deadlock a controller input callback")

    def test_disconnected_send_does_not_serialize_or_enqueue(self):
        transport = self.transport()
        transport._disconnect()
        transport.serializer.serialize = lambda **kw: self.fail("disconnected output was serialized")
        transport.send(type="speak", sequence=["obsolete"])
        self.assertTrue(transport.queue.empty())

    def test_tls_relay_handshake_flushes_before_receiver_thread_starts(self):
        """Handshake packets must not race the first TLS 1.3 server read."""
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        callback_module = types.ModuleType("callback_manager")
        callback_module.CallbackManager = Callbacks
        namespace = {}
        with mock.patch.dict(sys.modules, callback_manager=callback_module):
            exec(compile(source, "patched-transport", "exec"), namespace)
        serializer = types.SimpleNamespace(
            serialize=lambda **kwargs: (
                json.dumps(kwargs).encode("utf-8") + b"\n"),
            deserialize=lambda frame: json.loads(frame),
        )
        relay = namespace["RelayTransport"](
            serializer, ("127.0.0.1", 6837),
            channel="test-session", connection_type="slave",
        )
        sock = StreamSocket([])
        sent = []
        sock.sendall = lambda payload: sent.append(json.loads(payload))
        relay.server_sock = sock
        relay.transport_connected()
        self.assertEqual(
            [message["type"] for message in sent],
            ["protocol_version", "join"],
        )
        self.assertEqual(sent[1]["channel"], "test-session")
        self.assertTrue(relay.queue.empty())
        self.assertIsNone(relay.queue_thread)
        relay.close()

    def test_failed_synchronous_join_cleans_socket_without_starting_sender(self):
        """A failed pre-read write must invalidate the connection safely."""
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        callback_module = types.ModuleType("callback_manager")
        callback_module.CallbackManager = Callbacks
        namespace = {}
        with mock.patch.dict(sys.modules, callback_manager=callback_module):
            exec(compile(source, "patched-transport", "exec"), namespace)
        serializer = types.SimpleNamespace(
            serialize=lambda **kwargs: json.dumps(kwargs).encode() + b"\n",
            deserialize=lambda frame: json.loads(frame),
        )
        relay = namespace["RelayTransport"](
            serializer, ("127.0.0.1", 6837),
            channel="test-session", connection_type="slave",
        )
        sock = StreamSocket([])
        sock.sendall = mock.Mock(side_effect=OSError("peer closed TLS"))
        relay.server_sock = sock
        relay.transport_connected()
        self.assertFalse(relay.connected)
        self.assertIsNone(relay.server_sock)
        self.assertIsNone(relay.queue_thread)
        self.assertTrue(sock.closed)

    def test_v1_and_v2_outbound_hooks_upgrade_without_duplicate_patch(self):
        """Already-installed output hooks must safely upgrade to v3."""
        current = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        for old_hook in (
                remote_access._TRANSPORT_OUTBOUND_HOOK_V1,
                remote_access._TRANSPORT_OUTBOUND_HOOK_V2):
            with self.subTest(previous=old_hook.splitlines()[0]):
                historical = current.replace(
                    remote_access._TRANSPORT_OUTBOUND_HOOK,
                    old_hook,
                )
                self.assertNotEqual(historical, current)
                self.assertFalse(
                    remote_access.legacy_transport_cleanup_patch_current(
                        historical))
                upgraded = remote_access._patch_legacy_transport_cleanup(
                    historical)
                self.assertEqual(upgraded, current)
                self.assertTrue(
                    remote_access.legacy_transport_cleanup_patch_current(
                        upgraded))
                self.assertEqual(
                    remote_access._patch_legacy_transport_cleanup(upgraded),
                    upgraded)

    def test_genuine_v7_upgrade_preserves_backup_and_is_idempotent(self):
        fixture = Path(__file__).resolve().parents[2] / "fixtures/legacy-patches/transport-v7.txt"
        historical = fixture.read_text()
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(historical))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transport.py"
            path.write_text(historical)
            backup = path.with_name(path.name + ".linux-rdaccess-backup")
            backup.write_text(UPSTREAM)
            self.assertTrue(remote_access._patch_legacy_transport_logging(path))
            updated = path.read_text()
            self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(updated))
            self.assertEqual(backup.read_text(), UPSTREAM)
            self.assertFalse(remote_access._patch_legacy_transport_logging(path))
            self.assertEqual(path.read_text(), updated)

    def test_output_lifetime_tampering_is_rejected(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        tampered = source.replace("and epoch == self._linux_rdaccess_outbound_epoch", "and True", 1)
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(tampered))
        with self.assertRaisesRegex(ValueError, "incomplete relay output lifetime"):
            remote_access._patch_legacy_transport_cleanup(tampered)

    def test_unknown_send_implementation_is_rejected(self):
        source = UPSTREAM.replace("self.queue.put(obj)", "self.custom_sender(obj)", 1)
        with self.assertRaisesRegex(ValueError, "unsupported legacy transport send layout"):
            remote_access._patch_legacy_transport_cleanup(source)


if __name__ == "__main__":
    unittest.main()
