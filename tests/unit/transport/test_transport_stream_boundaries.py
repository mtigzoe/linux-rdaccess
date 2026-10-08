"""Exercise the complete pinned Orca Remote relay source, including its receiver.

Fixture: serrebidev/orca-remote d47a085945576d8e973f9c686587bdfc90ae061c,
orca-scripts/transport.py. Tests use fake sockets and native sender threads.
"""

import ast
import json
import re
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest import mock

import remote_access


UPSTREAM = (Path(__file__).resolve().parents[2] / "fixtures/legacy-patches/transport-upstream.txt").read_text()


class Callbacks:
    def __init__(self):
        self.calls = []
        self.callbacks = {}

    def call_callbacks(self, event, **kwargs):
        self.calls.append((event, kwargs))
        for callback in self.callbacks.get(event, ()):
            callback(**kwargs)

    def register_callback(self, event, callback):
        self.callbacks.setdefault(event, []).append(callback)


class StreamSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.closed = False
        self.shutdowns = 0

    def connect(self, address):
        pass

    def recv(self, count):
        return self.incoming.pop(0) if self.incoming else b""

    def sendall(self, data):
        pass

    def shutdown(self, mode):
        self.shutdowns += 1

    def close(self):
        self.closed = True


def transport_from_source(source, incoming):
    callback_module = types.ModuleType("callback_manager")
    callback_module.CallbackManager = Callbacks
    namespace = {}
    with mock.patch.dict(sys.modules, callback_manager=callback_module):
        exec(compile(source, "pinned-orca-remote-transport", "exec"), namespace)
    sock = StreamSocket(incoming)
    serializer = types.SimpleNamespace(deserialize=lambda data: json.loads(data))
    transport = namespace["TCPTransport"](serializer, ("relay.example", 6837))
    transport.create_outbound_socket = lambda address: sock
    reads = []

    def select(readers, writers, errors):
        reads.append(1)
        if len(reads) > len(incoming) + 2:
            raise AssertionError("receiver spun after EOF instead of disconnecting")
        return readers, [], []

    return transport, sock, select


class TransportStreamBoundariesTests(unittest.TestCase):
    def test_failed_connect_cleanup_cannot_close_replacement_after_handoff(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, obsolete, _selector = transport_from_source(source, [])
        replacement = StreamSocket([])
        entered, release = threading.Event(), threading.Event()
        close_attempted, close_done = threading.Event(), threading.Event()
        failures = []
        original_disconnect = transport._disconnect
        obsolete.connect = mock.Mock(side_effect=OSError("connect failed"))

        def disconnect():
            if threading.current_thread() is worker:
                entered.set()
                if not release.wait(2):
                    raise AssertionError("failed connection cleanup never released")
            original_disconnect()

        def run():
            try:
                transport.run()
            except BaseException as error:
                failures.append(error)

        def close_and_replace():
            close_attempted.set()
            transport.close()
            # Model a replacement connection after the old session closes.
            with transport._linux_rdaccess_connection_lock:
                transport.server_sock = replacement
                transport.connected = True
                transport.buffer = b'{"type":"new-partial'
            close_done.set()

        transport._disconnect = disconnect
        worker = threading.Thread(target=run)
        closer = threading.Thread(target=close_and_replace)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            closer.start()
            self.assertTrue(close_attempted.wait(2))
            closed_before_cleanup = close_done.wait(0.05)
        finally:
            release.set()
            worker.join(2)
            if closer.ident is not None:
                closer.join(2)
            self.addCleanup(transport.close)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual([type(error) for error in failures], [OSError])
        self.assertFalse(closed_before_cleanup)
        self.assertTrue(obsolete.closed)
        self.assertFalse(replacement.closed)
        self.assertIs(transport.server_sock, replacement)
        self.assertTrue(transport.connected)
        self.assertEqual(transport.buffer, b'{"type":"new-partial')
        events = [event for event, _ in transport.callback_manager.calls]
        self.assertLess(events.index("transport_connection_failed"), events.index("transport_closing"))

    def test_close_serializes_connected_transition_and_sender_creation(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, _selector = transport_from_source(source, [])
        entered, release = threading.Event(), threading.Event()
        close_attempted, close_done = threading.Event(), threading.Event()
        failures = []
        original_connected = transport.transport_connected

        def connected():
            entered.set()
            if not release.wait(2):
                raise AssertionError("connected transition never released")
            original_connected()

        def run():
            try:
                transport.run()
            except BaseException as error:
                failures.append(error)

        def close():
            close_attempted.set()
            try:
                transport.close()
            except BaseException as error:
                failures.append(error)
            finally:
                close_done.set()

        def selector(readers, writers, errors):
            if not close_done.wait(2):
                raise AssertionError("transport close never completed")
            return readers, [], []

        transport.transport_connected = connected
        worker, closer = threading.Thread(target=run), threading.Thread(target=close)
        with mock.patch("select.select", side_effect=selector):
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                closer.start()
                self.assertTrue(close_attempted.wait(2))
                closed_before_transition = close_done.wait(0.05)
            finally:
                release.set()
                worker.join(2)
                if closer.ident is not None:
                    closer.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(failures, [])
        self.assertFalse(closed_before_transition)
        self.assertTrue(transport.closed)
        self.assertFalse(transport.connected)
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertTrue(transport.queue_thread is None or not transport.queue_thread.is_alive())
        events = [event for event, _ in transport.callback_manager.calls]
        self.assertLess(events.index("transport_connected"), events.index("transport_closing"))

    def test_close_during_socket_creation_never_connects_obsolete_attempt(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, _selector = transport_from_source(source, [])
        entered, release = threading.Event(), threading.Event()
        failures = []
        sock.connect = mock.Mock()

        def factory(address):
            entered.set()
            if not release.wait(2):
                raise AssertionError("socket creation never released")
            return sock

        def run():
            try:
                transport.run()
            except BaseException as error:
                failures.append(error)

        transport.create_outbound_socket = factory
        worker = threading.Thread(target=run)
        with mock.patch("select.select", side_effect=lambda r, w, e: (r, [], [])):
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                transport.close()
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        sock.connect.assert_not_called()
        self.assertTrue(sock.closed)
        self.assertFalse(transport.connected)
        self.assertTrue(transport.closed)
        self.assertIsNone(transport.server_sock)
        self.assertIsNone(transport.queue_thread)
        self.assertEqual(transport.callback_manager.calls, [("transport_closing", {})])

    def test_canceled_socket_creation_cannot_overwrite_replacement_connection(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, obsolete, _selector = transport_from_source(source, [])
        replacement = StreamSocket([])
        obsolete.connect = mock.Mock()

        def factory(address):
            transport.close()
            # Model a new connection published while the old DNS/TLS call returns.
            transport.server_sock = replacement
            transport.connected = True
            transport.buffer = b'{"type":"new-partial'
            return obsolete

        transport.create_outbound_socket = factory
        with mock.patch("select.select", side_effect=lambda r, w, e: (r, [], [])):
            transport.run()
        obsolete.connect.assert_not_called()
        self.assertTrue(obsolete.closed)
        self.assertFalse(replacement.closed)
        self.assertIs(transport.server_sock, replacement)
        self.assertTrue(transport.connected)
        self.assertEqual(transport.buffer, b'{"type":"new-partial')
        transport.close()

    def test_failure_of_canceled_socket_creation_does_not_report_connection_failure(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, _sock, _selector = transport_from_source(source, [])

        def factory(address):
            transport.close()
            raise OSError("obsolete TLS connection failed")

        transport.create_outbound_socket = factory
        transport.run()
        self.assertEqual(transport.callback_manager.calls, [("transport_closing", {})])
        self.assertFalse(transport.connected)
        self.assertTrue(transport.closed)

    def test_obsolete_native_connector_cannot_begin_another_attempt(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, _sock, _selector = transport_from_source(source, [])
        obsolete = transport.reconnector_thread
        transport.close()
        transport.create_outbound_socket = mock.Mock(return_value=_sock)
        with mock.patch("threading.current_thread", return_value=obsolete), mock.patch(
                "select.select", side_effect=lambda r, w, e: (r, [], [])):
            transport.run()
        transport.create_outbound_socket.assert_not_called()
        self.assertTrue(transport.closed)

    def test_genuine_v7_gains_pending_connection_ownership_without_changing_backup(self):
        import tempfile
        historical = remote_access._strip_transport_pending_connect(
            remote_access._patch_legacy_transport_cleanup(UPSTREAM))
        self.assertTrue(remote_access._legacy_transport_cleanup_v7_current(historical))
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

    def test_pending_connection_ownership_tampering_is_rejected(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        tampered = source.replace(
            "if connect_epoch != self._linux_rdaccess_connection_epoch:",
            "if False:", 1)
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(tampered))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            remote_access._patch_legacy_transport_cleanup(tampered)

    def test_native_reconnect_cannot_make_old_run_select_new_session(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        callback_module = types.ModuleType("callback_manager")
        callback_module.CallbackManager = Callbacks
        namespace = {}
        with mock.patch.dict(sys.modules, callback_manager=callback_module):
            exec(compile(source, "pinned-orca-remote-transport", "exec"), namespace)
        old = StreamSocket([b'{"type":"reconnect"}\n'])
        replacement = StreamSocket([b""])
        sockets = iter((old, replacement))
        serializer = types.SimpleNamespace(
            deserialize=lambda data: json.loads(data),
            serialize=lambda **kwargs: json.dumps(kwargs).encode() + b"\n")
        transport = namespace["RelayTransport"](serializer, ("relay.example", 6837), channel="session")
        transport.create_outbound_socket = lambda address: next(sockets)
        entered, release = threading.Event(), threading.Event()
        owner = threading.current_thread()
        workers = []

        def selector(readers, writers, errors):
            if threading.current_thread() is owner:
                if readers[0] is replacement:
                    raise AssertionError("obsolete run selected replacement session")
                return readers, [], []
            entered.set()
            release.wait(2)
            return readers, [], []

        def reconnect():
            transport.reconnect(("relay.example", 6837), "session")
            workers.append(transport.reconnector_thread)
            self.assertTrue(entered.wait(2))
            transport.reconnector_thread.running = False

        transport.callback_manager.register_callback("msg_reconnect", reconnect)
        namespace["select"] = types.SimpleNamespace(select=selector)
        namespace["time"] = types.SimpleNamespace(sleep=lambda _: None)
        try:
            transport.run()
            self.assertIs(transport.server_sock, replacement)
            self.assertFalse(replacement.closed)
            self.assertTrue(transport.connected)
        finally:
            transport.close()
            release.set()
            for worker in workers:
                worker.join(2)
                self.assertFalse(worker.is_alive())

    def test_close_marks_transport_disconnected_before_future_sends(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, _selector = transport_from_source(source, [])
        transport.serializer.serialize = lambda **kwargs: json.dumps(kwargs).encode() + b"\n"
        transport.server_sock = sock
        transport.connected = True
        transport.close()
        self.assertFalse(transport.connected)
        transport.send(type="speak", sequence=["after close"])
        self.assertTrue(transport.queue.empty())

    def test_callback_close_cannot_deliver_remaining_frames_from_closed_session(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, selector = transport_from_source(source, [
            b'{"type":"first"}\n{"type":"stale"}\n{"type":"unfinished'
        ])
        record = transport.callback_manager.call_callbacks

        def callback(event, **kwargs):
            record(event, **kwargs)
            if event == "msg_first":
                transport.close()

        transport.callback_manager.call_callbacks = callback
        with mock.patch("select.select", selector):
            transport.run()
        self.assertTrue(sock.closed)
        self.assertFalse(transport.connected)
        self.assertEqual([event for event, _ in transport.callback_manager.calls],
                         ["transport_connected", "msg_first", "transport_closing", "transport_disconnected"])
        self.assertEqual(transport.buffer, b"")

    def test_callback_replacement_keeps_new_partial_frame_and_discards_old_batch(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, old, _selector = transport_from_source(source, [
            b'{"type":"first"}\n{"type":"stale"}\n{"type":"old-partial'
        ])
        replacement = StreamSocket([b'{"type":"new-partial'])
        transport.server_sock = old
        record = transport.callback_manager.call_callbacks

        def callback(event, **kwargs):
            record(event, **kwargs)
            if event == "msg_first":
                transport.server_sock = replacement
                transport.handle_server_data()

        transport.callback_manager.call_callbacks = callback
        transport.handle_server_data()
        self.assertIs(transport.server_sock, replacement)
        self.assertEqual(transport.callback_manager.calls, [("msg_first", {})])
        self.assertEqual(transport.buffer, b'{"type":"new-partial')

    def test_oversized_complete_frame_disconnects_before_deserialization(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        payload = b'{"type":"oversized","data":"' + (b"x" * ((1 << 20) + 1)) + b'"}\n'
        chunks = [payload[index:index + 16384] for index in range(0, len(payload), 16384)]
        transport, sock, selector = transport_from_source(source, chunks)
        transport.serializer.deserialize = mock.Mock(
            side_effect=AssertionError("oversized frame must not be deserialized"))
        try:
            with mock.patch("select.select", selector):
                transport.run()
        finally:
            transport._disconnect()
        transport.serializer.deserialize.assert_not_called()
        self.assertFalse(transport.connected)
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(transport.buffer, b"")

    def test_oversized_unterminated_frame_disconnects_and_clears_partial_state(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        chunk = b"{" + (b"x" * 16383)
        incoming = [chunk] * 65
        transport, sock, selector = transport_from_source(source, incoming)
        try:
            with mock.patch("select.select", selector):
                transport.run()
        finally:
            transport._disconnect()
        self.assertFalse(transport.connected)
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(transport.buffer, b"")
        self.assertEqual(
            [event for event, _ in transport.callback_manager.calls],
            ["transport_connected", "transport_disconnected"],
        )

    def test_eof_with_truncated_frame_disconnects_and_clears_partial_state(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, selector = transport_from_source(
            source, [b'{"type":"speak","sequence":["truncated', b""]
        )
        try:
            with mock.patch("select.select", selector):
                transport.run()
        finally:
            transport._disconnect()
        self.assertFalse(transport.connected)
        self.assertTrue(sock.closed)
        self.assertIsNone(transport.server_sock)
        self.assertEqual(transport.buffer, b"")
        self.assertEqual(
            [event for event, _ in transport.callback_manager.calls],
            ["transport_connected", "transport_disconnected"],
        )

    def test_complete_frames_before_truncated_eof_are_delivered_once(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, selector = transport_from_source(
            source, [b'{"type":"ping","nonce":7}\n{"type":"partial', b""]
        )
        try:
            with mock.patch("select.select", selector):
                transport.run()
        finally:
            transport._disconnect()
        self.assertEqual(transport.callback_manager.calls, [
            ("transport_connected", {}), ("msg_ping", {"nonce": 7}),
            ("transport_disconnected", {}),
        ])
        self.assertTrue(sock.closed)
        self.assertEqual(transport.buffer, b"")

    def test_clean_eof_disconnects(self):
        source = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        transport, sock, selector = transport_from_source(source, [b""])
        with mock.patch("select.select", selector):
            transport.run()
        self.assertFalse(transport.connected)
        self.assertTrue(sock.closed)
        self.assertEqual(transport.buffer, b"")

    def test_v6_cleanup_patch_upgrades_to_v7(self):
        current = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        tree = ast.parse(current)
        tcp = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"
        )
        receiver = next(
            node for node in tcp.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "handle_server_data"
        )
        current_receiver = ast.get_source_segment(current, receiver)
        pending_v7 = (
            "\t\tif b'\\n' not in data:\n"
            "\t\t\tif len(data) > 1 << 20:\n"
            "\t\t\t\tself.buffer = b''\n"
            "\t\t\t\tself._disconnect()\n"
            "\t\t\t\treturn\n"
            "\t\t\tself.buffer += data\n"
            "\t\t\treturn"
        )
        pending_v6 = (
            "\t\tif b'\\n' not in data:\n"
            "\t\t\tself.buffer += data\n"
            "\t\t\treturn"
        )
        complete_v7 = (
            "\t\t\tline, sep, data = data.partition(b'\\n')\n"
            "\t\t\tif len(line) > 1 << 20:\n"
            "\t\t\t\tself.buffer = b''\n"
            "\t\t\t\tself._disconnect()\n"
            "\t\t\t\treturn\n"
            "\t\t\tself.parse(line)"
        )
        complete_v6 = (
            "\t\t\tline, sep, data = data.partition(b'\\n')\n"
            "\t\t\tself.parse(line)"
        )
        v6_receiver = current_receiver.replace(pending_v7, pending_v6, 1)
        v6_receiver = v6_receiver.replace(complete_v7, complete_v6, 1)
        self.assertNotEqual(v6_receiver, current_receiver)
        v6 = current.replace(current_receiver, v6_receiver, 1)
        v6 = v6.replace(
            remote_access.TRANSPORT_CLEANUP_MARKER,
            remote_access.TRANSPORT_CLEANUP_MARKER_V6,
            1,
        )
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(v6))
        upgraded = remote_access._patch_legacy_transport_cleanup(v6)
        self.assertTrue(remote_access.legacy_transport_cleanup_patch_current(upgraded))
        self.assertIn(remote_access.TRANSPORT_CLEANUP_MARKER, upgraded)
        self.assertNotIn(remote_access.TRANSPORT_CLEANUP_MARKER_V6 + "\\n", upgraded)
        self.assertIn("if len(data) > 1 << 20:", upgraded)
        self.assertIn("if len(line) > 1 << 20:", upgraded)


    def test_genuine_v5_upgrade_preserves_original_backup_and_is_idempotent(self):
        import tempfile
        fixture = Path(__file__).resolve().parents[2] / "fixtures/legacy-patches/transport-v5.txt"
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
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertFalse(remote_access._patch_legacy_transport_logging(path))
            self.assertEqual(path.read_text(), updated)
            transport, sock, selector = transport_from_source(updated, [b'{"type":"partial', b""])
            with mock.patch("select.select", selector):
                transport.run()
            self.assertFalse(transport.connected)
            self.assertTrue(sock.closed)
            self.assertEqual(transport.buffer, b"")

    def test_eof_guard_tampering_is_rejected(self):
        current = remote_access._patch_legacy_transport_cleanup(UPSTREAM)
        tampered = current.replace("if not received:", "if not self.buffer and not received:", 1)
        self.assertFalse(remote_access.legacy_transport_cleanup_patch_current(tampered))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            remote_access._patch_legacy_transport_cleanup(tampered)


if __name__ == "__main__":
    unittest.main()
