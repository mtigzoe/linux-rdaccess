"""Elements List keyboard fallback must preserve remotely held Linux keys."""

import sys
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class StructuralListOwnershipTests(Harness, unittest.TestCase):
    def fallback(self, controller, key="m"):
        adapter = types.ModuleType("linux_rdaccess_orca_adapter")
        adapter.OrcaRuntimeAdapter = types.SimpleNamespace(
            show_structural_list=lambda *args, **kwargs: None,
        )
        with mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": adapter}):
            controller._linux_rdaccess_open_structural_list(key, None)

    @staticmethod
    def keys(controller):
        return [event[:3] for event in controller.local_machine.events if event[0] == "key"]

    def test_name_only_list_letter_prevents_synthetic_press_and_release(self):
        for key in ("k", "h", "f", "b", "m"):
            for name in (key, key.upper()):
                with self.subTest(key=key, name=name):
                    controller, _, _ = self._patched_controller()
                    controller._on_remote_key(key_name=name, pressed=True)
                    controller.local_machine.events.clear()
                    self.fallback(controller, key)
                    self.assertEqual(self.keys(controller), [])
                    self.assertEqual(set(controller._lrd_forwarded), {(name, False)})
                    controller._on_remote_key(key_name=name, pressed=False)
                    self.assertEqual(self.keys(controller), [("key", None, False)])
                    self.assertFalse(controller._lrd_forwarded)

    def test_name_only_modifiers_are_borrowed_until_their_real_release(self):
        for name, borrowed, other in (("Shift_L", 0xA0, 0xA4), ("Alt_L", 0xA4, 0xA0)):
            with self.subTest(name=name):
                controller, _, _ = self._patched_controller()
                controller._on_remote_key(key_name=name, pressed=True)
                controller.local_machine.events.clear()
                self.fallback(controller)
                self.assertEqual(self.keys(controller), [
                    ("key", other, True), ("key", 0x4D, True),
                    ("key", 0x4D, False), ("key", other, False),
                ])
                self.assertNotIn(("key", borrowed, False), self.keys(controller))
                self.assertEqual(set(controller._lrd_forwarded), {(name, False)})
                controller._on_remote_key(key_name=name, pressed=False)
                self.assertFalse(controller._lrd_forwarded)

    def test_both_name_only_modifiers_leave_only_the_letter_to_inject(self):
        controller, _, _ = self._patched_controller()
        for name in ("Shift_L", "Alt_L"):
            controller._on_remote_key(key_name=name, pressed=True)
        controller.local_machine.events.clear()
        self.fallback(controller)
        self.assertEqual(self.keys(controller), [("key", 0x4D, True), ("key", 0x4D, False)])
        self.assertEqual(set(controller._lrd_forwarded), {("Shift_L", False), ("Alt_L", False)})
        controller._linux_rdaccess_reset_keys()
        self.assertEqual(self.keys(controller)[2:], [("key", None, False), ("key", None, False)])
        self.assertFalse(controller._lrd_forwarded)

    def test_borrowed_name_only_modifier_survives_a_failed_letter_release(self):
        for failure in (False, OSError("synthetic backend failure")):
            with self.subTest(failure=type(failure).__name__):
                controller, _, _ = self._patched_controller()
                controller._on_remote_key(key_name="Shift_L", pressed=True)
                controller.local_machine.events.clear()
                original = controller.local_machine.send_key
                failures = []

                def send(**payload):
                    if payload["vk_code"] == 0x4D and not payload["pressed"] and not failures:
                        failures.append(True)
                        if isinstance(failure, Exception):
                            raise failure
                        return failure
                    return original(**payload)

                controller.local_machine.send_key = send
                if isinstance(failure, Exception):
                    with self.assertRaises(OSError):
                        self.fallback(controller)
                else:
                    self.fallback(controller)
                self.assertEqual(self.keys(controller), [
                    ("key", 0xA4, True), ("key", 0x4D, True),
                    ("key", 0x4D, False), ("key", 0xA4, False),
                ])
                self.assertEqual(set(controller._lrd_forwarded), {("Shift_L", False)})
                controller._on_remote_key(key_name="Shift_L", pressed=False)
                self.assertFalse(controller._lrd_forwarded)

    def test_unrelated_name_only_letter_does_not_block_the_list_shortcut(self):
        controller, _, _ = self._patched_controller()
        controller._on_remote_key(key_name="x", pressed=True)
        controller.local_machine.events.clear()
        self.fallback(controller)
        self.assertEqual(self.keys(controller), [
            ("key", 0xA0, True), ("key", 0xA4, True), ("key", 0x4D, True),
            ("key", 0x4D, False), ("key", 0xA4, False), ("key", 0xA0, False),
        ])
        self.assertEqual(set(controller._lrd_forwarded), {("x", False)})
        controller._on_remote_key(key_name="x", pressed=False)
        self.assertFalse(controller._lrd_forwarded)

    def test_numeric_list_letter_and_modifier_guards_remain_supported(self):
        controller, _, _ = self._patched_controller()
        self._key(controller, 0x4D, True)
        controller.local_machine.events.clear()
        self.fallback(controller)
        self.assertEqual(self.keys(controller), [])
        self._key(controller, 0x4D, False)
        for shift, alt in ((0xA0, 0xA4), (0x10, 0x12)):
            with self.subTest(shift=shift, alt=alt):
                self._key(controller, shift, True)
                self._key(controller, alt, True)
                controller.local_machine.events.clear()
                self.fallback(controller)
                self.assertEqual(self.keys(controller), [("key", 0x4D, True), ("key", 0x4D, False)])
                self._key(controller, alt, False)
                self._key(controller, shift, False)
                self.assertFalse(controller._lrd_forwarded)


if __name__ == "__main__":
    unittest.main()
