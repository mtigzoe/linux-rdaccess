"""Fault-injection stress for the patched pinned Orca Remote transport (issue #123).

Runs on 127.0.0.1 only: the genuine pinned NVDA Remote relay (server.py), the
pinned Orca Remote transport.py with the PRODUCTION patch applied, and a TCP
proxy that cuts, resets, fragments or blackholes the link. It never starts Orca,
touches a desktop, or contacts a real relay. Channel keys are random.

Scenarios (each prints one RESULT line and exits non-zero on failure):
  sessions   repeated sessions torn down by close()/cut/RST/mid-record cut; every
             session must join at the relay and exchange tagged frames in order,
             with no frames crossing sessions and no thread/fd growth.
  teardown   heavy bidirectional traffic torn down at a random instant; close()
             must return, no uncaught thread exceptions, no crash, clean reconnect.
  halfopen   peer stops reading while the sender is wedged; close() must return.
  partial    a >16 KiB line is cut mid-frame; the next session must start clean.
  prejoin    a producer thread sends continuously across reconnects; the relay
             must never receive an application frame before that connection's join.

LRD_UNPATCHED=1 runs the same scenarios against the unpatched pinned transport
(an informational control showing the scenarios can detect the old defect class).
"""
import argparse
import asyncio
import collections
import gc
import importlib.util
import json
import os
import random
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from linux_rdaccess_core.connection import remote_access  # noqa: E402

ORCA_SCRIPTS = Path(os.environ["LRD_PINNED_ORCA_REMOTE"]) / "orca-scripts"
RELAY_FILE = Path(os.environ["LRD_PINNED_RELAY_FILE"])
UNPATCHED = bool(os.environ.get("LRD_UNPATCHED"))
SIZES = [8, 120, 900, 4000, 16360, 16384, 16385, 32768, 60000]
_LIVE_ENVS = []                               # closed by main() even when a scenario raises


def is_expected_fault_error(exc):
    """True for the socket errors the injected cut/RST/stall faults are meant to cause.

    ConnectionResetError, BrokenPipeError and ConnectionAbortedError are what a peer sees
    when the proxy drops or resets a connection. Anything else raised on the harness's own
    asyncio side (a RuntimeError, an unexpected OSError, a cancelled-but-unfinished
    future...) is a harness defect and is reported rather than swallowed.
    """
    return isinstance(exc, ConnectionError)


def stats():
    with open("/proc/self/status") as fh:
        status = dict(line.split(":", 1) for line in fh if ":" in line)
    return {"rss_kb": int(status["VmRSS"].split()[0]),
            "threads": int(status["Threads"]), "fds": len(os.listdir("/proc/self/fd")),
            "cpu_s": round(time.process_time(), 2)}


def wait_until(predicate, timeout, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


def load_transport():
    for name in ("callback_manager", "serializer"):
        spec = importlib.util.spec_from_file_location(name, ORCA_SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    source = (ORCA_SCRIPTS / "transport.py").read_text()
    if not UNPATCHED:
        source = remote_access._patch_legacy_transport_cleanup(source)
    namespace = {"__name__": "lrd_stress_transport"}
    exec(compile(source, "pinned-transport", "exec"), namespace)
    return namespace, sys.modules["serializer"].JSONSerializer()


class Conn:
    """One proxied TCP connection with fault knobs (loop-thread access only)."""

    def __init__(self):
        self.c2s = self.s2c = 0
        self.pause_c2s = False
        self.cut_after_s2c = None
        self.chunk_s2c = 65536
        self.closed = False
        self.cw = self.rw = None

    def cut(self):
        self.closed = True
        for writer in (self.cw, self.rw):
            try:
                writer.close()
            except Exception:
                pass

    def reset(self):
        self.closed = True
        try:
            self.cw.get_extra_info("socket").setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except OSError:
            pass
        self.cut()


class Env:
    """Genuine relay + fault proxy on a private event loop thread."""

    SHUTDOWN_GRACE_S = 10      # bound on tasks finishing by themselves once transports close
    THREAD_JOIN_S = 60

    def __init__(self):
        spec = importlib.util.spec_from_file_location("lrd_stress_relay", RELAY_FILE)
        self.relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.relay)
        self.joins = 0
        self.frames = []                      # (client_id, type, session)
        original, env = self.relay.Client.process_message, self

        async def observed(client, line):     # read-only observation
            try:
                message = json.loads(line)
                if message.get("type") == "join":
                    env.joins += 1
                env.frames.append((client.id, message.get("type"), message.get("sess")))
            except (ValueError, TypeError, AttributeError):
                pass
            return await original(client, line)
        self.relay.Client.process_message = observed
        self.tmp = tempfile.TemporaryDirectory(prefix="lrd-stress-")
        cert, key = Path(self.tmp.name, "c.pem"), Path(self.tmp.name, "k.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True, timeout=30)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(cert), str(key))
        self.server = self.relay.AsyncServer(SimpleNamespace(
            max_msg_size=65536, tracebacks=True, motd="", motd_force=False))
        self.loop = asyncio.new_event_loop()
        self.loop.set_exception_handler(self._loop_exception)
        self.conns = []
        self.peer_writers = []                # Peer StreamWriters, closed by teardown
        self.fault_errors = collections.Counter()   # expected injected-fault errors, by type
        self.problems = []                    # unexpected errors; loop-thread writes only until joined
        self.forced_cancellations = []        # tasks that had to be cancelled at shutdown
        self._stop = None                     # asyncio.Event, created on the loop thread
        self._report = None
        ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, args=(ready,),
                                       name="lrd-stress-loop", daemon=True)
        self.thread.start()
        assert ready.wait(15), "relay did not start"
        assert not self.problems, self.problems
        _LIVE_ENVS.append(self)

    # ---- loop thread -------------------------------------------------------------
    def _serve(self, ready):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run(ready))
        except BaseException:                  # reported by close(), never swallowed
            self.problems.append("event loop thread failed:\n" + traceback.format_exc())
            ready.set()
        finally:
            self.loop.close()

    async def _run(self, ready):
        self._stop = asyncio.Event()
        servers = []
        try:
            relay = await asyncio.start_server(self.server.handle_client, "127.0.0.1", 0, ssl=self.ctx)
            servers.append(relay)
            self.relay_port = relay.sockets[0].getsockname()[1]
            proxy = await asyncio.start_server(self._proxy, "127.0.0.1", 0)
            servers.append(proxy)
            self.proxy_port = proxy.sockets[0].getsockname()[1]
            ready.set()
            await self._stop.wait()
        finally:
            await self._teardown(servers)

    def record_fault_error(self, where, exc):
        """Count an injected-fault error as expected; report anything else as a problem."""
        if is_expected_fault_error(exc):
            self.fault_errors[type(exc).__name__] += 1
        else:
            self.problems.append(f"{where}: unexpected {type(exc).__name__}: {exc}")

    def _loop_exception(self, loop, context):
        exc = context.get("exception")
        if exc is not None and is_expected_fault_error(exc):
            self.fault_errors[type(exc).__name__] += 1
            return
        self.problems.append(f"asyncio reported: {context.get('message')} {exc!r}")
        loop.default_exception_handler(context)

    async def _wait_closed(self, writer, where):
        try:
            await writer.wait_closed()
        except Exception as exc:
            self.record_fault_error(where, exc)

    async def _proxy(self, creader, cwriter):
        try:
            rreader, rwriter = await asyncio.open_connection("127.0.0.1", self.relay_port)
        except Exception as exc:
            self.record_fault_error("proxy connect to relay", exc)
            cwriter.close()
            await self._wait_closed(cwriter, "proxy client leg")
            return
        conn = Conn()
        conn.cw, conn.rw = cwriter, rwriter
        self.conns.append(conn)

        async def c2s():
            try:
                while not conn.closed:
                    while conn.pause_c2s and not conn.closed:
                        await asyncio.sleep(0.01)
                    data = await creader.read(65536)
                    if not data:
                        break
                    conn.c2s += len(data)
                    rwriter.write(data)
                    await rwriter.drain()
            except Exception as exc:
                self.record_fault_error("proxy client->relay", exc)
            finally:
                conn.cut()

        async def s2c():
            try:
                while not conn.closed:
                    data = await rreader.read(65536)
                    if not data:
                        break
                    if conn.cut_after_s2c is not None:
                        data = data[:max(conn.cut_after_s2c - conn.s2c, 0)]
                    for i in range(0, len(data), conn.chunk_s2c):
                        cwriter.write(data[i:i + conn.chunk_s2c])
                        await cwriter.drain()
                    conn.s2c += len(data)
                    if conn.cut_after_s2c is not None and conn.s2c >= conn.cut_after_s2c:
                        break
            except Exception as exc:
                self.record_fault_error("proxy relay->client", exc)
            finally:
                conn.cut()

        legs = [asyncio.ensure_future(c2s()), asyncio.ensure_future(s2c())]
        try:
            await asyncio.gather(*legs)
        finally:
            # Own the legs: whatever ended this handler (EOF, fault, shutdown cancellation),
            # both legs finish, their results are retrieved, and both transports are closed
            # before the handler task completes.
            conn.cut()
            for leg in legs:
                leg.cancel()
            await asyncio.gather(*legs, return_exceptions=True)
            await self._wait_closed(cwriter, "proxy client leg")
            await self._wait_closed(rwriter, "proxy relay leg")

    async def _teardown(self, servers):
        """Shut down like asyncio.run(): stop accepting, close transports, let tasks finish,
        cancel and AWAIT any survivors, retrieve their exceptions, then release the loop."""
        me = asyncio.current_task()
        for server in servers:
            server.close()                         # stop accepting new connections
        for conn in self.conns:
            conn.cut()                             # drop every proxied connection
        for writer in self.peer_writers:
            writer.close()
        snapshot = {t for t in asyncio.all_tasks() if t is not me}
        if snapshot:
            done, _ = await asyncio.wait(snapshot, timeout=self.SHUTDOWN_GRACE_S)
            for task in done:
                self._retrieve(task)
        for _ in range(3):                         # cancellation may itself spawn cleanup tasks
            survivors = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
            if not survivors:
                break
            self.forced_cancellations += [t.get_coro().__qualname__ for t in survivors]
            for task in survivors:
                task.cancel()
            await asyncio.gather(*survivors, return_exceptions=True)
            for task in survivors:
                self._retrieve(task)
        for server in servers:
            try:
                await asyncio.wait_for(server.wait_closed(), self.SHUTDOWN_GRACE_S)
            except Exception as exc:               # includes TimeoutError
                self.problems.append(f"server did not finish closing: {exc!r}")
        await self.loop.shutdown_asyncgens()
        await self.loop.shutdown_default_executor()
        gc.collect()                               # unreferenced finished tasks report here

    def _retrieve(self, task):
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.record_fault_error(f"task {task.get_coro().__qualname__}", exc)

    # ---- caller thread -----------------------------------------------------------
    def call(self, fn, *args):
        self.loop.call_soon_threadsafe(fn, *args)

    def close(self):
        """Stop relay and proxy, wait for the loop thread, and return the shutdown report.

        Idempotent. The report lists anything left over (pending tasks, an unclosed loop,
        a thread that did not end) and every unexpected error; callers must treat a
        non-empty ``problems`` as a scenario failure.
        """
        if self._report is not None:
            return self._report
        if self.thread.is_alive() and self._stop is not None:
            try:
                self.loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass                               # loop already closed: thread is ending
            self.thread.join(self.THREAD_JOIN_S)
        problems = list(self.problems)
        pending = sorted(t.get_coro().__qualname__ for t in asyncio.all_tasks(self.loop))
        joined, closed = not self.thread.is_alive(), self.loop.is_closed()
        if not joined:
            problems.append("event loop thread did not terminate")
        if not closed:
            problems.append("event loop was not closed")
        if pending:
            problems.append(f"tasks still pending after shutdown: {pending}")
        self._report = {"thread_joined": joined, "loop_closed": closed, "pending_tasks": pending,
                        "forced_cancellations": list(self.forced_cancellations),
                        "expected_fault_errors": dict(self.fault_errors), "problems": problems}
        if self in _LIVE_ENVS:
            _LIVE_ENVS.remove(self)
        self.tmp.cleanup()
        return self._report


class Peer:
    """Independent reference peer: asyncio TLS client (single-threaded TLS I/O)."""

    def __init__(self, env, channel):
        self.env, self.frames, self.cond = env, [], threading.Condition()
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE

        async def connect():
            reader, self.writer = await asyncio.open_connection("127.0.0.1", env.relay_port, ssl=ctx)
            env.peer_writers.append(self.writer)
            self.write({"type": "protocol_version", "version": 2})
            self.write({"type": "join", "channel": channel, "connection_type": "master"})
            asyncio.ensure_future(self.read(reader))
        asyncio.run_coroutine_threadsafe(connect(), env.loop).result(15)

    def write(self, obj):
        self.writer.write((json.dumps(obj) + "\n").encode())

    async def read(self, reader):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                message = json.loads(line)
                if "pad" in message:
                    message["padlen"] = len(message.pop("pad"))
                with self.cond:
                    if message.get("type") != "ping":
                        self.frames.append(message)
        except Exception as exc:
            with self.cond:
                self.frames.append({"type": "_peer_error", "error": repr(exc)})

    def send(self, obj):
        self.env.call(self.write, obj)

    def data(self):
        with self.cond:
            return [f for f in self.frames if f.get("type") == "lrd_data"]

    def joined(self):
        with self.cond:
            return sum(1 for f in self.frames if f.get("type") == "client_joined")

    def close(self):
        self.env.call(self.writer.close)


class Orca:
    """The pinned RelayTransport driven by its own connector thread, via the proxy."""

    def __init__(self, env, channel):
        namespace, serializer = load_transport()
        self.transport = namespace["RelayTransport"](
            serializer, ("127.0.0.1", env.proxy_port), channel=channel, connection_type="slave")
        self.transport.reconnector_thread.connect_delay = 0.05
        self.inbound = []
        self.transport.callback_manager.register_callback(
            "msg_lrd_data", lambda **e: self.inbound.append((e.get("sess"), e.get("seq"))))
        self.transport.reconnector_thread.start()

    def restart_connector(self):               # production reconnect() after close()
        self.transport.reconnector_thread.connect_delay = 0.05
        self.transport.reconnector_thread.start()


def pad(n):
    return "x" * n


def finish(env, problems, result):
    """Close the harness and fold its shutdown report into the scenario outcome."""
    report = env.close()
    result["shutdown"] = report
    problems.extend(f"harness shutdown: {p}" for p in report["problems"])
    return not problems, result


def scenario_sessions(cycles=120, seed=2):
    rnd, env, problems = random.Random(seed), Env(), []
    channel = "stress-" + os.urandom(8).hex()
    peer, orca = Peer(env, channel), Orca(env, channel)
    transport, modes = orca.transport, {"close": 0, "cut": 0, "rst": 0, "midrecord": 0}
    baseline = None
    for cycle in range(cycles):
        if not wait_until(lambda: peer.joined() >= cycle + 1, 15):
            problems.append(f"cycle {cycle}: join never reached the relay "
                            f"(connected={transport.connected} connects={transport.successful_connects})")
            break
        baseline = stats() if cycle == 3 else baseline
        conn, n = env.conns[-1], 20
        before, got = len(peer.data()), len(orca.inbound)
        sender = threading.Thread(target=lambda: [transport.send(
            "lrd_data", seq=i, sess=cycle, pad=pad(rnd.choice(SIZES[:7]))) for i in range(n)])
        sender.start()
        for i in range(n):
            peer.send({"type": "lrd_data", "seq": i, "sess": cycle, "pad": "b"})
        sender.join()
        if not wait_until(lambda: len(peer.data()) - before >= n, 10):
            problems.append(f"cycle {cycle}: Orca->peer frames missing ({len(peer.data()) - before}/{n})")
            break
        if not wait_until(lambda: len(orca.inbound) - got >= n, 10):
            problems.append(f"cycle {cycle}: peer->Orca frames missing ({len(orca.inbound) - got}/{n})")
            break
        mine = [(f["sess"], f["seq"]) for f in peer.data()[before:]]
        if mine != [(cycle, i) for i in range(n)]:
            problems.append(f"cycle {cycle}: wrong order/session at relay peer: {mine[:3]}")
            break
        if orca.inbound[got:got + n] != [(cycle, i) for i in range(n)]:
            problems.append(f"cycle {cycle}: wrong order/session at Orca: {orca.inbound[got:got + 3]}")
            break
        mode = rnd.choice(list(modes))
        modes[mode] += 1
        if mode == "close":
            transport.close()
            orca.restart_connector()
        elif mode == "cut":
            env.call(conn.cut)
        elif mode == "rst":
            env.call(conn.reset)
        else:
            conn.chunk_s2c = 7
            peer.send({"type": "lrd_data", "seq": 99, "sess": cycle, "pad": "y" * 3000})
            time.sleep(0.05)
            env.call(conn.cut)
        if not wait_until(lambda: transport.successful_connects >= cycle + 2, 15):
            problems.append(f"cycle {cycle}: no reconnect after {mode}")
            break
    time.sleep(0.5)
    final = stats()
    if baseline and final["threads"] > baseline["threads"] + 1:
        problems.append(f"thread growth {baseline['threads']} -> {final['threads']}")
    if baseline and final["fds"] > baseline["fds"] + 4:
        problems.append(f"fd growth {baseline['fds']} -> {final['fds']}")
    result = {"cycles": cycle + 1, "modes": modes, "connects": transport.successful_connects,
              "baseline": baseline, "final": final, "problems": problems}
    transport.close(); peer.close()
    return finish(env, problems, result)


def scenario_teardown(cycles=60, seed=5):
    rnd, env, problems, thread_errors = random.Random(seed), Env(), [], []
    hook = threading.excepthook
    threading.excepthook = lambda a: thread_errors.append(
        (a.thread.name if a.thread else "?", a.exc_type.__name__, str(a.exc_value)[:100]))
    channel = "stress-" + os.urandom(8).hex()
    peer, orca = Peer(env, channel), Orca(env, channel)
    transport, close_times, modes = orca.transport, [], {"close": 0, "cut": 0, "rst": 0}
    for cycle in range(cycles):
        if not wait_until(lambda: peer.joined() >= cycle + 1, 15):
            problems.append(f"cycle {cycle}: no join"); break
        conn, stop, mark = env.conns[-1], threading.Event(), len(orca.inbound)

        def a_producer():
            i = 0
            while not stop.is_set():
                transport.send("lrd_data", seq=i, sess=cycle, pad=pad(rnd.choice(SIZES)))
                i += 1
                if i % 8 == 0:
                    time.sleep(0.0005)

        def b_producer():
            i = 0
            while not stop.is_set():
                if i - (len(orca.inbound) - mark) > 30:
                    time.sleep(0.002); continue
                peer.send({"type": "lrd_data", "seq": i, "sess": cycle, "pad": pad(rnd.choice(SIZES))})
                i += 1
                time.sleep(0.0007)
        threads = [threading.Thread(target=a_producer), threading.Thread(target=b_producer)]
        for t in threads:
            t.start()
        time.sleep(rnd.uniform(0.02, 0.35))
        mode = rnd.choice(list(modes))
        modes[mode] += 1
        if mode == "close":
            started, done = time.monotonic(), threading.Event()
            closer = threading.Thread(target=lambda: (transport.close(), done.set()), daemon=True)
            closer.start()
            if not done.wait(20):
                problems.append(f"cycle {cycle}: close() hung under load"); stop.set(); break
            close_times.append(time.monotonic() - started)
            stop.set()
            orca.restart_connector()
        else:
            env.call(conn.cut if mode == "cut" else conn.reset)
            stop.set()
        for t in threads:
            t.join()
        if not wait_until(lambda: transport.successful_connects >= cycle + 2, 15):
            problems.append(f"cycle {cycle}: no reconnect after {mode}"); break
    time.sleep(1)
    sessions_by_origin = {}
    for frame in peer.data():
        sessions_by_origin.setdefault(frame.get("origin"), set()).add(frame["sess"])
    mixed = {o: s for o, s in sessions_by_origin.items() if len(s) > 1}
    if mixed:
        problems.append(f"one relay connection carried several sessions: {mixed}")
    if thread_errors:
        problems.append(f"uncaught thread exceptions: {thread_errors[:5]}")
    result = {"cycles": cycle + 1, "modes": modes, "connects": transport.successful_connects,
              "close_s_max": round(max(close_times), 3) if close_times else None,
              "thread_exceptions": len(thread_errors), "stats": stats(), "problems": problems}
    threading.excepthook = hook
    transport.close(); peer.close()
    return finish(env, problems, result)


def scenario_halfopen():
    env = Env()
    channel = "stress-" + os.urandom(8).hex()
    peer, orca = Peer(env, channel), Orca(env, channel)
    transport, problems = orca.transport, []
    assert wait_until(lambda: peer.joined() >= 1, 15), "no join"
    conn, stop = env.conns[-1], threading.Event()
    conn.pause_c2s = True                       # the proxy stops reading Orca's socket

    def flood():
        i = 0
        while not stop.is_set():
            transport.send("lrd_data", seq=i, sess=0, pad=pad(60000))
            i += 1
            time.sleep(0.001)
    flooder = threading.Thread(target=flood, daemon=True)
    flooder.start()
    time.sleep(3)
    queued = transport.queue.qsize()
    time.sleep(1)
    wedged = transport.queue.qsize() > queued
    stop.set(); flooder.join()
    sender, done = transport.queue_thread, threading.Event()
    started = time.monotonic()
    threading.Thread(target=lambda: (transport.close(), done.set()), daemon=True).start()
    returned = done.wait(20)
    if not wedged:
        problems.append("harness did not wedge the sender (no backpressure)")
    if not returned:
        problems.append("close() hung while the sender was blocked in sendall")
    elif sender is not None and not wait_until(lambda: not sender.is_alive(), 5):
        problems.append("sender thread still alive after close()")
    connector_gone = wait_until(lambda: not [t for t in threading.enumerate()
                                             if t.name.endswith("_connector_loop") and t.is_alive()], 10)
    if returned and not connector_gone:
        problems.append("connector thread still alive after close()")
    result = {"sender_wedged": wedged, "close_returned": returned,
              "close_s": round(time.monotonic() - started, 2), "problems": problems}
    conn.pause_c2s = False
    peer.close()
    return finish(env, problems, result)


def scenario_partial(cycles=30, seed=6):
    rnd, env, problems = random.Random(seed), Env(), []
    channel = "stress-" + os.urandom(8).hex()
    peer, orca = Peer(env, channel), Orca(env, channel)
    transport = orca.transport
    for cycle in range(cycles):
        if not wait_until(lambda: peer.joined() >= cycle + 1, 15):
            problems.append(f"cycle {cycle}: no join"); break
        conn, mark = env.conns[-1], len(orca.inbound)
        for i in range(10):
            peer.send({"type": "lrd_data", "seq": i, "sess": cycle, "pad": "ok"})
        if not wait_until(lambda: len(orca.inbound) - mark >= 10, 10) \
                or orca.inbound[mark:mark + 10] != [(cycle, i) for i in range(10)]:
            problems.append(f"cycle {cycle}: first frames of the new session corrupted or missing: "
                            f"{orca.inbound[mark:mark + 3]} buffer={len(transport.buffer)}B")
            break
        env.call(setattr, conn, "cut_after_s2c", conn.s2c + rnd.randint(17000, 33000))
        time.sleep(0.05)
        peer.send({"type": "lrd_data", "seq": 1000, "sess": cycle, "pad": "z" * 50000})
        if not wait_until(lambda: transport.successful_connects >= cycle + 2, 15):
            problems.append(f"cycle {cycle}: no reconnect after cutting inside a 50 KB frame"); break
    result = {"cycles": cycle + 1, "problems": problems, "stats": stats()}
    transport.close(); peer.close()
    return finish(env, problems, result)


def scenario_prejoin(cycles=60):
    env, problems = Env(), []
    channel = "stress-" + os.urandom(8).hex()
    orca = Orca(env, channel)                  # no peer: a flooded peer is dropped by the relay
    transport, stop, sent = orca.transport, threading.Event(), [0]

    def producer():
        while not stop.is_set():
            transport.send("lrd_data", seq=sent[0], sess=0, pad="p")
            sent[0] += 1
            time.sleep(0)
    threading.Thread(target=producer, daemon=True).start()
    for cycle in range(cycles):
        if not wait_until(lambda: env.joins >= cycle + 1, 15):
            problems.append(f"cycle {cycle}: no join at relay"); break
        time.sleep(0.02)
        env.call(env.conns[-1].cut)
        if not wait_until(lambda: transport.successful_connects >= cycle + 2, 15):
            problems.append(f"cycle {cycle}: no reconnect"); break
    stop.set()
    order = {}
    for client, kind, _session in list(env.frames):
        order.setdefault(client, []).append(kind)
    early = {c: k[:3] for c, k in order.items()
             if "join" in k and [x for x in k[:k.index("join")] if x != "protocol_version"]}
    if early:
        problems.append(f"application frames reached the relay before join: {dict(list(early.items())[:3])}")
    result = {"cycles": cycle + 1, "relay_connections": len(order), "frames_sent": sent[0],
              "problems": problems, "stats": stats()}
    transport.close()
    return finish(env, problems, result)


SCENARIOS = {"sessions": scenario_sessions, "teardown": scenario_teardown,
             "halfopen": scenario_halfopen, "partial": scenario_partial,
             "prejoin": scenario_prejoin}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--cycles", type=int)
    args = parser.parse_args()
    kwargs = {"cycles": args.cycles} if args.cycles else {}
    try:
        ok, result = SCENARIOS[args.scenario](**kwargs)
    finally:
        for leftover in list(_LIVE_ENVS):    # a scenario that raised must not leak its loop
            leftover.close()
    print("RESULT", args.scenario, "PASS" if ok else "FAIL",
          "patched" if not UNPATCHED else "UNPATCHED-control", json.dumps(result, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
