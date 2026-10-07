"""NVDA pointer clicks cannot fall through to Orca focus/review-item clicks."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class MouseCommandCollisionTests(Harness, unittest.TestCase):
    KEYS = ((0x6F, True), (0x6A, False))  # NVDA NumpadDivide/Multiply

    def test_plain_remote_mouse_commands_are_owned_in_both_layouts(self):
        for layout in ("desktop", "laptop"):
            for vk, extended in self.KEYS:
                with self.subTest(layout=layout, vk=vk), mock.patch.dict(
                        os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    controller, _, _ = self._patched_controller()
                    controller._linux_rdaccess_script_call = mock.Mock()
                    for pressed in (True, True, False):
                        self._key(controller, vk, pressed, extended=extended)
                    self.assertFalse(any(event[0] == "key" and event[1] == vk
                                         for event in controller.local_machine.events))
                    controller._linux_rdaccess_script_call.assert_not_called()
                    self.assertFalse(controller._lrd_swapped)

    def test_press_ownership_survives_modifier_change_before_repeat_and_release(self):
        for vk, extended in self.KEYS:
            with self.subTest(vk=vk):
                controller, _, _ = self._patched_controller()
                self._key(controller, vk, True, extended=extended)
                self._key(controller, 0xA2, True)
                self._key(controller, vk, True, extended=extended)
                self._key(controller, vk, False, extended=extended)
                self._key(controller, 0xA2, False)
                self.assertFalse(any(event[0] == "key" and event[1] == vk
                                     for event in controller.local_machine.events))
                self.assertFalse(controller._lrd_swapped)

    def test_ctrl_alt_win_modified_click_keys_keep_native_input(self):
        for modifier in (0xA2, 0xA4, 0x5B):
            for vk, extended in self.KEYS:
                with self.subTest(modifier=modifier, vk=vk):
                    controller, _, _ = self._patched_controller()
                    self._key(controller, modifier, True)
                    self._key(controller, vk, True, extended=extended)
                    self._key(controller, vk, False, extended=extended)
                    self._key(controller, modifier, False)
                    self.assertEqual(
                        [event[2] for event in controller.local_machine.events
                         if event[0] == "key" and event[1] == vk], [True, False])

    def test_uncertain_extended_identities_keep_existing_native_input(self):
        for vk, extended in ((0x6F, False), (0x6A, True)):
            with self.subTest(vk=vk):
                controller, _, _ = self._patched_controller()
                self._key(controller, vk, True, extended=extended)
                self._key(controller, vk, False, extended=extended)
                self.assertEqual(
                    [event[2] for event in controller.local_machine.events
                     if event[0] == "key" and event[1] == vk], [True, False])

    def test_consumed_pointer_click_reset_does_not_inject_unmatched_release(self):
        for vk, extended in self.KEYS:
            with self.subTest(vk=vk):
                controller, _, _ = self._patched_controller()
                self._key(controller, vk, True, extended=extended)
                controller.toggle_control()
                controller.toggle_control()
                self._key(controller, vk, False, extended=extended)
                self.assertFalse(any(event[0] == "key" and event[1] == vk
                                     for event in controller.local_machine.events))
                self.assertFalse(controller._lrd_swapped)

    def test_installed_orca42_click_handlers_target_focus_instead_of_current_pointer(self):
        path = Path("/usr/lib/python3/dist-packages/orca/scripts/default.py")
        if not path.is_file():
            self.skipTest("Installed Orca default script is unavailable")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        script_node = next(node for node in tree.body
                           if isinstance(node, ast.ClassDef) and node.name == "Script")
        methods = [node for node in script_node.body
                   if isinstance(node, ast.FunctionDef)
                   and node.name in ("leftClickReviewItem", "rightClickReviewItem")]
        module = ast.Module(body=methods, type_ignores=[])
        ast.fix_missing_locations(module)
        focus = object()
        synth = types.SimpleNamespace(clickCharacter=mock.Mock(return_value=True),
                                      clickObject=mock.Mock())
        namespace = {"orca_state": types.SimpleNamespace(locusOfFocus=focus),
                     "eventsynthesizer": synth}
        exec(compile(module, str(path), "exec"), namespace)
        script = types.SimpleNamespace(flatReviewContext=None,
                                       utilities=types.SimpleNamespace(
                                           queryNonEmptyText=lambda obj: True))
        for method, button in (("leftClickReviewItem", 1), ("rightClickReviewItem", 3)):
            self.assertIs(namespace[method](script), True)
            synth.clickCharacter.assert_called_with(focus, button)
        synth.clickObject.assert_not_called()


if __name__ == "__main__":
    unittest.main()
