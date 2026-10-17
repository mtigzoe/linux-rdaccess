"""Exercise patched upstream Orca against a pinned, real NVDA Remote relay.

Both the relay and the Orca controller run in an isolated Orca CI process.
This verifies shared-channel isolation, not cryptographic authorization of a
channel password: the relay treats possession of the channel string as access.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import ssl
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace


def exercise_relay(RemoteController, RelayTransport, JSONSerializer):
    relay_file = Path(os.environ["LRD_PINNED_RELAY_FILE"])
    spec = importlib.util.spec_from_file_location("lrd_private_real_relay", relay_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Observe real relay inbound key frames without modifying forwarding.
    relay_key_messages = []
    relay_handshake_messages = []
    original_process = module.Client.process_message
    async def observed_process(client, line):
        try:
            message = json.loads(line)
            if message.get("type") in ("join", "protocol_version"):
                relay_handshake_messages.append((client.id, message.get("type"), bool(message.get("channel"))))
            if message.get("type") == "key":
                relay_key_messages.append({
                    "client_id": client.id,
                    "channel": client.channel_id,
                    "key_name": message.get("key_name"),
                    "pressed": message.get("pressed"),
                })
        except (ValueError, TypeError):
            pass
        return await original_process(client, line)
    module.Client.process_message = observed_process
    # Correlate actual relay read boundaries with individual client TLS writes.
    # Record only frame types/lengths and ephemeral ports, never channel keys.
    relay_read_lines = []
    active_readers = {}
    original_handle_client = module.AsyncServer.handle_client

    async def observed_handle_client(server, reader, writer):
        peer = writer.get_extra_info("peername")
        peer_port = peer[1] if peer else None
        original_readline = reader.readline
        active_readers[peer_port] = reader

        async def observed_readline():
            line = await original_readline()
            try:
                kind = json.loads(line).get("type") if line else "EOF"
            except (ValueError, TypeError, AttributeError):
                kind = "invalid"
            relay_read_lines.append(
                (round(time.monotonic(), 3), peer_port, kind, len(line)))
            return line

        reader.readline = observed_readline
        try:
            return await original_handle_client(server, reader, writer)
        finally:
            active_readers.pop(peer_port, None)

    module.AsyncServer.handle_client = observed_handle_client
    with tempfile.TemporaryDirectory(prefix="lrd-genuine-relay-") as tmp:
        cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-nodes", "-days", "1", "-subj", "/CN=localhost",
                        "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True, timeout=15)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert), str(key))
        args = SimpleNamespace(max_msg_size=65536, tracebacks=True,
                               motd="", motd_force=False)
        real_server = module.AsyncServer(args)
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        bound = {}
        errors = []

        async def server_main():
            server = await asyncio.start_server(
                real_server.handle_client, "127.0.0.1", 0, ssl=ctx)
            bound["port"] = server.sockets[0].getsockname()[1]
            bound["server"] = server
            ready.set()
            await server.serve_forever()

        def serve():
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(server_main())
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                errors.append(exc)
                ready.set()
            finally:
                loop.close()

        relay_worker = threading.Thread(target=serve, daemon=True)
        relay_worker.start()
        assert ready.wait(8), "real relay failed to bind"
        assert not errors, errors
        address = ("127.0.0.1", bound["port"])
        channel = secrets.token_urlsafe(20)
        other_channel = secrets.token_urlsafe(20)
        transport = RelayTransport(
            JSONSerializer(), address, channel=channel, connection_type="slave")
        controller = RemoteController(transport)
        # Observe parsed incoming frames at the Orca callback boundary.
        controller_key_callbacks = []
        transport.callback_manager.register_callback(
            "msg_key", lambda **event: controller_key_callbacks.append(dict(event)))

        # Intercept key injection at the final controller boundary. The real
        # relay and RemoteController callbacks remain active, but never send
        # keys to the runner desktop.
        key_events = []
        def observe_key(**event):
            key_events.append(dict(event))
            return True
        controller.local_machine.send_key = observe_key

        def await_keys(count):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if len(key_events) >= count:
                    return
                time.sleep(0.02)
            raise AssertionError(
                "expected real-relay key callbacks: " + repr({"expected_count": count, "actual_events": list(key_events), "transport_connected": transport.connected, "connected_clients": dict(controller.connected_clients), "server": server_snapshot()}))

        def send_key(peer, pressed, *, key_name="Shift", vk_code=16):
            peer.sendall((json.dumps({
                "type": "key", "key_name": key_name,
                "pressed": pressed, "vk_code": vk_code,
            }) + "\n").encode("utf-8"))
        sessions = []

        # Observe whether the real sender queue emits a protocol handshake.
        original_send = transport.send
        sent = []
        # Keep an audit of actual sender socket writes. A send() request alone
        # is not proof its queued frame reached the TLS socket.
        writes = []
        socket_connects = []
        socket_closes = []
        original_create = transport.create_outbound_socket
        next_socket_id = 0

        class ObservedSocket:
            def __init__(self, sock):
                nonlocal next_socket_id
                next_socket_id += 1
                self._socket_id = next_socket_id
                self._local_port = None
                self._sock = sock

            def connect(self, address):
                result = self._sock.connect(address)
                self._local_port = self._sock.getsockname()[1]
                socket_connects.append((
                    round(time.monotonic(), 3), self._socket_id,
                    self._local_port))
                return result

            def sendall(self, payload):
                result = self._sock.sendall(payload)
                try:
                    kind = json.loads(payload).get("type")
                except (ValueError, TypeError, AttributeError):
                    kind = "invalid"
                writes.append((
                    round(time.monotonic(), 3), self._socket_id,
                    self._local_port, transport.successful_connects,
                    kind, len(payload)))
                return result

            def close(self):
                socket_closes.append((
                    round(time.monotonic(), 3), self._socket_id,
                    self._local_port, "close"))
                return self._sock.close()

            def shutdown(self, how):
                socket_closes.append((
                    round(time.monotonic(), 3), self._socket_id,
                    self._local_port, "shutdown", how))
                return self._sock.shutdown(how)
            def __getattr__(self, name):
                return getattr(self._sock, name)
            def fileno(self):
                return self._sock.fileno()
        def observed_create(address):
            return ObservedSocket(original_create(address))
        transport.create_outbound_socket = observed_create
        def observed_send(type, **kwargs):
            sent.append((type, sorted(kwargs)))
            return original_send(type, **kwargs)
        transport.send = observed_send

        async def inspect_server():
            def channel_label(channel_id):
                if channel_id is None:
                    return "unjoined"
                if channel_id == channel:
                    return "target"
                if channel_id == other_channel:
                    return "other"
                return "unexpected"

            return {
                "clients": [
                    (client.id, channel_label(client.channel_id),
                     client.connection_type)
                    for client in real_server.clients
                ],
                "channels": [
                    (channel_label(key), len(members))
                    for key, members in real_server.channels.items()
                ],
                "readers": [
                    (peer_port, len(getattr(reader, "_buffer", b"")),
                     reader.at_eof(),
                     type(reader.exception()).__name__ if reader.exception()
                     else None)
                    for peer_port, reader in active_readers.items()
                ],
            }

        def server_snapshot():
            # Inspect asyncio-owned client/channel sets from their own loop.
            future = asyncio.run_coroutine_threadsafe(inspect_server(), loop)
            try:
                return future.result(timeout=2)
            except Exception as exc:
                return {"snapshot_error": type(exc).__name__}

        def sender_tcp_state():
            # Linux TCP_INFO is independent of the TLS plaintext parser.
            # Unacknowledged TCP segments distinguish outstanding network
            # delivery from data acknowledged by the peer's TCP stack.
            sock = transport.server_sock
            if sock is None:
                return None
            try:
                info = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 104)
                return {
                    "state": info[0],
                    "unacked_segments": struct.unpack_from("=I", info, 24)[0],
                    "socket_error": sock.getsockopt(
                        socket.SOL_SOCKET, socket.SO_ERROR),
                }
            except (AttributeError, OSError, struct.error) as exc:
                return {"tcp_info_error": type(exc).__name__}

        def start_orca():
            def run():
                try:
                    transport.run()
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=run, daemon=True)
            sessions.append(worker)
            worker.start()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if transport.connected and any(
                    client.channel_id == channel
                    for client in real_server.clients
                ):
                    # Once the relay has joined, both frames must have been
                    # seen at its read boundary for this socket's local port.
                    # This also validates the diagnostic port correlation on
                    # successful first connections and reconnects.
                    local_port = socket_connects[-1][2]
                    observed = [
                        kind for _, peer_port, kind, _ in relay_read_lines
                        if peer_port == local_port
                    ]
                    assert "protocol_version" in observed and "join" in observed, (
                        "relay frame observer missed the joined socket: " +
                        repr({"local_port": local_port, "frames": observed}))
                    return
                time.sleep(0.02)
            raise AssertionError("actual upstream transport never joined real relay: " + repr({"transport_connected": transport.connected, "worker_alive": worker.is_alive(), "worker_errors": [str(e) for e in errors], "server": server_snapshot(), "successful_connects": transport.successful_connects, "queue_size": transport.queue.qsize(), "sender_alive": bool(transport.queue_thread and transport.queue_thread.is_alive()), "tcp_state": sender_tcp_state(), "sent": sent, "relay_handshake": relay_handshake_messages, "relay_read_lines": relay_read_lines[-30:], "socket_connects": socket_connects, "socket_writes": writes, "socket_closes": socket_closes}))

        def master(key_string):
            peer = ssl._create_unverified_context().wrap_socket(
                socket.socket(), server_hostname="localhost")
            peer.settimeout(8)
            peer.connect(address)
            peer.sendall((json.dumps({"type": "protocol_version", "version": 2}) +
                          "\n").encode())
            peer.sendall((json.dumps({"type": "join", "channel": key_string,
                                      "connection_type": "master"}) +
                          "\n").encode())
            return peer

        def members(expected):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if len(controller.connected_clients) == expected:
                    return
                time.sleep(0.02)
            raise AssertionError(
                "unexpected real controller membership: " +
                repr(controller.connected_clients))

        peers = []
        try:
            start_orca()
            unauthorized = master(other_channel)
            peers.append(unauthorized)
            members(0)
            authorized = master(channel)
            peers.append(authorized)
            members(1)
            send_key(authorized, True)
            await_keys(1)
            assert key_events[0]["pressed"] is True
            assert controller._lrd_forwarded, "Shift press did not acquire held-key ownership"
            # Losing the relay while Shift is held must release that modifier.
            # Record the actual local-machine boundary without touching X11.
            authorized.close()
            peers.remove(authorized)
            members(0)
            transport.close()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not any(
                e["key_name"] == "Shift" and e["pressed"] is False
                for e in key_events
            ):
                time.sleep(0.02)
            assert any(
                e["key_name"] == "Shift" and e["pressed"] is False
                for e in key_events
            ), "held Shift was not released on transport disconnect: " + repr(key_events)
            assert not controller._lrd_forwarded, "held-key ownership survived disconnect"
            sessions[-1].join(timeout=8)
            assert not sessions[-1].is_alive()
            assert transport.buffer == b""
            assert not controller.connected_clients
            previous_keys = len(key_events)
            # The upstream transport's previous sender used this queue.
            # Give the new test connection an empty queue after confirming
            # its old sender exited, as in the isolated TLS reconnect smoke.
            import queue
            assert transport.queue_thread is None
            transport.queue = queue.Queue()
            start_orca()
            recovered = master(channel)
            peers.append(recovered)
            members(1)
            assert len(key_events) == previous_keys, "old key replayed after reconnect"
            # A distinct key identifies fresh-session delivery even if the
            # disconnect callback generated a Shift release independently.
            # Unmatched key-up is intentionally ignored by the production
            # controller. Exercise a complete *new-session* press/release pair.
            send_key(recovered, True, key_name="Control", vk_code=17)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not any(
                e["key_name"] == "Control" and e["pressed"] is True
                for e in key_events[previous_keys:]
            ):
                time.sleep(0.02)
            assert any(
                e["key_name"] == "Control" and e["pressed"] is True
                for e in key_events[previous_keys:]
            ), "fresh-session Control press never reached real controller: " + repr(key_events)
            send_key(recovered, False, key_name="Control", vk_code=17)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not any(
                e["key_name"] == "Control" and e["pressed"] is False
                for e in key_events[previous_keys:]
            ):
                time.sleep(0.02)
            assert any(
                e["key_name"] == "Control" and e["pressed"] is False
                for e in key_events[previous_keys:]
            ), "fresh-session Control release never reached real controller: " + repr({"controller_events": key_events, "relay_inbound": relay_key_messages, "controller_key_callbacks": controller_key_callbacks, "relay_clients": [(c.id, c.channel_id) for c in real_server.clients]})
        finally:
            transport.close()
            for peer in peers:
                peer.close()
            for worker in sessions:
                worker.join(timeout=8)
            loop.call_soon_threadsafe(
                lambda: [task.cancel() for task in asyncio.all_tasks(loop)])
            relay_worker.join(timeout=8)
        assert not errors, errors
        assert not any(w.is_alive() for w in sessions)
        assert not relay_worker.is_alive(), "real relay worker remained alive"
