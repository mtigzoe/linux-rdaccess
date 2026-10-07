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
