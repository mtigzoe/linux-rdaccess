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
