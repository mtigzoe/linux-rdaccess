"""Issue #61: actual socket EOF with simulated controller notification.

This exercises real local socket teardown, but the controller's disconnect
callback is invoked explicitly. It does not exercise the production
NVDA Remote relay or an Orca/NVDA installation.
"""
from __future__ import annotations

import socket
import unittest

from tests.unit.input.test_lifecycle_invariants import LifecycleHarness


class SocketLifecycleTests(LifecycleHarness, unittest.TestCase):
    def test_eof_releases_modifier_and_expires_queued_speech(self):
        c = self._lifecycle_controller()
        c._linux_rdaccess_run_main = lambda func, **kw: func()
        self._key(c, 0xA2, True)
        # Restore the queueing scheduler after the synchronous key-down.
        del c._linux_rdaccess_run_main
        queued, patches = self._fake_glib()
        with patches, socket.socketpair() as (receiver, sender):
            receiver.settimeout(2)
            c._linux_rdaccess_stop_local_speech()
            sender.shutdown(socket.SHUT_WR)
            self.assertEqual(receiver.recv(1), b"", "expected real socket EOF")
            # The fake upstream transport does not implement a real socket
            # receiver; explicitly bridge the observed EOF to its callback.
            c._on_transport_disconnected()
            while queued:
                queued.pop(0)()
        events = [(vk, pressed) for _, vk, pressed in self._key_log(c)]
        self.assertEqual(events, [(0xA2, True), (0xA2, False)])
        self.assertEqual(
            [event for event in c.local_machine.events
             if event[0] != "key"], [])

    def test_new_socket_after_eof_accepts_fresh_input(self):
        c = self._lifecycle_controller()
        c._linux_rdaccess_run_main = lambda func, **kw: func()
        with socket.socketpair() as (receiver, sender):
            receiver.settimeout(2)
            self._key(c, 0xA2, True)
            sender.shutdown(socket.SHUT_WR)
            self.assertEqual(receiver.recv(1), b"")
            c._on_transport_disconnected()

        with socket.socketpair() as (receiver, sender):
            receiver.settimeout(2)
            c.transport = self.FakeTransport()
            c._on_transport_connected()
            sender.sendall(b"F")
            self.assertEqual(receiver.recv(1), b"F")
            # Newly connected fake controller should still inject keys.
            self._key(c, 0x41, True)
            self._key(c, 0x41, False)

        self.assertEqual(
            [(vk, down) for _, vk, down in self._key_log(c)],
            [(0xA2, True), (0xA2, False),
             (0x41, True), (0x41, False)],
        )


if __name__ == "__main__":
    unittest.main()
