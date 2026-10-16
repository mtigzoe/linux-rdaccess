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
    def connect():
        try:
            transport.run()
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=connect, daemon=True)
    peer = None
    try:
        worker.start()
        peer, address = listener.accept()
        assert address[0] == "127.0.0.1"
        peer.settimeout(5)
        # Real RelayTransport.on_connected sends protocol_version and join.
        incoming = b""
        messages = []
        while len(messages) < 2:
            chunk = peer.recv(8192)
            if not chunk:
                raise AssertionError("real transport disconnected before handshake")
            incoming += chunk
            while b"\n" in incoming:
                frame, incoming = incoming.split(b"\n", 1)
                messages.append(json.loads(frame))
        assert messages[0].get("type") == "protocol_version", messages
        assert messages[1].get("type") == "join", messages
        assert messages[1].get("channel") == "test-only-real-controller"
        assert transport.connected
    finally:
        transport.close()
        if peer is not None:
            peer.close()
        listener.close()
        worker.join(timeout=5)
        assert not worker.is_alive(), "real transport worker survived close"
    assert not errors, errors
