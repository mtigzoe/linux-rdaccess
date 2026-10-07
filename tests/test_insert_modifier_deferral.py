"""Insert-as-NVDA must not leak into Linux for consumed commands."""
from __future__ import annotations

import unittest

from tests.test_compat_lifecycle import Harness


class InsertModifierDeferralTests(Harness, unittest.TestCase):
    def test_consumed_nvda_command_never_injects_insert(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x4E, True)   # NVDA+N: intentionally unsupported remotely
        self._key(c, 0x4E, False)
        self._key(c, 0x2D, False, extended=True)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertNotIn(("key", 0x2D, True), keys)
        self.assertNotIn(("key", 0x2D, False), keys)
        self.assertNotIn(("key", 0x4E, True), keys)

    def test_pass_next_does_not_replay_used_nvda_modifier(self):
        for modifier, extended in ((0x2D, True), (0x14, False)):
            with self.subTest(modifier=hex(modifier)):
                c, _, _ = self._patched_controller()
                # Leave Orca activation queued; receive-side pass-next must
                # still forward exactly one following key.
                c._linux_rdaccess_run_main = lambda callback: True
                self._key(c, modifier, True, extended=extended)
                self._key(c, 0x71, True)   # NVDA+F2
                self._key(c, 0x71, False)
                self._key(c, 0x20, True)
                self._key(c, 0x20, False)
                self._key(c, modifier, False, extended=extended)
                keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
                self.assertFalse(any(k[1] == modifier for k in keys))
                self.assertIn(("key", 0x20, True), keys)
                self.assertIn(("key", 0x20, False), keys)

    def test_failed_deferred_insert_blocks_remainder_of_chord(self):
        for failure in (False, OSError("backend unavailable")):
            with self.subTest(failure=type(failure).__name__):
                c, _, _ = self._patched_controller()
                attempts = []

                def send(**kw):
                    attempts.append((kw["vk_code"], kw["pressed"]))
                    if kw["vk_code"] == 0x2D and kw["pressed"]:
                        if isinstance(failure, Exception):
                            raise failure
                        return False
                    return True

                c.local_machine.send_key = send
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0x59, True)   # Insert+Y, modifier replay fails
                self._key(c, 0x59, False)
                self._key(c, 0x2D, False, extended=True)
                self.assertNotIn((0x59, True), attempts)
                self.assertNotIn((0x59, False), attempts)

                # Ownership is cleared after the failed chord; later plain
                # input must not remain suppressed.
                self._key(c, 0x41, True)
                self._key(c, 0x41, False)
                self.assertIn((0x41, True), attempts)
                self.assertIn((0x41, False), attempts)

    def test_failed_insert_replay_during_bypass_preserves_next_request(self):
        c, _, _ = self._patched_controller()
        attempts = []

        def send(**kw):
            attempts.append((kw["vk_code"], kw["pressed"]))
            if kw["vk_code"] == 0x2D and kw["pressed"]:
                return False
            return True

        c.local_machine.send_key = send
        self._key(c, 0x2D, True, extended=True)
        request = c._lrd_bypass_request = {
            "generation": c._lrd_generation,
            "used": False,
            "external": False,
            "codes": {},
        }
        c._lrd_bypass_next = True

        self._key(c, 0x59, True)   # Insert+Y: Insert replay fails
        self._key(c, 0x59, False)
        self.assertNotIn((0x59, True), attempts)
        self.assertFalse(request["used"])
        self.assertTrue(c._lrd_bypass_next)

        # The bypass remains available for the next complete gesture.
        self._key(c, 0x41, True)
        self._key(c, 0x41, False)
        self.assertIn((0x41, True), attempts)
        self.assertFalse(c._lrd_bypass_next)

    def test_v84_controller_patch_upgrades_to_v85(self):
        import remote_access
        c, path, _ = self._patched_controller()
        previous = path.read_text(encoding="utf-8").replace(
            remote_access.LEGACY_COMPAT_MARKER,
            remote_access.LEGACY_COMPAT_MARKER_V84,
        )
        path.write_text(previous, encoding="utf-8")
        self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
        result = path.read_text(encoding="utf-8")
        self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
        self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V84 + "\n", result)
        self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))

    def test_non_nvda_insert_chord_replays_modifier_before_application_key(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x59, True)   # Insert+Y is not an NVDA 2026.2 command
        self._key(c, 0x59, False)
        self._key(c, 0x2D, False, extended=True)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertEqual(keys, [
            ("key", 0x2D, True),
            ("key", 0x59, True),
            ("key", 0x59, False),
            ("key", 0x2D, False),
        ])

    def test_standalone_insert_still_replays_one_press_release(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x2D, False, extended=True)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertEqual(keys, [
            ("key", 0x2D, True),
            ("key", 0x2D, False),
        ])


if __name__ == "__main__":
    unittest.main()
