"""Reconnect/handoff lifecycle invariants for the injected remote-input shim.

Hand-written regressions cover one interleaving each. These tests complement
them with fixed-seed random interleavings of remote key events, control
handoff, transport disconnect/reconnect (including a role change), departure
of the controlling client, queued Orca main-loop work, and injected key
press/release failures. After every sequence an independent oracle checks:

* no Linux key is left held once a final teardown has run with a working
  backend (a failed release stays owned and is retried by a later reset), and
* no queued Orca operation runs after the session it was scheduled in ended.

Seeds are fixed so any failure reproduces exactly. The assertion message
carries the complete event trace of the first failing seed.
"""
from __future__ import annotations

import random
import unittest

from tests.test_compat_lifecycle import Harness

# (virtual key, extended) pairs: letters, every modifier family, both NVDA
# modifier keys (Insert is deferred, CapsLock is a toggle), arrows, function
# keys, numpad and lock keys.
KEYS = [
    (0x41, False), (0x42, False), (0xA0, False), (0xA2, False), (0xA4, False),
    (0x5B, True), (0x2D, True), (0x2D, False), (0x14, False), (0x25, True),
    (0x28, True), (0x70, False), (0x7B, False), (0x0D, False), (0x20, False),
    (0x90, False), (0x61, False),
]
SEEDS = range(60)
STEPS = 50


class LifecycleHarness(Harness):
    def _lifecycle_source(self):
        # The shared upstream fixture has no transport lifecycle callbacks;
        # the shim only wraps the ones that exist.
        return self.UPSTREAM_CONTROLLER.replace(
            "    def _on_remote_sas(",
            "    def _on_transport_connected(self, *a, **k):\n"
            "        pass\n\n"
            "    def _on_transport_disconnected(self, *a, **k):\n"
            "        pass\n\n"
            "    def _on_remote_sas(",
        )

    def _lifecycle_controller(self):
        controller, _, _ = self._patched_controller(
            source=self._lifecycle_source(), inline=False)
        controller.connected_clients = {1: {"connection_type": "master"}}
        return controller

    @staticmethod
    def _reconnect(controller, transport):
        controller._on_transport_disconnected()
        controller.transport = transport
        controller._on_transport_connected()

    @staticmethod
    def _key_log(controller):
        return [event[:3] for event in controller.local_machine.events
                if event[0] == "key"]


class TargetedLifecycleTests(LifecycleHarness, unittest.TestCase):
    def test_speech_stop_queued_before_reconnect_is_skipped(self):
        c = self._lifecycle_controller()
        queue, patches = self._fake_glib()
        with patches:
            c._linux_rdaccess_stop_local_speech()
            self._reconnect(c, self.FakeTransport())
            for callback in list(queue):
                callback()
        self.assertEqual(c.local_machine.events, [])

    def test_deferred_insert_release_after_reconnect_is_not_forwarded(self):
        c = self._lifecycle_controller()
        c._linux_rdaccess_run_main = lambda func, **kw: func()
        self._key(c, 0x2D, True, extended=True)
        self._reconnect(c, self.FakeTransport())
        self._key(c, 0x2D, False, extended=True)
        self.assertEqual(self._key_log(c), [])

    def test_deferred_capslock_release_after_reconnect_is_not_forwarded(self):
        c = self._lifecycle_controller()
        c._linux_rdaccess_run_main = lambda func, **kw: func()
        self._key(c, 0x14, True)
        self._reconnect(c, self.FakeTransport())
        self._key(c, 0x14, False)
        self.assertEqual(self._key_log(c), [])

    def test_master_departure_releases_every_held_key_once(self):
        c = self._lifecycle_controller()
        c._linux_rdaccess_run_main = lambda func, **kw: func()
        self._key(c, 0xA2, True)
        self._key(c, 0x41, True)
        c._on_client_left(client={"id": 1, "connection_type": "master"})
        released = sorted(
            vk for _tag, vk, pressed in self._key_log(c) if not pressed)
        self.assertEqual(released, [0x41, 0xA2])
        # A late key-up from the departed client must not be injected again.
        self._key(c, 0x41, False)
        self._key(c, 0xA2, False)
        released = sorted(
            vk for _tag, vk, pressed in self._key_log(c) if not pressed)
        self.assertEqual(released, [0x41, 0xA2])

    def test_role_changing_reconnect_expires_queued_orca_work(self):
        c = self._lifecycle_controller()
        queue, patches = self._fake_glib()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with patches:
            self._key(c, 0x2D, True)
            self._key(c, 0x54, True)
            self._reconnect(c, self.FakeTransport(connection_type="master"))
            for callback in list(queue):
                callback()
        self.assertEqual(calls, [])


class RandomisedLifecycleInvariantTests(LifecycleHarness, unittest.TestCase):
    _results = {}

    def run_sequence(self, seed):
        # Both invariants check the same sequences; run each seed once.
        cache = type(self)._results
        if seed not in cache:
            cache[seed] = self._run_sequence(seed)
        return cache[seed]

    def _run_sequence(self, seed):
        rnd = random.Random(seed)
        c = self._lifecycle_controller()
        queue, patches = self._fake_glib()
        trace = []
        down = set()
        failure_rate = {"press": 0.0, "release": 0.0}
        session = [0]  # oracle: bumped by every real session change
        ran = []

        controller_class = type(c)
        schedule = controller_class._linux_rdaccess_run_main

        def tagged_schedule(owner, func, **kwargs):
            scheduled_in = session[0]

            def invoke():
                ran.append((scheduled_in, session[0]))
                return func()

            return schedule(owner, invoke, **kwargs)

        controller_class._linux_rdaccess_run_main = tagged_schedule
        c._linux_rdaccess_script_call = lambda *args, **kw: trace.append(
            ("script", args[:1]))

        class Backend:
            def cancel_speech(self):
                trace.append("cancel_speech")

            def send_key(self, **kw):
                vk, pressed = kw.get("vk_code"), bool(kw["pressed"])
                kind = "press" if pressed else "release"
                if rnd.random() < failure_rate[kind]:
                    trace.append(("injection-failed", kind, vk))
                    if rnd.random() < 0.5:
                        raise OSError("injection failed")
                    return False
                if pressed:
                    down.add(vk)
                else:
                    down.discard(vk)
                trace.append((kind, vk))

        c.local_machine = Backend()
        held = set()

        def end_of_session():
            session[0] += 1
            held.clear()

        with patches:
            for _ in range(STEPS):
                failure_rate["press"] = rnd.choice([0, 0, 0, 0.3])
                failure_rate["release"] = rnd.choice([0, 0, 0, 0.3])
                roll = rnd.random()
                if roll < 0.55:
                    key = rnd.choice(KEYS)
                    if key in held and rnd.random() < 0.7:
                        held.discard(key)
                        pressed = False
                    else:
                        held.add(key)
                        pressed = True
                    trace.append(("remote", key[0], pressed))
                    self._key(c, key[0], pressed, extended=key[1])
                elif roll < 0.65:
                    trace.append("toggle_control")
                    c.toggle_control()
                    end_of_session()
                elif roll < 0.73:
                    trace.append("reconnect")
                    self._reconnect(c, self.FakeTransport())
                    end_of_session()
                elif roll < 0.78:
                    trace.append("master_left")
                    c._on_client_left(
                        client={"id": 1, "connection_type": "master"})
                    end_of_session()
                elif roll < 0.90:
                    trace.append("run_queued_work")
                    for callback in list(queue):
                        queue.remove(callback)
                        callback()
                else:
                    trace.append("role_changing_reconnect")
                    self._reconnect(c, self.FakeTransport(
                        connection_type=rnd.choice(["master", "slave"])))
                    end_of_session()
            # Final teardown with a healthy backend: failed releases that
            # stayed owned must now be retried and succeed.
            failure_rate["press"] = failure_rate["release"] = 0
            self._reconnect(c, self.FakeTransport())
            for callback in list(queue):
                queue.remove(callback)
                callback()
        stale = [pair for pair in ran if pair[0] != pair[1]]
        return down, stale, trace

    def _first_failure(self, selector):
        for seed in SEEDS:
            down, stale, trace = self.run_sequence(seed)
            problem = selector(down, stale)
            if problem:
                return seed, problem, trace
        return None

    def test_no_key_stays_down_after_teardown(self):
        failure = self._first_failure(lambda down, stale: sorted(down))
        if failure:
            seed, problem, trace = failure
            self.fail("seed %d left Linux keys held: %s\nFull trace:\n%s" % (
                seed, [hex(vk) for vk in problem],
                "\n".join(map(str, trace))))

    def test_queued_orca_work_never_runs_after_its_session_ended(self):
        failure = self._first_failure(lambda down, stale: stale)
        if failure:
            seed, problem, trace = failure
            self.fail(
                "seed %d ran queued work from an earlier session "
                "(scheduled-in, running-in): %s\nFull trace:\n%s" % (
                    seed, problem[:5], "\n".join(map(str, trace))))


if __name__ == "__main__":
    unittest.main()
