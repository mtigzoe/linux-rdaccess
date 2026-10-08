"""NVDA's unqualified keypad object-navigation gestures work in both layouts.

NVDA 2026.2 binds NVDA+Numpad5, NVDA+NumpadMinus, NVDA+Shift+NumpadMinus,
NVDA+NumpadDivide, NVDA+NumpadMultiply and NVDA+NumpadEnter with plain
"kb:" gestures (laptop layout adds alternatives; it does not remove these).
Only identities NVDA's own vkCodes table makes unambiguous are intercepted;
non-extended navigation-cluster VKs are never guessed to be the keypad.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness

# (name, vk, extended, shift)
KEYPAD_OBJECT_GESTURES = (
    ('numpad5', 0x0C, False, False),
    ('numpadMinus', 0x6D, False, False),
    ('shift+numpadMinus', 0x6D, False, True),
    ('numpadDivide', 0x6F, True, False),
    ('numpadMultiply', 0x6A, False, False),
    ('numpadEnter', 0x0D, True, False),
)


class KeypadObjectGestureTests(Harness, unittest.TestCase):
    def run_gesture(self, layout, vk, extended, shift):
        with mock.patch.dict(os.environ, {'LINUX_RDACCESS_NVDA_LAYOUT': layout}):
            c, _, _ = self._patched_controller()
            calls = []
            c._linux_rdaccess_script_call = lambda method, *a: calls.append(method)
            self._key(c, 0x2D, True, extended=True)
            if shift:
                self._key(c, 0xA0, True)
            before = list(c.local_machine.events)
            self._key(c, vk, True, extended=extended)
            self._key(c, vk, True, extended=extended)      # autorepeat
            self._key(c, vk, False, extended=extended)
            leaked = [e for e in c.local_machine.events[len(before):] if e[0] == 'key' and e[1] == vk]
            return leaked, calls

    def test_exact_keypad_object_gestures_are_consumed_in_both_layouts(self):
        for layout in ('desktop', 'laptop'):
            for name, vk, extended, shift in KEYPAD_OBJECT_GESTURES:
                with self.subTest(layout=layout, gesture=name):
                    leaked, calls = self.run_gesture(layout, vk, extended, shift)
                    self.assertEqual(leaked, [], 'keypad gesture reached Orca')
                    self.assertEqual(calls, [])

    def test_laptop_layout_keeps_its_own_alternatives_and_plain_keys(self):
        # NVDA+Enter (laptop activate) is consumed; a plain keypad key is not.
        leaked, _ = self.run_gesture('laptop', 0x0D, False, False)
        self.assertEqual(leaked, [])
        with mock.patch.dict(os.environ, {'LINUX_RDACCESS_NVDA_LAYOUT': 'laptop'}):
            c, _, _ = self._patched_controller()
            self._key(c, 0x6D, True)
            self._key(c, 0x6D, False)
            self.assertEqual([e for e in c.local_machine.events if e[0] == 'key' and e[1] == 0x6D],
                             [('key', 0x6D, True, None), ('key', 0x6D, False, None)])

    def test_nonextended_navigation_vks_are_still_never_guessed_to_be_keypad(self):
        for layout in ('desktop', 'laptop'):
            for vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E):
                with self.subTest(layout=layout, vk=hex(vk)):
                    with mock.patch.dict(os.environ, {'LINUX_RDACCESS_NVDA_LAYOUT': layout}):
                        c, _, _ = self._patched_controller()
                        self._key(c, vk, True, extended=False)
                        self._key(c, vk, False, extended=False)
                        self.assertEqual(
                            [e for e in c.local_machine.events if e[0] == 'key' and e[1] == vk],
                            [('key', vk, True, None), ('key', vk, False, None)])


if __name__ == '__main__':
    unittest.main()
