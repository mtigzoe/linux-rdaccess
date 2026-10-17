"""Deterministic recovery edge cases for issue #61.

These are isolated, fake-transport tests. They do not establish live NVDA,
Orca process restart, or physical braille acceptance.
"""
from __future__ import annotations

import unittest

from linux_rdaccess_core.connection import remote_access

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

    def test_v120_and_v121_controller_upgrades_preserve_original_backup(self):
        """A new controller helper must replace installed old versions safely."""
        controller, path, _ = self._patched_controller()
        current = path.read_text(encoding="utf-8")
        backup = path.with_name(path.name + ".linux-rdaccess-backup")
        for previous in (remote_access.LEGACY_COMPAT_MARKER_V120,
                         remote_access.LEGACY_COMPAT_MARKER_V121):
            with self.subTest(previous=previous):
                path.write_text(
                    current.replace(remote_access.LEGACY_COMPAT_MARKER, previous),
                    encoding="utf-8",
                )
                self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
                self.assertEqual(path.read_text(encoding="utf-8"), current)
                self.assertEqual(backup.read_text(encoding="utf-8"),
                                 self.UPSTREAM_CONTROLLER)
                self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))

    def test_queued_command_expires_while_handoff_release_is_blocked(self):
        """An in-flight reset must expire queued work before slow key cleanup."""
        import threading

        controller = self._lifecycle_controller()
        queue, patches = self._fake_glib()
        calls = []
        entered, resume = threading.Event(), threading.Event()
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)

        with patches:
            # Keep an ordinary key physically held; also queue NVDA+T.
            self._key(controller, 0x41, True)
            self._key(controller, 0x2D, True)
            self._key(controller, 0x54, True)
            self.assertTrue(queue)

            original_send = controller.local_machine.send_key

            def blocking_release(**kwargs):
                if kwargs["vk_code"] == 0x41 and not kwargs["pressed"]:
                    entered.set()
                    if not resume.wait(5):
                        raise AssertionError("held-key release was never resumed")
                return original_send(**kwargs)

            controller.local_machine.send_key = blocking_release
            handoff = threading.Thread(target=controller.toggle_control)
            handoff.start()
            try:
                self.assertTrue(entered.wait(2), "handoff never reached key release")
                # The input thread has started reset, but original
                # toggle_control has not yet changed control_state. Dispatch
                # the earlier Orca idle jobs concurrently with key cleanup.
                for callback in list(queue):
                    callback()
            finally:
                resume.set()
                handoff.join(2)

        self.assertFalse(handoff.is_alive())
        self.assertNotIn(("presentTitle",), calls,
                         "old NVDA+T ran after handoff teardown had begun")

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
