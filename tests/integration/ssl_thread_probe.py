"""Isolated TLS read/write concurrency probe for genuine-relay issue #123.

This is a measurement, not a flaky pass/fail regression: a concurrent
handshake may succeed or stall depending on Python/OpenSSL scheduling. The
serialized-handshake control tests the same frames on the same TLS setup.
Runs on localhost only, without Orca, NVDA or production credentials.
"""
import asyncio
from collections import Counter
from contextlib import suppress
import json
import os
from pathlib import Path
import queue
import select
import socket
import ssl
import subprocess
import tempfile
import threading
import time


ITERATIONS = int(os.environ.get("LRD_TLS_PROBE_ITERATIONS", "150"))
FRAME_WAIT_SECONDS = 0.45


def exercise():
    with tempfile.TemporaryDirectory(prefix="lrd-tls-probe-") as tmp:
        cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-days", "1", "-subj", "/CN=localhost", "-keyout", str(key),
             "-out", str(cert)],
            check=True, capture_output=True, timeout=15)
        server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_tls.load_cert_chain(str(cert), str(key))
        client_tls = ssl.create_default_context()
        client_tls.check_hostname = False
        client_tls.verify_mode = ssl.CERT_NONE

        loop = asyncio.new_event_loop()
        ready = threading.Event()
        bound = {}
        observed_frames = {}
        server_errors = []

        async def handle(reader, writer):
            address = writer.get_extra_info("peername")
            peer_port = address[1] if address else None
            observed_frames[peer_port] = []
            try:
                while True:
                    frame = await reader.readline()
                    if not frame:
                        break
                    try:
                        kind = json.loads(frame).get("type")
                    except (TypeError, ValueError, AttributeError):
                        kind = "invalid"
                    observed_frames[peer_port].append(kind)
                    if kind == "join":
                        writer.write(b'{"type":"channel_joined"}\n')
                        await writer.drain()
            except (OSError, ssl.SSLError) as exc:
                # Concurrent TLS reads and writes may corrupt the session.
                server_errors.append(type(exc).__name__)
            finally:
                with suppress(Exception):
                    writer.close()
                    await writer.wait_closed()

        async def serve():
            server = await asyncio.start_server(
                handle, "127.0.0.1", 0, ssl=server_tls)
            bound["port"] = server.sockets[0].getsockname()[1]
            ready.set()
            async with server:
                await server.serve_forever()

        def serve_in_thread():
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(serve())
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        relay_worker = threading.Thread(target=serve_in_thread, daemon=True)
        relay_worker.start()
        assert ready.wait(8), "isolated TLS relay failed to bind"

        totals = {}
        protocol = (json.dumps({"type": "protocol_version", "version": 2})
                    + "\n").encode("utf-8")
        join = (json.dumps({"type": "join", "channel": "localhost-test",
                            "connection_type": "slave"})
                + "\n").encode("utf-8")

        for serialized in (False, True):
            summary = Counter()
            for _ in range(ITERATIONS):
                peer = client_tls.wrap_socket(socket.socket())
                peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                peer.connect(("127.0.0.1", bound["port"]))
                # Set timeout before starting either thread: changing the
                # socket timeout while sendall is active would add a race.
                peer.settimeout(0.15)
                local_port = peer.getsockname()[1]
                outbound = queue.Queue()
                for frame in (protocol, join, None):
                    outbound.put(frame)
                recv_active = threading.Event()
                write_overlaps = []
                send_errors = []

                def write_frames():
                    while True:
                        payload = outbound.get()
                        if payload is None:
                            return
                        if recv_active.is_set():
                            write_overlaps.append(True)
                        try:
                            peer.sendall(payload)
                        except (OSError, ssl.SSLError) as exc:
                            send_errors.append(type(exc).__name__)
                            return

                sender = threading.Thread(target=write_frames, daemon=True)
                sender.start()
                if serialized:
                    sender.join(1)

                deadline = time.monotonic() + FRAME_WAIT_SECONDS
                while time.monotonic() < deadline:
                    if "join" in observed_frames.get(local_port, ()):
                        break
                    readers, _, _ = select.select([peer], [], [], 0.01)
                    if readers:
                        recv_active.set()
                        try:
                            peer.recv(16384)
                        except (OSError, ssl.SSLError):
                            pass
                        finally:
                            recv_active.clear()

                sender.join(1)
                frames = tuple(observed_frames.get(local_port, ()))
                if "join" in frames:
                    summary["joined"] += 1
                elif "protocol_version" in frames:
                    summary["protocol_only"] += 1
                    if write_overlaps:
                        summary["protocol_only_with_overlap"] += 1
                else:
                    summary["no_protocol"] += 1
                summary["write_overlap_sessions"] += bool(write_overlaps)
                summary["send_errors"] += bool(send_errors)
                with suppress(OSError):
                    peer.close()

            totals["serialized_handshake" if serialized
                   else "concurrent_handshake"] = dict(summary)

        print(json.dumps({
            "python": __import__("sys").version.split()[0],
            "openssl": ssl.OPENSSL_VERSION,
            "iterations_per_mode": ITERATIONS,
            "results": totals,
            "server_errors": dict(Counter(server_errors)),
        }, sort_keys=True))
        loop.call_soon_threadsafe(
            lambda: [task.cancel() for task in asyncio.all_tasks(loop)])
        relay_worker.join(5)
        assert not relay_worker.is_alive(), "isolated TLS relay did not exit"


if __name__ == "__main__":
    exercise()
