"""Regression tests for issues #137 and #138: relay stress harness shutdown.

The isolated relay fault-injection harness (relay_transport_stress.py) used to
cancel every asyncio task, including the task the loop thread was running, and
then stop the loop without awaiting any cancellation. The loop was left unclosed
with pending ``Env._proxy()`` / relay ``handle_client()`` tasks, which asyncio
reported as "Task was destroyed but it is pending!" and "_GatheringFuture
exception was never retrieved" at interpreter exit.

These tests need the exact pinned upstream checkouts (see
docs/testing/relay-transport-stress.md). They are skipped when the checkouts
are not configured, unless LRD_REQUIRE_PINNED=1 (set by the CI workflow), in
which case a missing checkout is a failure rather than a silent skip.
"""
import asyncio
import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STRESS = REPO / "tests" / "integration" / "relay_transport_stress.py"
PINNED_VARS = ("LRD_PINNED_ORCA_REMOTE", "LRD_PINNED_RELAY_FILE")

# Reports that mean the harness tore down its event loop incorrectly. Expected
# fault-injection output (relay "Error client N ... BrokenPipeError", asyncio
# "socket.send() raised exception", transport "dropped malformed line") is
# deliberately not listed here.
SHUTDOWN_NOISE = (
    "Task was destroyed but it is pending",
    "exception was never retrieved",
    "CancelledError",
    "ResourceWarning",
    "unclosed",
    "Event loop is closed",
    "Exception in callback",
    "Unhandled exception",
)


def setUpModule():
    missing = [name for name in PINNED_VARS if not os.environ.get(name)]
    if not missing:
        return
    if os.environ.get("LRD_REQUIRE_PINNED") == "1":
        raise RuntimeError(f"LRD_REQUIRE_PINNED=1 but {', '.join(missing)} is not set")
    raise unittest.SkipTest(f"pinned upstream checkouts not configured: {', '.join(missing)}")


def load_stress():
    spec = importlib.util.spec_from_file_location("lrd_relay_stress_under_test", STRESS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def open_fds():
    return len(os.listdir("/proc/self/fd"))


class ProxiedTlsClient:
    """A blocking TLS client joining the relay through the fault proxy, like Orca."""

    def __init__(self, port, channel):
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        self.sock = ctx.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=10))
        for obj in ({"type": "protocol_version", "version": 2},
                    {"type": "join", "channel": channel, "connection_type": "slave"}):
            self.sock.sendall((json.dumps(obj) + "\n").encode())

    def close(self):
        self.sock.close()


class EnvShutdownTests(unittest.TestCase):
    def test_close_finishes_every_task_and_releases_loop_thread_and_sockets(self):
        stress = load_stress()
        threads_before = set(threading.enumerate())
        fds_before = open_fds()
        channel = "shutdown-" + os.urandom(6).hex()

        env = stress.Env()
        peer = stress.Peer(env, channel)               # direct TLS peer on the relay
        client = ProxiedTlsClient(env.proxy_port, channel)   # proxied leg: Env._proxy()
        self.assertTrue(stress.wait_until(lambda: env.joins >= 2, 10), "both clients must join")
        self.assertEqual(len(env.conns), 1, "the proxied leg should exist before shutdown")

        peer.close()
        env.close()

        pending = sorted(task.get_coro().__qualname__ for task in asyncio.all_tasks(env.loop))
        self.assertEqual(pending, [], "tasks still pending after Env.close()")
        self.assertTrue(env.loop.is_closed(), "event loop was not closed by Env.close()")
        leaked_threads = [t.name for t in set(threading.enumerate()) - threads_before if t.is_alive()]
        self.assertEqual(leaked_threads, [], "threads alive after Env.close()")

        client.close()
        self.assertEqual(open_fds(), fds_before, "file descriptors leaked by the harness")

    def test_expected_fault_errors_are_classified_apart_from_unexpected_ones(self):
        stress = load_stress()
        for exc in (ConnectionResetError(104, "reset"), BrokenPipeError(32, "pipe"),
                    ConnectionAbortedError(103, "aborted")):
            self.assertTrue(stress.is_expected_fault_error(exc), repr(exc))
        for exc in (RuntimeError("boom"), ValueError("x"), AttributeError("y"),
                    asyncio.CancelledError(), OSError(9, "bad fd")):
            self.assertFalse(stress.is_expected_fault_error(exc), repr(exc))

    def test_close_reports_unexpected_errors_and_ignores_expected_ones(self):
        stress = load_stress()
        env = stress.Env()
        env.call(env.record_fault_error, "proxy", ConnectionResetError(104, "injected"))
        env.call(env.record_fault_error, "proxy", RuntimeError("not a socket fault"))
        report = env.close()
        self.assertEqual(report["expected_fault_errors"], {"ConnectionResetError": 1})
        self.assertEqual(len(report["problems"]), 1, report)
        self.assertIn("RuntimeError", report["problems"][0])


class ScenarioShutdownTests(unittest.TestCase):
    """Run each real scenario in a fresh interpreter and inspect the shutdown output.

    A subprocess is required: asyncio reports destroyed-pending tasks and
    unretrieved exceptions when objects are garbage collected at interpreter exit.
    """

    SCENARIOS = (("sessions", "6"), ("teardown", "6"), ("halfopen", None),
                 ("partial", "3"), ("prejoin", "4"))

    def run_scenario(self, name, cycles):
        cmd = [sys.executable, "-X", "dev", "-X", "faulthandler", str(STRESS), name]
        if cycles:
            cmd += ["--cycles", cycles]
        done = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300,
                              env={**os.environ, "PYTHONPATH": str(REPO)})
        return done, done.stdout + done.stderr

    def test_scenarios_exit_without_asyncio_shutdown_noise(self):
        for name, cycles in self.SCENARIOS:
            with self.subTest(scenario=name):
                done, output = self.run_scenario(name, cycles)
                self.assertEqual(done.returncode, 0, output[-3000:])
                noise = [line for line in output.splitlines()
                         if any(marker in line for marker in SHUTDOWN_NOISE)]
                self.assertEqual(noise, [], "asyncio shutdown noise in scenario output")

    def test_scenario_result_reports_a_clean_shutdown(self):
        for name, cycles in self.SCENARIOS:
            with self.subTest(scenario=name):
                done, output = self.run_scenario(name, cycles)
                result_lines = [l for l in output.splitlines() if l.startswith("RESULT ")]
                self.assertEqual(len(result_lines), 1, output[-3000:])
                result = json.loads(result_lines[0].split(" ", 4)[4])
                shutdown = result.get("shutdown")
                self.assertIsNotNone(shutdown, "RESULT must include the harness shutdown report")
                self.assertEqual(shutdown["pending_tasks"], [])
                self.assertTrue(shutdown["loop_closed"])
                self.assertTrue(shutdown["thread_joined"])
                self.assertEqual(shutdown["problems"], [])


if __name__ == "__main__":
    unittest.main()
