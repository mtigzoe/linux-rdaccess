"""Real upstream Orca Remote TLS transport reconnect, isolated to localhost.

This checks TLS encryption and the real transport handshake/recovery. The
upstream client disables peer certificate validation, so it does NOT prove
certificate authentication or a real NVDA Remote relay's channel authorization.
"""
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time


def exercise_tls(RemoteController, RelayTransport, JSONSerializer):
    with tempfile.TemporaryDirectory(prefix="lrd-orca-tls-") as tmp:
        cert = Path(tmp) / "cert.pem"
        key = Path(tmp) / "key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-nodes", "-days", "1", "-subj", "/CN=localhost",
            "-keyout", str(key), "-out", str(cert),
        ], check=True, capture_output=True, timeout=15)
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(str(cert), str(key))
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(8)
        transport = RelayTransport(
            JSONSerializer(), listener.getsockname(),
            channel="test-only-tls-channel", connection_type="slave")
        controller = RemoteController(transport)
        assert controller.transport is transport
        errors = []
        workers = []
        peer = None

        def run_transport():
            try:
                transport.run()
            except Exception as exc:
                errors.append(exc)

        def accept_tls():
            raw, address = listener.accept()
            assert address[0] == "127.0.0.1"
            raw.settimeout(8)
            return server_ctx.wrap_socket(raw, server_side=True)

        def handshake(peer):
            buf = b""
            messages = []
            deadline = time.monotonic() + 8
            while len(messages) < 2 and time.monotonic() < deadline:
                chunk = peer.recv(8192)
                if not chunk:
                    raise AssertionError("TLS peer disconnected before join")
                buf += chunk
                while b"\n" in buf:
                    frame, buf = buf.split(b"\n", 1)
                    messages.append(json.loads(frame))
            assert len(messages) >= 2, messages
            assert [m.get("type") for m in messages[:2]] == [
                "protocol_version", "join"], messages
            assert messages[1]["channel"] == "test-only-tls-channel"
            assert transport.connected
 
        def await_clients(expected):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if set(controller.connected_clients) == set(expected):
                    return
                time.sleep(0.02)
            raise AssertionError(
                "unexpected controller clients: " + repr(controller.connected_clients))

        def relay_event(peer, **message):
            peer.sendall((json.dumps(message) + "\n").encode("utf-8"))

        try:
            for cycle in range(2):
                worker = threading.Thread(target=run_transport, daemon=True)
                workers.append(worker)
                worker.start()
                peer = accept_tls()
                assert peer.version() in {"TLSv1.2", "TLSv1.3"}
                handshake(peer)
                # A channel_joined frame is a *fixture* relay authorization
                # response, not independent proof a real relay checked the key.
                client_id = "peer-" + str(cycle)
                relay_event(peer, type="channel_joined",
                            channel="test-only-tls-channel",
                            clients=[{"id": client_id, "connection_type": "master"}])
                await_clients([client_id])
                relay_event(peer, type="client_left", client={"id": client_id})
                await_clients([])
                if cycle == 0:
                    peer.sendall(b'{"type":"key","vk_code":17')
                    # Simulate relay loss with an incomplete frame.
                    peer.close()
                    peer = None
                    worker.join(timeout=8)
                    assert not worker.is_alive(), "old TLS receiver still running"
                    assert not transport.connected
                    assert transport.buffer == b"", "TLS partial frame leaked"
                    assert transport.queue_thread is None, "TLS sender thread leaked"
                    await_clients([])
        finally:
            transport.close()
            if peer is not None:
                peer.close()
            listener.close()
            for worker in workers:
                worker.join(timeout=8)
                assert not worker.is_alive(), "TLS receiver worker leaked"
        assert not errors, errors
