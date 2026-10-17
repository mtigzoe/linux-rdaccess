"""Validate patched TLS application-frame delivery after a successful handshake.

Independent loopback probe using the actual pinned Orca Remote transport patch.
A sender thread writes application frames while select()/recv() reads the
same per-socket I/O wrapper; control completes writes before reading. The test
reports counts and asserts that the protected transport delivers every frame.
No NVDA, Orca, user credential, installed desktop or network relay is used.
"""
import asyncio
from collections import Counter
from contextlib import suppress
import json
import os
from pathlib import Path
import select
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace

from tests.unit.transport.test_tls_socket_serialization import patched_transport


ITERATIONS = int(os.environ.get("LRD_POSTCONNECT_TLS_PROBE_ITERATIONS", "60"))
MESSAGES = 8


def exercise():
    with tempfile.TemporaryDirectory(prefix="lrd-postconnect-tls-") as folder:
        cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-nodes", "-days", "1", "-subj", "/CN=localhost",
             "-keyout", str(key), "-out", str(cert)],
            check=True, capture_output=True, timeout=15)
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(str(cert), str(key))
        namespace = patched_transport()
        transport_class = namespace["TCPTransport"]
        serial_class = namespace["_linux_rdaccess_serial_ssl_socket"]
        loop = asyncio.new_event_loop()
        port, received, errors = [], {}, []
        ready = threading.Event()

        async def handle(reader, writer):
            addr = writer.get_extra_info("peername")
            peer_port = addr[1] if addr else None
            received[peer_port] = []
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        kind = json.loads(line).get("type")
                    except (ValueError, AttributeError, TypeError):
                        break
                    received[peer_port].append(kind)
                    if kind == "join":
                        writer.write(b'{"type":"channel_joined"}\n')
                        await writer.drain()
                    elif kind == "app":
                        writer.write(b'{"type":"ack"}\n')
                        await writer.drain()
            except (OSError, ssl.SSLError) as exc:
                errors.append(type(exc).__name__)
            finally:
                with suppress(Exception):
                    writer.close()
                    await writer.wait_closed()

        async def serve():
            server = await asyncio.start_server(
                handle, "127.0.0.1", 0, ssl=server_ctx)
            port.append(server.sockets[0].getsockname()[1])
            ready.set()
            async with server:
                await server.serve_forever()

        def run_server():
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(serve())
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        assert ready.wait(8), "isolated TLS server did not bind"

        totals = {}
        for serialize in (False, True):
            counts = Counter()
            for _ in range(ITERATIONS):
                transport = transport_class(
                    SimpleNamespace(deserialize=lambda frame: json.loads(frame)),
                    ("127.0.0.1", port[0]),
                )
                client = transport.create_outbound_socket(("127.0.0.1", port[0]))
                assert isinstance(client, serial_class), (
                    "outbound factory did not install the SSL socket I/O gate")
                client.settimeout(0.15)
                client.connect(("127.0.0.1", port[0]))
                client_port = client.getsockname()[1]
                # Both variants first complete the original initial
                # handshake, then exercise only *post-join* traffic.
                client.sendall(b'{"type":"protocol_version"}\n')
                client.sendall(b'{"type":"join"}\n')
                deadline = time.monotonic() + 0.25
                while (time.monotonic() < deadline
                       and "join" not in received.get(client_port, ())):
                    time.sleep(0.001)
                if "join" not in received.get(client_port, ()):
                    counts["initial_join_failed"] += 1
                    client.close()
                    continue

                in_recv = threading.Event()
                overlaps, send_errors = [], []

                def write_app():
                    for seq in range(MESSAGES):
                        if in_recv.is_set():
                            overlaps.append(seq)
                        try:
                            client.sendall(b'{"type":"app"}\n')
                        except (OSError, ssl.SSLError) as exc:
                            send_errors.append(type(exc).__name__)
                            return

                writer_thread = threading.Thread(
                    target=write_app, daemon=True)
                writer_thread.start()
                if serialize:
                    writer_thread.join(1)

                deadline = time.monotonic() + 0.15
                while (time.monotonic() < deadline
                       and received.get(client_port, ()).count("app")
                       < MESSAGES):
                    readable, _, _ = select.select(
                        [client], [], [], 0.005)
                    if readable:
                        in_recv.set()
                        try:
                            client.recv(16384)
                        except (OSError, ssl.SSLError):
                            pass
                        finally:
                            in_recv.clear()

                writer_thread.join(1)
                if writer_thread.is_alive():
                    counts["sender_still_alive"] += 1
                delivered = received.get(client_port, ()).count("app")
                if delivered == MESSAGES:
                    counts["all_app_frames"] += 1
                else:
                    counts["missing_app_frames"] += 1
                    if overlaps:
                        counts["missing_with_ssl_overlap"] += 1
                counts["ssl_overlap_sessions"] += bool(overlaps)
                counts["write_error_sessions"] += bool(send_errors)
                with suppress(OSError):
                    client.close()

            totals["serialized_app_writes" if serialize
                   else "concurrent_app_writes"] = dict(counts)

        for mode, observed in totals.items():
            assert observed.get("all_app_frames") == ITERATIONS, (
                "patched SSL transport lost post-connect application frames: "
                + repr({"mode": mode, "counts": observed}))
            assert observed.get("initial_join_failed", 0) == 0
            assert observed.get("sender_still_alive", 0) == 0
            assert observed.get("write_error_sessions", 0) == 0

        print(json.dumps({
            "python": __import__("sys").version.split()[0],
            "openssl": ssl.OPENSSL_VERSION,
            "connections_per_mode": ITERATIONS,
            "app_frames_per_connection": MESSAGES,
            "results": totals,
            "server_errors": dict(Counter(errors)),
        }, sort_keys=True))
        loop.call_soon_threadsafe(
            lambda: [task.cancel() for task in asyncio.all_tasks(loop)])
        thread.join(5)
        assert not thread.is_alive(), "isolated TLS server did not exit"


if __name__ == "__main__":
    exercise()
