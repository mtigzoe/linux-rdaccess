"""Actual patched upstream controller + transport TCP handshake in private Orca.

Runs only in isolated CI Orca customizations; TLS is replaced solely for
loopback so no credentials or external network are involved.
"""
import json
import socket
import threading


def exercise(RemoteController, RelayTransport, JSONSerializer):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    transport = RelayTransport(
        JSONSerializer(), listener.getsockname(),
        channel="test-only-real-controller", connection_type="slave")
    controller = RemoteController(transport)
    assert controller.transport is transport
    assert controller.local_machine is not None

    # The upstream transport normally wraps the socket with TLS. CI uses an
    # ephemeral localhost-only peer and plain TCP, never production secrets.
    def create_local_socket(address):
        assert address[0] == "127.0.0.1"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        return sock

    transport.create_outbound_socket = create_local_socket
    errors = []
    import time

    def connect():
        try:
            transport.run()
        except Exception as exc:
            errors.append(exc)

    def receive_handshake(peer):
        incoming = b""
        messages = []
        deadline = time.monotonic() + 5
        while len(messages) < 2 and time.monotonic() < deadline:
            chunk = peer.recv(8192)
            if not chunk:
                raise AssertionError("real transport disconnected before handshake")
            incoming += chunk
            while b"\n" in incoming:
                frame, incoming = incoming.split(b"\n", 1)
                messages.append(json.loads(frame))
        assert len(messages) >= 2, messages
        assert messages[0].get("type") == "protocol_version", messages
        assert messages[1].get("type") == "join", messages
        assert messages[1].get("channel") == "test-only-real-controller"

    worker = threading.Thread(target=connect, daemon=True)
    peer = None
    second = None
    try:
        worker.start()
        peer, address = listener.accept()
        assert address[0] == "127.0.0.1"
        peer.settimeout(5)
        receive_handshake(peer)
        assert transport.connected
        # Drop a partial protocol frame and force native cleanup.
        peer.sendall(b'{"type":"key","vk_code":16')
        peer.shutdown(socket.SHUT_RDWR)
        peer.close()
        peer = None
        worker.join(timeout=5)
        assert not worker.is_alive(), "old receiver survived disconnect"
        assert not transport.connected
        assert transport.buffer == b"", "old partial frame survived disconnect"
        assert transport.queue_thread is None, "sender thread survived disconnect"
        # Reuse the same transport/controller for a genuinely fresh connection.
        second = threading.Thread(target=connect, daemon=True)
        second.start()
        peer, address = listener.accept()
        assert address[0] == "127.0.0.1"
        peer.settimeout(5)
        receive_handshake(peer)
        assert transport.connected
        assert controller.transport is transport
    finally:
        transport.close()
        if peer is not None:
            peer.close()
        listener.close()
        worker.join(timeout=5)
        if second is not None:
            second.join(timeout=5)
            assert not second.is_alive(), "second receiver survived close"
        assert not worker.is_alive(), "real transport worker survived close"
    assert not errors, errors
