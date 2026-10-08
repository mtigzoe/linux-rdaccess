"""Browser commands keep physical identity, remote provenance and typing context."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness
from tests import test_remote_access as fixtures


class BrowserCommandContextTests(Harness, unittest.TestCase):
    SHIFT, CTRL, ALT, ORCA = fixtures.LegacyConfigTests.SHIFT, fixtures.LegacyConfigTests.CTRL, \
        fixtures.LegacyConfigTests.ALT, fixtures.LegacyConfigTests.ORCA
    D_CODE, M_CODE = fixtures.LegacyConfigTests.D_CODE, fixtures.LegacyConfigTests.M_CODE
    LEFT, RIGHT, UP, DOWN = fixtures.LegacyConfigTests.LEFT, fixtures.LegacyConfigTests.RIGHT, \
        fixtures.LegacyConfigTests.UP, fixtures.LegacyConfigTests.DOWN
    KP_DOWN = fixtures.LegacyConfigTests.KP_DOWN
    _orca_env = fixtures.LegacyConfigTests._orca_env
    _hooked = fixtures.LegacyConfigTests._hooked

    LEVELS = ((7, 0x37, 17, "&"), (8, 0x38, 18, "*"), (9, 0x39, 19, "("))

    def _deferred_action(self, command):
        controller, event_class, script = self._hooked()
        action = mock.Mock()
        state = {"document": True, "frame": object()}
        script.utilities.inDocumentContent = lambda obj=None: state["document"]
        script.utilities.documentFrame = lambda: state["frame"]
        sys.modules['orca'].orca_state = types.SimpleNamespace(activeScript=script)
        nav = script.structuralNavigation
        if command == 'form':
            nav.enabledObjects['formField'].goNext = action
            vk, key, code, modifiers = 0x46, 'f', 41, 0
        elif command == 'heading':
            nav.enabledObjects['heading'].goNextAtLevelFactory = lambda level: action
            vk, key, code, modifiers = 0x37, '7', 17, 0
        elif command in ('layout'):
            self._key(controller, 0x2D, True, extended=True)
            if command == 'layout':
                script.toggleLayoutMode = action
                vk, key, code, modifiers = 0x56, 'v', 55, self.ORCA
            elif command == 'find':
                self._key(controller, 0xA2, True)
                script.inputEventHandlers['findHandler'].function = action
                vk, key, code, modifiers = 0x46, 'f', 41, self.ORCA | self.CTRL
            else:
                script.findNext = action
                vk, key, code, modifiers = 0x72, 'F3', 69, self.ORCA
        elif command in ('edge', 'arrow'):
            self._key(controller, 0xA2, True)
            self._key(controller, 0xA4, True)
            if command == 'edge':
                script.utilities.getCaretContext = lambda: ('cached page caret', 0)
                script.utilities.rowAndColumnCount = lambda table, prefer: (5, 6)
                nav.goCell = action
                vk, key, code = 0x23, 'End', 115
            else:
                script.keyBindings.table[(self.DOWN, self.SHIFT | self.ALT)] = (
                    types.SimpleNamespace(function=action))
                nav.enabledObjects['tableCell'].functions.append(action)
                vk, key, code = 0x28, 'Down', self.DOWN
            modifiers = self.CTRL | self.ALT
        else:
            script.keyBindings.table[(self.M_CODE, 0)] = types.SimpleNamespace(function=action)
            nav.functions.append(action)
            vk, key, code, modifiers = 0x44, 'd', self.D_CODE, 0
        self._key(controller, vk, True, extended=command in ('edge', 'arrow'))
        event = event_class(key, code, modifiers=modifiers)
        self.assertTrue(event.consume)
        return controller, event, script, action, state

    @staticmethod
    def _consume_deferred(event):
        if event._consumer is not None:
            event._consumer(event)
        else:
            event._handler.function(event._script, event)

    DEFERRED_COMMANDS = ('form', 'heading', 'layout',
                         'edge', 'arrow', 'landmark')

    def test_deferred_browser_actions_refuse_chrome_with_cached_page_caret(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                _, event, _, action, state = self._deferred_action(command)
                state['document'] = False
                self._consume_deferred(event)
                action.assert_not_called()

    def test_deferred_browse_navigation_refuses_focus_mode(self):
        for command in ('form', 'heading', 'edge', 'arrow', 'landmark'):
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(command)
                script.state['browse'] = False
                self._consume_deferred(event)
                action.assert_not_called()

    def test_deferred_browser_actions_expire_on_handoff(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                controller, event, _, action, _ = self._deferred_action(command)
                controller.toggle_control()
                self._consume_deferred(event)
                action.assert_not_called()

    def test_deferred_browser_actions_expire_on_script_or_document_change(self):
        for command in self.DEFERRED_COMMANDS:
            for change in ('script', 'document'):
                with self.subTest(command=command, change=change):
                    _, event, _, action, state = self._deferred_action(command)
                    if change == 'script':
                        sys.modules['orca'].orca_state.activeScript = object()
                    else:
                        state['frame'] = object()
                    self._consume_deferred(event)
                    action.assert_not_called()

    def test_deferred_browser_actions_keep_valid_commands_after_key_release(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(command)
                event.__class__(event.event_string, event.hw_code,
                                modifiers=event.modifiers, pressed=False)
                self._consume_deferred(event)
                action.assert_called_once()

    def test_deferred_document_commands_still_work_in_focus_mode(self):
        for command in ('layout'):
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(command)
                script.state['browse'] = False
                self._consume_deferred(event)
                action.assert_called_once()

    def test_handoff_during_mode_query_cannot_rebind_old_event_to_new_session(self):
        controller, event_class, script = self._hooked()
        action = mock.Mock()
        script.structuralNavigation.enabledObjects['formField'].goNext = action
        script.useStructuralNavigationModel = lambda: (controller.toggle_control(), True)[1]
        self._key(controller, 0x46, True)
        event = event_class('f', 41)
        self.assertIsNotNone(event._consumer)
        self._consume_deferred(event)
        action.assert_not_called()

    def test_shifted_heading_levels_use_physical_code_for_printable_symbol_events(self):
        for level, vk, code, symbol in self.LEVELS:
            with self.subTest(level=level):
                controller, event_class, script = self._hooked()
                self._key(controller, 0xA0, True)
                self._key(controller, vk, True)
                event = event_class(symbol, code, modifiers=self.SHIFT)
                self.assertIsNotNone(event._consumer)
                event._consumer(event)
                self.assertEqual(script.heading_calls, [("previous", level)])
                self.assertEqual(event.event_string, symbol)
                self._key(controller, vk, False)
                release = event_class(symbol, code, modifiers=self.SHIFT, pressed=False)
                self.assertIsNotNone(release._consumer)
                self.assertFalse(controller._module._LRD_BROWSE_UNSUPPORTED["held"])

    def test_local_shifted_punctuation_never_becomes_remote_heading_command(self):
        for level, _vk, code, symbol in self.LEVELS:
            with self.subTest(level=level):
                _controller, event_class, script = self._hooked()
                event = event_class(symbol, code, modifiers=self.SHIFT)
                self.assertIsNone(event._consumer)
                self.assertEqual(script.heading_calls, [])

    def test_remote_marker_does_not_own_symbol_from_different_physical_key(self):
        controller, event_class, script = self._hooked()
        self._key(controller, 0xA0, True)
        self._key(controller, 0x37, True)
        event = event_class("&", 83, modifiers=self.SHIFT)  # physical KP_7
        self.assertIsNone(event._consumer)
        self.assertEqual(script.heading_calls, [])

    def test_remote_shifted_heading_refused_in_focus_mode_cannot_claim_later_local_key(self):
        for level, vk, code, symbol in self.LEVELS:
            with self.subTest(level=level):
                controller, event_class, script = self._hooked(browse=False)
                self._key(controller, 0xA0, True)
                self._key(controller, vk, True)
                event = event_class(symbol, code, modifiers=self.SHIFT)
                self.assertIsNone(event._consumer)
                script.state["browse"] = True
                local = event_class(symbol, code, modifiers=self.SHIFT)
                self.assertIsNone(local._consumer)
                self.assertEqual(script.heading_calls, [])

    def test_actual_orca42_gate_preserves_editable_and_browser_chrome_typing(self):
        path = Path("/usr/lib/python3/dist-packages/orca/scripts/web/script.py")
        if not path.is_file():
            self.skipTest("Installed Orca web script is unavailable")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        script_node = next(node for node in tree.body
                           if isinstance(node, ast.ClassDef) and node.name == "Script")
        gate = next(node for node in script_node.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "useStructuralNavigationModel")
        module = ast.Module(body=[gate], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {}
        exec(compile(module, str(path), "exec"), namespace)
        import types
        guarded_letters = (("a", 0x41, 38), ("f", 0x46, 41), ("m", 0x4D, 58),
                           ("n", 0x4E, 57), ("o", 0x4F, 32), ("w", 0x57, 25),
                           ("d", 0x44, self.D_CODE))
        cases = [(vk, code, letter.upper() if shift else letter, shift)
                 for letter, vk, code in guarded_letters for shift in (False, True)]
        cases.extend((vk, code, symbol, True) for _level, vk, code, symbol in self.LEVELS)
        for in_document, focus_mode in ((True, True), (False, False)):
            for vk, code, symbol, shift in cases:
                with self.subTest(document=in_document, focus=focus_mode, vk=vk, shift=shift):
                    controller, event_class, script = self._hooked()
                    script.structuralNavigation.enabled = True
                    script._inFocusMode = focus_mode
                    script.utilities.inDocumentContent = lambda: in_document
                    script.useStructuralNavigationModel = types.MethodType(
                        namespace["useStructuralNavigationModel"], script)
                    if shift:
                        self._key(controller, 0xA0, True)
                    self._key(controller, vk, True)
                    event = event_class(symbol, code, modifiers=self.SHIFT if shift else 0)
                    self.assertIsNone(event._consumer)
                    self.assertEqual(script.heading_calls, [])
                    self.assertEqual(script.form_calls, [])


if __name__ == "__main__":
    unittest.main()
