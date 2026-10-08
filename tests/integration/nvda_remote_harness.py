"""Disposable loopback peer for the pinned Orca Remote transport.

Only the TLS socket factory and external Orca services are replaced. The
production-patched transport runs its real connect/select/recv/send/cleanup
paths, including its sender and reconnection threads. This peer implements
newline-delimited protocol-v2 messages, not a Windows NVDA speech synthesizer
or braille driver. It never reads user configuration or opens a public relay.
"""

from __future__ import annotations

import json
from pathlib import Path
import queue
import socket
import sys
import threading
import types
from unittest import mock

from linux_rdaccess_core.connection import remote_access


def packet(**message):
    return (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")


class ProtocolSerializer:
    def serialize(self, **message):
        return packet(**message)

    def deserialize(self, data):
        return json.loads(data)


class CallbackManager:
    def __init__(self):
        self.callbacks = {}
        self.events = []
        self.condition = threading.Condition()

    def register_callback(self, event, callback):
        with self.condition:
            self.callbacks.setdefault(event, []).append(callback)

    def call_callbacks(self, event, **kwargs):
        with self.condition:
            callbacks = tuple(self.callbacks.get(event, ()))
        for callback in callbacks:
            callback(**kwargs)
        # Record completion rather than receipt so assertions never race the
        # callback's side effects on the transport receiver thread.
        with self.condition:
            self.events.append((event, kwargs))
            self.condition.notify_all()

    def wait_for(self, event, count=1, timeout=3):
        with self.condition:
            ok = self.condition.wait_for(
                lambda: sum(name == event for name, _ in self.events) >= count,
                timeout=timeout,
            )
            if not ok:
                raise AssertionError(f"callback did not complete: {event}")


def transport_class():
    source = (Path(__file__).resolve().parents[1]
              / "fixtures/legacy-patches/transport-upstream.txt").read_text()
    source = remote_access._patch_legacy_transport_cleanup(source)
    # Match the installed transport's privacy patch as well as its lifecycle.
    source = source.replace(
        'log.info("Connecting to %s channel %s" % (address, channel))',
        'log.info("Connecting to NVDA Remote relay (connection details redacted)")',
    )
    callback_module = types.ModuleType("callback_manager")
    callback_module.CallbackManager = CallbackManager
    namespace = {}
    with mock.patch.dict(sys.modules, {"callback_manager": callback_module}):
        exec(compile(source, "loopback-orca-remote-transport", "exec"), namespace)
    return namespace["RelayTransport"]


class LoopbackSession:
    """A real TCP relay peer with deterministic message and lifecycle waits."""

    def __init__(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(("127.0.0.1", 0))
            self.listener.listen(1)
            self.listener.settimeout(3)
            self.address = self.listener.getsockname()
            self.transport = transport_class()(
                ProtocolSerializer(), self.address,
                channel="linux-rdaccess-loopback-test-only", connection_type="slave",
            )
        except BaseException:
            self.listener.close()
            raise
        self.transport.create_outbound_socket = self._plain_loopback_socket
        self.receiver_condition = threading.Condition()
        receive = self.transport.handle_server_data

        def observed_receive():
            try:
                return receive()
            finally:
                with self.receiver_condition:
                    self.receiver_condition.notify_all()

        self.transport.handle_server_data = observed_receive
        self.peer = None
        self.buffer = b""
        self.workers = []
        self.errors = queue.Queue()
        self.closed = False

    @staticmethod
    def _plain_loopback_socket(address):
        if address[0] != "127.0.0.1":
            raise AssertionError("integration transport must stay on loopback")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    def _run(self):
        try:
            self.transport.run()
        except BaseException as error:
            self.errors.put(error)

    def start(self, *, native_reconnector=False):
        if native_reconnector:
            worker = self.transport.reconnector_thread
            worker.connect_delay = 0.02
        else:
            worker = threading.Thread(target=self._run, daemon=True)
        self.workers.append(worker)
        worker.start()
        self.accept()
        return worker

    def accept(self):
        self.peer, _ = self.listener.accept()
        self.peer.settimeout(3)
        self.buffer = b""
        expected = [
            {"type": "protocol_version", "version": 2},
            {"type": "join", "channel": "linux-rdaccess-loopback-test-only",
             "connection_type": "slave"},
        ]
        received = [self.read(), self.read()]
        if received != expected:
            raise AssertionError(f"incorrect protocol handshake: {received!r}")

    def read(self):
        while b"\n" not in self.buffer:
            data = self.peer.recv(16384)
            if not data:
                raise AssertionError("transport closed before expected message")
            self.buffer += data
        line, _, self.buffer = self.buffer.partition(b"\n")
        return json.loads(line)

    def read_through_barrier(self):
        self.transport.send(type="test_barrier")
        messages = []
        while True:
            message = self.read()
            if message == {"type": "test_barrier"}:
                return messages
            messages.append(message)

    def send(self, **message):
        self.peer.sendall(packet(**message))

    def barrier(self):
        # A callback at the tail of an incoming batch proves all its messages
        # were processed, even when they produce no outgoing packets.
        manager = self.transport.callback_manager
        count = sum(name == "msg_test_barrier" for name, _ in manager.events) + 1
        self.send(type="test_barrier")
        manager.wait_for("msg_test_barrier", count=count)

    def wait_for_buffer(self, expected):
        with self.receiver_condition:
            if not self.receiver_condition.wait_for(
                    lambda: self.transport.buffer == expected, timeout=3):
                raise AssertionError("partial wire message was not buffered")

    def disconnect_peer(self):
        if self.peer is not None:
            peer = self.peer
            self.peer = None
            try:
                peer.shutdown(socket.SHUT_RDWR)
            finally:
                peer.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        failures = []
        # Also cancel retries when a deliberately failing close callback stops
        # the transport's own close() before it reaches the cancellation flag.
        self.transport.reconnector_thread.running = False
        try:
            self.transport.close()
        except BaseException as error:
            failures.append(error)
        finally:
            # Always release both ends, even when transport cleanup fails.
            try:
                self.disconnect_peer()
            except OSError:
                pass
            self.listener.close()
            for worker in self.workers:
                worker.join(3)
        if failures:
            raise AssertionError("integration transport cleanup failed") from failures[0]
        if any(worker.is_alive() for worker in self.workers):
            raise AssertionError("integration receiver/reconnector leaked")
        sender = self.transport.queue_thread
        if sender is not None and sender.is_alive():
            raise AssertionError("integration sender leaked")
        if not self.errors.empty():
            raise AssertionError("integration receiver raised") from self.errors.get()


class QueuedMainLoop:
    """Explicit idle dispatch for stale-generation integration scenarios."""

    def __init__(self):
        self.callbacks = queue.Queue()
        glib = types.SimpleNamespace(idle_add=self.idle_add)
        gi = types.ModuleType("gi")
        repository = types.ModuleType("gi.repository")
        repository.GLib = glib
        gi.repository = repository
        self.modules = {"gi": gi, "gi.repository": repository}

    def idle_add(self, callback):
        self.callbacks.put(callback)
        return 1

    def drain(self):
        while True:
            try:
                callback = self.callbacks.get_nowait()
            except queue.Empty:
                return
            callback()
