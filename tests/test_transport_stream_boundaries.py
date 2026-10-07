"""Exercise the complete pinned Orca Remote relay source, including its receiver.

Fixture: serrebidev/orca-remote d47a085945576d8e973f9c686587bdfc90ae061c,
orca-scripts/transport.py. Tests use fake sockets and native sender threads.
"""

import json
import re
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest import mock

import remote_access


UPSTREAM = (Path(__file__).parent / "fixtures/legacy-patches/transport-upstream.txt").read_text()


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
        pattern = (
            r"(?m)^([ \t]*)if b'\\n' not in data:[ \t]*\\n"
            r"([ \t]*)if len\\(data\\) > 1 << 20:[ \t]*\\n"
            r"([ \t]*)self\\.buffer = b''[ \t]*\\n"
            r"\\3self\\._disconnect\\(\\)[ \t]*\\n"
            r"\\3return[ \t]*\\n"
            r"\\2self\\.buffer \\+= data[ \t]*\\n"
            r"\\2return[ \t]*$"
        )

        def remove_bound(match):
            indent, body = match.group(1), match.group(2)
            return (
                indent + "if b'\\n' not in data:\\n"
                + body + "self.buffer += data\\n"
                + body + "return"
            )

        v6, count = re.subn(pattern, remove_bound, current, count=1)
        self.assertEqual(count, 1)
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

    def test_genuine_v5_upgrade_preserves_original_backup_and_is_idempotent(self):
        import tempfile
        fixture = Path(__file__).parent / "fixtures/legacy-patches/transport-v5.txt"
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
