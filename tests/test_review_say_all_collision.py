"""NVDA review Say All cannot invoke Orca's caret Say All through KP_Add."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class ReviewSayAllCollisionTests(Harness, unittest.TestCase):
    def test_plain_numpad_plus_review_command_owns_repeat_and_release_in_both_layouts(self):
        for layout in ("desktop", "laptop"):
            with self.subTest(layout=layout), mock.patch.dict(
                    os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                controller, _, _ = self._patched_controller()
                controller._linux_rdaccess_script_call = mock.Mock()
                for pressed in (True, True, False):
                    self._key(controller, 0x6B, pressed)
                self.assertFalse(any(event[0] == "key" and event[1] == 0x6B
                                     for event in controller.local_machine.events))
                controller._linux_rdaccess_script_call.assert_not_called()
                self.assertFalse(controller._lrd_swapped)

    def test_modified_and_uncertain_numpad_plus_forms_keep_application_input(self):
        for modifier, extended in ((0xA0, False), (0xA2, False), (0xA4, False),
                                   (0x5B, False), (None, True)):
            with self.subTest(modifier=modifier, extended=extended):
                controller, _, _ = self._patched_controller()
                if modifier:
                    self._key(controller, modifier, True)
                self._key(controller, 0x6B, True, extended=extended)
                self._key(controller, 0x6B, False, extended=extended)
                if modifier:
                    self._key(controller, modifier, False)
                self.assertEqual(
                    [event[2] for event in controller.local_machine.events
                     if event[0] == "key" and event[1] == 0x6B], [True, False])

    def test_caret_say_all_commands_are_preserved_for_both_nvda_modifiers(self):
        for layout, vk, extended in (("desktop", 0x28, True), ("laptop", 0x41, False)):
            for modifier in (0x2D, 0x14):
                with self.subTest(layout=layout, modifier=modifier), mock.patch.dict(
                        os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    controller, _, _ = self._patched_controller()
                    controller._linux_rdaccess_script_call = mock.Mock()
                    self._key(controller, modifier, True, extended=modifier == 0x2D)
                    self._key(controller, vk, True, extended=extended)
                    self._key(controller, vk, False, extended=extended)
                    self._key(controller, modifier, False, extended=modifier == 0x2D)
                    controller._linux_rdaccess_script_call.assert_called_once_with("sayAll")

    def test_installed_orca42_first_kp_add_handler_reads_focused_caret(self):
        root = Path("/usr/lib/python3/dist-packages/orca")
        keymap_path, script_path = root / "desktop_keyboardmap.py", root / "scripts/default.py"
        if not keymap_path.is_file() or not script_path.is_file():
            self.skipTest("Installed Orca default script/keymap is unavailable")
        namespace = {"__name__": "orca.desktop_keyboardmap", "__package__": "orca"}
        keymap_tree = ast.parse(keymap_path.read_text(encoding="utf-8"))
        keymap_assignment = next(node for node in keymap_tree.body
                                 if isinstance(node, ast.Assign)
                                 and any(isinstance(t, ast.Name) and t.id == "keymap"
                                         for t in node.targets))
        keymap_module = ast.Module(body=[keymap_assignment], type_ignores=[])
        namespace.update(defaultModifierMask=1, ORCA_MODIFIER_MASK=256,
                         NO_MODIFIER_MASK=0, ORCA_SHIFT_MODIFIER_MASK=257)
        exec(compile(keymap_module, str(keymap_path), "exec"), namespace)
        add_handlers = [(binding[3], binding[4]) for binding in namespace["keymap"]
                        if binding[0] == "KP_Add" and binding[2] == 0]
        self.assertEqual(add_handlers, [("sayAllHandler", 1), ("flatReviewSayAllHandler", 2)])

        tree = ast.parse(script_path.read_text(encoding="utf-8"))
        script_node = next(node for node in tree.body
                           if isinstance(node, ast.ClassDef) and node.name == "Script")
        method = next(node for node in script_node.body
                      if isinstance(node, ast.FunctionDef) and node.name == "sayAll")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        focus = types.SimpleNamespace(queryText=lambda: types.SimpleNamespace(caretOffset=17))
        speech = types.SimpleNamespace(sayAll=mock.Mock())
        namespace = {"orca_state": types.SimpleNamespace(locusOfFocus=focus), "speech": speech}
        exec(compile(module, str(script_path), "exec"), namespace)
        lines = object()
        script = types.SimpleNamespace(
            utilities=types.SimpleNamespace(isDead=lambda obj: False),
            textLines=mock.Mock(return_value=lines),
            _Script__sayAllProgressCallback=mock.Mock(),
        )
        # The extracted standalone function has no class-level name mangling.
        setattr(script, "__sayAllProgressCallback", script._Script__sayAllProgressCallback)
        self.assertIs(namespace["sayAll"](script, None), True)
        script.textLines.assert_called_once_with(focus, 17)
        speech.sayAll.assert_called_once_with(lines, script._Script__sayAllProgressCallback)


if __name__ == "__main__":
    unittest.main()
