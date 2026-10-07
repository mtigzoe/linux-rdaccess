"""Exact NVDA focused-object shortcut reporting without Where Am I side effects."""
from __future__ import annotations

import ast
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from orca_adapter import OrcaRuntimeAdapter
from tests.test_compat_lifecycle import Harness


class FocusAcceleratorAdapterTests(unittest.TestCase):
    @contextmanager
    def context(self, keys=("Alt+O", "Alt+F O", "Ctrl+O"), *, focus=True):
        obj = object() if focus else None
        script = types.SimpleNamespace(
            utilities=types.SimpleNamespace(
                mnemonicShortcutAccelerator=mock.Mock(return_value=list(keys)),
                getCaretContext=mock.Mock(return_value=(object(), 18)),
            ),
            presentMessage=mock.Mock(),
            whereAmIDetailed=mock.Mock(),
        )
        orca = types.ModuleType("orca")
        orca.orca_state = types.SimpleNamespace(locusOfFocus=obj)
        with mock.patch.object(OrcaRuntimeAdapter, "active_script", return_value=script), \
                mock.patch.dict(sys.modules, {"orca": orca}):
            yield script, obj

    def test_reports_only_focused_shortcuts_through_speech_and_braille_presenter(self):
        with self.context() as (script, obj):
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), True)
        script.utilities.mnemonicShortcutAccelerator.assert_called_once_with(obj)
        script.utilities.getCaretContext.assert_not_called()
        script.whereAmIDetailed.assert_not_called()
        script.presentMessage.assert_called_once_with("Alt+F O; Ctrl+O")

    def test_mnemonic_is_used_when_full_menu_shortcut_is_absent(self):
        with self.context(("Alt+O", "", "")) as (script, _):
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), True)
        script.presentMessage.assert_called_once_with("Alt+O")

    def test_duplicate_shortcut_is_presented_once(self):
        with self.context(("Ctrl+O", "Ctrl+O", "Ctrl+O")) as (script, _):
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), True)
        script.presentMessage.assert_called_once_with("Ctrl+O")

    def test_empty_shortcuts_report_no_shortcut_key(self):
        with self.context(("", "", "")) as (script, _):
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), True)
        script.presentMessage.assert_called_once_with("No shortcut key")

    def test_missing_focus_does_not_use_stale_browse_caret(self):
        with self.context(focus=False) as (script, _):
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), False)
        script.utilities.mnemonicShortcutAccelerator.assert_not_called()
        script.utilities.getCaretContext.assert_not_called()
        script.presentMessage.assert_not_called()

    def test_missing_api_is_explicitly_unsupported(self):
        with self.context() as (script, _):
            del script.utilities.mnemonicShortcutAccelerator
            self.assertIsNone(OrcaRuntimeAdapter.present_focus_accelerator())
        script.whereAmIDetailed.assert_not_called()
        script.presentMessage.assert_not_called()

    def test_native_presenter_can_decline_without_triggering_other_presentation(self):
        with self.context() as (script, _):
            script.presentMessage.return_value = False
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), False)
        script.presentMessage.assert_called_once()
        script.whereAmIDetailed.assert_not_called()

    def test_malformed_native_result_never_presented_as_application_text(self):
        for keys in (("Ctrl+O",), ("", "", object()), "private label"):
            with self.subTest(keys=type(keys).__name__), self.context() as (script, _):
                script.utilities.mnemonicShortcutAccelerator.return_value = keys
                self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), False)
            script.presentMessage.assert_not_called()

    def test_native_failure_and_partial_presentation_are_not_retried(self):
        for name in ("mnemonicShortcutAccelerator", "presentMessage"):
            with self.subTest(name=name), self.context() as (script, _):
                handler = (getattr(script.utilities, name) if name.startswith("mnemonic")
                           else getattr(script, name))
                handler.side_effect = RuntimeError("private application text")
                self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), False)
            handler.assert_called_once()
            script.whereAmIDetailed.assert_not_called()

    def test_installed_orca42_presenter_preserves_speech_and_braille(self):
        path = Path("/usr/lib/python3/dist-packages/orca/scripts/default.py")
        if not path.is_file():
            self.skipTest("Installed Orca default script is unavailable")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        script_node = next(node for node in tree.body
                           if isinstance(node, ast.ClassDef) and node.name == "Script")
        method = next(node for node in script_node.body
                      if isinstance(node, ast.FunctionDef) and node.name == "presentMessage")
        module = ast.Module(body=[method], type_ignores=[])
        ast.fix_missing_locations(module)
        braille = types.SimpleNamespace(displayMessage=mock.Mock())
        settings = {
            "enableSpeech": True, "messagesAreDetailed": True,
            "enableBraille": True, "enableBrailleMonitor": False,
            "enableFlashMessages": True, "flashIsDetailed": True,
            "flashIsPersistent": False, "brailleFlashTime": 5,
        }
        namespace = {"_settingsManager": types.SimpleNamespace(getSetting=settings.get),
                     "braille": braille}
        exec(compile(module, str(path), "exec"), namespace)
        with self.context(("", "", "Ctrl+O")) as (script, _):
            script.speakMessage = mock.Mock()
            script.presentMessage = types.MethodType(namespace["presentMessage"], script)
            self.assertIs(OrcaRuntimeAdapter.present_focus_accelerator(), True)
        script.speakMessage.assert_called_once_with("Ctrl+O", voice=None,
                                                  resetStyles=True, force=False)
        braille.displayMessage.assert_called_once_with("Ctrl+O", flashTime=5)


class FocusAcceleratorCommandTests(Harness, unittest.TestCase):
    def test_plain_shift_numpad2_reports_in_both_layouts_and_owns_repeat_release(self):
        for layout in ("desktop", "laptop"):
            with self.subTest(layout=layout), mock.patch.dict(
                    os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                controller, _, _ = self._patched_controller()
                controller._linux_rdaccess_script_call = mock.Mock()
                self._key(controller, 0xA0, True)
                for pressed in (True, True, False):
                    self._key(controller, 0x28, pressed, scan_code=0x50)
                self._key(controller, 0xA0, False)
                controller._linux_rdaccess_script_call.assert_called_once_with(
                    "presentFocusAccelerator")
                self.assertFalse(any(event[0] == "key" and event[1] == 0x28
                                     for event in controller.local_machine.events))
                self.assertFalse(controller._lrd_swapped)

    def test_laptop_shortcut_reports_for_insert_and_caps_without_toggle_replay(self):
        for modifier in (0x2D, 0x14):
            with self.subTest(modifier=modifier), mock.patch.dict(
                    os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "laptop"}):
                controller, _, _ = self._patched_controller()
                controller._linux_rdaccess_script_call = mock.Mock()
                self._key(controller, modifier, True, extended=modifier == 0x2D)
                self._key(controller, 0xA2, True)
                self._key(controller, 0xA0, True)
                for pressed in (True, True, False):
                    self._key(controller, 0xBE, pressed)
                self._key(controller, 0xA0, False)
                self._key(controller, 0xA2, False)
                self._key(controller, modifier, False, extended=modifier == 0x2D)
                controller._linux_rdaccess_script_call.assert_called_once_with(
                    "presentFocusAccelerator")
                keys = [event for event in controller.local_machine.events if event[0] == "key"]
                self.assertFalse(any(event[1] in (0xBE, 0x14) for event in keys))
                self.assertFalse(controller._lrd_swapped)

    def test_dedicated_down_and_unproven_numpad_never_report_accelerator(self):
        for extended, scan in ((True, 0x50), (False, 0), (False, 0x48)):
            with self.subTest(extended=extended, scan=scan):
                controller, _, _ = self._patched_controller()
                controller._linux_rdaccess_script_call = mock.Mock()
                self._key(controller, 0xA0, True)
                self._key(controller, 0x28, True, extended=extended, scan_code=scan)
                self._key(controller, 0x28, False, extended=extended, scan_code=scan)
                self._key(controller, 0xA0, False)
                controller._linux_rdaccess_script_call.assert_not_called()
                self.assertTrue(any(event[0] == "key" and event[1] == 0x28
                                    for event in controller.local_machine.events))

    def test_extra_modifiers_preserve_native_input_instead_of_reporting_shortcuts(self):
        for layout in ("desktop", "laptop"):
            for extra in (0xA2, 0xA4, 0x5B):
                with self.subTest(layout=layout, extra=extra), mock.patch.dict(
                        os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    controller, _, _ = self._patched_controller()
                    controller._linux_rdaccess_script_call = mock.Mock()
                    self._key(controller, 0xA0, True)
                    self._key(controller, extra, True)
                    self._key(controller, 0x28, True, scan_code=0x50)
                    self._key(controller, 0x28, False, scan_code=0x50)
                    self._key(controller, extra, False)
                    self._key(controller, 0xA0, False)
                    controller._linux_rdaccess_script_call.assert_not_called()
                    self.assertEqual(
                        [event[2] for event in controller.local_machine.events
                         if event[0] == "key" and event[1] == 0x28], [True, False])

    def test_queued_accelerator_report_is_cancelled_by_controller_reset(self):
        controller, _, _ = self._patched_controller(inline=False)
        controller._linux_rdaccess_script_call = mock.Mock()
        queue, patches = self._fake_glib()
        with patches:
            self._key(controller, 0xA0, True)
            self._key(controller, 0x28, True, scan_code=0x50)
            self._key(controller, 0x28, False, scan_code=0x50)
            self._key(controller, 0xA0, False)
            self.assertTrue(queue)
            controller.toggle_control()
            for callback in queue:
                callback()
        controller._linux_rdaccess_script_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
