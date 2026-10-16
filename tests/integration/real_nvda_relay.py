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
                "expected real-relay key callbacks: " + repr({"expected_count": count, "actual_events": list(key_events), "transport_connected": transport.connected, "connected_clients": dict(controller.connected_clients), "relay_channels": {key: len(value) for key, value in real_server.channels.items()}}))

        def send_key(peer, pressed, *, key_name="Shift", vk_code=16):
            peer.sendall((json.dumps({
                "type": "key", "key_name": key_name,
                "pressed": pressed, "vk_code": vk_code,
            }) + "\n").encode("utf-8"))
        sessions = []

        # Observe whether the real sender queue emits a protocol handshake.
        original_send = transport.send
        sent = []
        def observed_send(type, **kwargs):
            sent.append((type, sorted(kwargs)))
            return original_send(type, **kwargs)
        transport.send = observed_send

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
                    return
                time.sleep(0.02)
            raise AssertionError("actual upstream transport never joined real relay: " + repr({"transport_connected": transport.connected, "worker_alive": worker.is_alive(), "worker_errors": [str(e) for e in errors], "relay_clients": [(c.id, c.channel_id) for c in real_server.clients], "relay_channels": list(real_server.channels), "successful_connects": transport.successful_connects, "queue_size": transport.queue.qsize(), "sender_alive": bool(transport.queue_thread and transport.queue_thread.is_alive()), "socket": repr(transport.server_sock), "sent": sent, "relay_handshake": relay_handshake_messages}))

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
