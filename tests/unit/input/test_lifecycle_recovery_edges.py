"""Deterministic recovery edge cases for issue #61.

These are isolated, fake-transport tests. They do not establish live NVDA,
Orca process restart, or physical braille acceptance.
"""
from __future__ import annotations

import unittest

from tests.unit.input.test_lifecycle_invariants import LifecycleHarness


class RecoveryEdgeCaseTests(LifecycleHarness, unittest.TestCase):
    def test_queued_stop_expires_across_two_reconnections(self):
        controller = self._lifecycle_controller()
        queue, patches = self._fake_glib()
        with patches:
            controller._linux_rdaccess_stop_local_speech()
            self._reconnect(controller, self.FakeTransport())
            self._reconnect(controller, self.FakeTransport())
            while queue:
                queue.pop(0)()
        self.assertEqual(controller.local_machine.events, [])

    def test_repeated_disconnect_releases_held_modifier_once(self):
        controller = self._lifecycle_controller()
        controller._linux_rdaccess_run_main = lambda func, **kwargs: func()
        self._key(controller, 0xA2, True)  # Left Ctrl
        controller._on_transport_disconnected()
        controller._on_transport_disconnected()
        events = [event for event in self._key_log(controller)
                  if event[1] == 0xA2]
        self.assertEqual([pressed for _, _, pressed in events],
                         [True, False])

    def test_old_key_up_after_reconnect_does_not_release_new_press(self):
        controller = self._lifecycle_controller()
        controller._linux_rdaccess_run_main = lambda func, **kwargs: func()
        self._key(controller, 0xA2, True)  # Key-down in first session
        self._reconnect(controller, self.FakeTransport())
        self._key(controller, 0xA2, False)  # Late old-session key-up
        self._key(controller, 0xA2, True)  # Fresh session key-down
        self._key(controller, 0xA2, False)  # Fresh session key-up
        events = [event for event in self._key_log(controller)
                  if event[1] == 0xA2]
        self.assertEqual([pressed for _, _, pressed in events],
                         [True, False, True, False])


if __name__ == "__main__":
    unittest.main()
