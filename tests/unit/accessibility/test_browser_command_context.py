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

    def _native_hooked(self):
        controller, _, _ = self._patched_controller()
        event_class, script, patches = self._orca_env()
        patches.start()
        self.addCleanup(patches.stop)
        state = sys.modules['orca'].orca_state
        state.capturingKeys = state.bypassNextCommand = False
        state.learnModeEnabled = state.listNotificationsModeEnabled = False
        fixture = Path(__file__).resolve().parents[2] / 'fixtures/orca42-keyboard-consume-methods.py'
        namespace = {'orca_state': state}
        exec(compile(fixture.read_text(), str(fixture), 'exec'), namespace)
        event_class.shouldConsume = namespace['KeyboardEvent'].shouldConsume
        event_class._presentHandler = namespace['KeyboardEvent']._presentHandler
        event_class.timestamp = 1
        event_class.is_duplicate = False
        event_class._getUserHandler = lambda event: None
        event_class._isReleaseForLastNonModifierKeyEvent = lambda event: False
        event_class.isModifierKey = lambda event: False
        script.consumesKeyboardEvent = lambda event: bool(event._handler)
        self.assertTrue(controller._module._lrd_install_orca_hook())
        return controller, event_class, script

    def _deferred_action(self, command, *, native=False, capture=False,
                         in_document=True, learn=False, browse=True):
        controller, event_class, script = self._native_hooked() if native else self._hooked()
        action = mock.Mock()
        state = {"document": in_document, "frame": object()}
        script.utilities.inDocumentContent = lambda obj=None: state["document"]
        script.utilities.documentFrame = lambda: state["frame"]
        if not native:
            sys.modules['orca'].orca_state = types.SimpleNamespace(activeScript=script)
        sys.modules['orca'].orca_state.capturingKeys = capture
        if learn:
            sys.modules['orca'].orca_state.learnModeEnabled = True
        script.state['browse'] = browse
        script.presentMessage = mock.Mock()
        if native:
            script.consumesKeyboardEvent = mock.Mock(wraps=script.consumesKeyboardEvent)
        nav = script.structuralNavigation
        for name, description in (
                ('findHandler', 'Localized find'),
                ('findNextHandler', 'Localized find next'),
                ('findPreviousHandler', 'Localized find previous'),
                ('toggleLayoutModeHandler', 'Localized layout')):
            handler = script.inputEventHandlers.setdefault(name, types.SimpleNamespace())
            handler.description, handler.learnModeEnabled = description, True
        nav.enabledObjects['formField'].inputEventHandlers = {
            'formFieldGoNext': types.SimpleNamespace(
                description='Localized next form field', learnModeEnabled=True),
            'formFieldGoPrevious': types.SimpleNamespace(
                description='Localized previous form field', learnModeEnabled=True),
        }
        nav.enabledObjects['heading'].inputEventHandlers = {}
        cmdnames = types.ModuleType('orca.cmdnames')
        cmdnames.HEADING_AT_LEVEL_NEXT = 'Localized next heading %d'
        cmdnames.HEADING_AT_LEVEL_PREV = 'Localized previous heading %d'
        cmdnames_patch = mock.patch.dict(sys.modules, {'orca.cmdnames': cmdnames})
        cmdnames_patch.start()
        self.addCleanup(cmdnames_patch.stop)
        sys.modules['orca'].cmdnames = cmdnames
        if command == 'form':
            nav.enabledObjects['formField'].goNext = action
            vk, key, code, modifiers = 0x46, 'f', 41, 0
        elif command == 'heading':
            nav.enabledObjects['heading'].goNextAtLevelFactory = lambda level: action
            vk, key, code, modifiers = 0x37, '7', 17, 0
        elif command in ('layout', 'find', 'find_next', 'find_previous'):
            self._key(controller, 0x2D, True, extended=True)
            if command == 'layout':
                script.toggleLayoutMode = action
                vk, key, code, modifiers = 0x56, 'v', 55, self.ORCA
            elif command == 'find':
                self._key(controller, 0xA2, True)
                script.inputEventHandlers['findHandler'].function = action
                vk, key, code, modifiers = 0x46, 'f', 41, self.ORCA | self.CTRL
            else:
                modifiers = self.ORCA
                if command == 'find_previous':
                    self._key(controller, 0xA0, True)
                    script.findPrevious = action
                    modifiers |= self.SHIFT
                else:
                    script.findNext = action
                vk, key, code = 0x72, 'F3', 69
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
        for handler in script.keyBindings.table.values():
            handler.learnModeEnabled = True
            if not hasattr(handler, 'description'):
                handler.description = 'Native physical key binding'
        self._key(controller, vk, True, extended=command in ('edge', 'arrow'))
        event = event_class(key, code, modifiers=modifiers)
        consumed = event.consume[0] if isinstance(event.consume, tuple) else event.consume
        self.assertEqual(consumed, not capture)
        return controller, event, script, action, state

    @staticmethod
    def _consume_deferred(event):
        if event._consumer is not None:
            event._consumer(event)
        else:
            event._handler.function(event._script, event)

    DEFERRED_COMMANDS = ('form', 'heading', 'layout', 'find', 'find_next',
                         'edge', 'arrow', 'landmark')
    COMMAND_KEYS = {'form': 0x46, 'heading': 0x37, 'layout': 0x56,
                    'find': 0x46, 'find_next': 0x72, 'edge': 0x23,
                    'arrow': 0x28, 'landmark': 0x44}
    HELP_COMMANDS = {
        'form': 'Localized next form field',
        'heading': 'Localized next heading 7',
        'layout': 'Localized layout',
        'find': 'Localized find',
        'find_next': 'Localized find next',
        'find_previous': 'Localized find previous',
    }

    def test_input_help_describes_browse_commands_without_executing_them(self):
        for command, description in self.HELP_COMMANDS.items():
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(
                    command, native=True, learn=True)
                self.assertEqual(event.consume, (True, 'In Learn Mode'))
                script.consumesKeyboardEvent.assert_called_once_with(event)
                self._consume_deferred(event)
                action.assert_not_called()
                script.presentMessage.assert_called_once_with(description)

    def test_input_help_describes_commands_in_focus_mode_and_browser_chrome(self):
        for command, description in self.HELP_COMMANDS.items():
            for document in (True, False):
                with self.subTest(command=command, document=document):
                    _, event, script, action, _ = self._deferred_action(
                        command, native=True, learn=True, browse=False, in_document=document)
                    self._consume_deferred(event)
                    action.assert_not_called()
                    script.presentMessage.assert_called_once_with(description)

    def test_help_gesture_never_executes_after_help_is_turned_off(self):
        for command in (*self.HELP_COMMANDS, 'edge'):
            with self.subTest(command=command):
                controller, event, script, action, _ = self._deferred_action(
                    command, native=True, learn=True)
                sys.modules['orca'].orca_state.learnModeEnabled = False
                self._consume_deferred(event)
                action.assert_not_called()
                script.presentMessage.assert_not_called()
                release = event.__class__(event.event_string, event.hw_code,
                                          modifiers=event.modifiers, pressed=False)
                self._consume_deferred(release)
                action.assert_not_called()
                vk = self.COMMAND_KEYS.get(command, 0x72)
                self._key(controller, vk, True, extended=command == 'edge')
                current = event.__class__(event.event_string, event.hw_code,
                                          modifiers=event.modifiers)
                self._consume_deferred(current)
                action.assert_called_once()

    def test_input_help_repeats_describe_each_press_and_release_does_not_repeat(self):
        for command, description in self.HELP_COMMANDS.items():
            with self.subTest(command=command):
                controller, event, script, action, _ = self._deferred_action(
                    command, native=True, learn=True)
                self._consume_deferred(event)
                self._key(controller, self.COMMAND_KEYS.get(command, 0x72), True)
                repeated = event.__class__(event.event_string, event.hw_code,
                                           modifiers=event.modifiers)
                self._consume_deferred(repeated)
                release = event.__class__(event.event_string, event.hw_code,
                                          modifiers=event.modifiers, pressed=False)
                self._consume_deferred(release)
                action.assert_not_called()
                self.assertEqual(script.presentMessage.call_args_list,
                                 [mock.call(description), mock.call(description)])

    def test_input_help_honors_native_handler_presentation_preferences(self):
        for command in ('form', 'layout', 'find'):
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(
                    command, native=True, learn=True)
                if command == 'form':
                    handler = script.structuralNavigation.enabledObjects[
                        'formField'].inputEventHandlers['formFieldGoNext']
                else:
                    name = 'toggleLayoutModeHandler' if command == 'layout' else 'findHandler'
                    handler = script.inputEventHandlers[name]
                handler.learnModeEnabled = False
                self._consume_deferred(event)
                action.assert_not_called()
                script.presentMessage.assert_not_called()

    def test_help_callbacks_expire_on_handoff_script_change_or_shortcut_capture(self):
        for command in self.HELP_COMMANDS:
            for change in ('handoff', 'script', 'capture'):
                with self.subTest(command=command, change=change):
                    controller, event, script, action, _ = self._deferred_action(
                        command, native=True, learn=True)
                    if change == 'handoff':
                        controller.toggle_control()
                    elif change == 'script':
                        sys.modules['orca'].orca_state.activeScript = object()
                    else:
                        sys.modules['orca'].orca_state.capturingKeys = True
                    self._consume_deferred(event)
                    action.assert_not_called()
                    script.presentMessage.assert_not_called()

    def test_table_edges_in_input_help_never_query_or_move_the_cell(self):
        controller, event_class, script = self._native_hooked()
        sys.modules['orca'].orca_state.learnModeEnabled = True
        query = mock.Mock(side_effect=AssertionError('input help queried a cell'))
        script.utilities.getCaretContext = query
        script.presentMessage = mock.Mock()
        script.structuralNavigation.goCell = mock.Mock()
        for vk in (0xA2, 0xA4, 0x23):
            self._key(controller, vk, True, extended=vk == 0x23)
        event = event_class('End', 115, modifiers=self.CTRL | self.ALT)
        self._consume_deferred(event)
        query.assert_not_called()
        script.structuralNavigation.goCell.assert_not_called()
        script.presentMessage.assert_not_called()

    def test_caps_find_help_never_opens_orca_shortcut_list_in_either_layout(self):
        for layout in ('desktop', 'laptop'):
            for reverse in (False, True):
                with self.subTest(layout=layout, reverse=reverse), mock.patch.dict(
                        'os.environ', LINUX_RDACCESS_NVDA_LAYOUT=layout):
                    controller, event_class, script = self._native_hooked()
                    sys.modules['orca'].orca_state.learnModeEnabled = True
                    script.presentMessage, script.listOrcaShortcuts = mock.Mock(), mock.Mock()
                    script.findNext, script.findPrevious = mock.Mock(), mock.Mock()
                    name = 'findPreviousHandler' if reverse else 'findNextHandler'
                    script.inputEventHandlers[name] = types.SimpleNamespace(
                        description='Localized find direction', learnModeEnabled=True)
                    self._key(controller, 0x14, True)
                    if reverse:
                        self._key(controller, 0xA0, True)
                    self._key(controller, 0x72, True)
                    event = event_class('F3', 69, modifiers=self.SHIFT if reverse else 0)
                    self._consume_deferred(event)
                    script.presentMessage.assert_called_once_with('Localized find direction')
                    script.listOrcaShortcuts.assert_not_called()
                    script.findNext.assert_not_called()
                    script.findPrevious.assert_not_called()

    def test_input_help_claims_never_leak_into_later_local_commands(self):
        for command in self.HELP_COMMANDS:
            with self.subTest(command=command):
                _, event, _, action, _ = self._deferred_action(command, native=True, learn=True)
                sys.modules['orca'].orca_state.learnModeEnabled = False
                local = event.__class__(event.event_string, event.hw_code,
                                        modifiers=event.modifiers)
                self.assertIsNone(local._consumer)
                action.assert_not_called()

    def test_input_help_preserves_native_timestamp_and_duplicate_refusals(self):
        for reason in ('No timestamp', 'Is duplicate'):
            with self.subTest(reason=reason):
                controller, event_class, script = self._native_hooked()
                state = sys.modules['orca'].orca_state
                state.learnModeEnabled = True
                event_class.timestamp = 0 if reason == 'No timestamp' else 1
                event_class.is_duplicate = reason == 'Is duplicate'
                script.presentMessage, script.toggleLayoutMode = mock.Mock(), mock.Mock()
                self._key(controller, 0x2D, True, extended=True)
                self._key(controller, 0x56, True)
                event = event_class('v', 55, modifiers=self.ORCA)
                self.assertEqual(event.consume, (False, reason))
                self.assertIsNone(event._consumer)
                script.presentMessage.assert_not_called()
                script.toggleLayoutMode.assert_not_called()

    def test_input_help_never_describes_unrelated_native_browse_bindings(self):
        cases = ((0x41, 'a', 38, (), 0),
                 (0x4D, 'm', 58, (), 0),
                 (0x79, 'F10', 76, (0x2D, 0xA0), self.ORCA | self.SHIFT))
        for vk, key, code, modifiers, mask in cases:
            with self.subTest(key=key):
                controller, event_class, script = self._native_hooked()
                sys.modules['orca'].orca_state.learnModeEnabled = True
                script.presentMessage = mock.Mock()
                for modifier in modifiers:
                    self._key(controller, modifier, True, extended=modifier == 0x2D)
                self._key(controller, vk, True)
                event = event_class(key, code, modifiers=mask)
                self._consume_deferred(event)
                self.assertIsNone(event._handler)
                script.presentMessage.assert_not_called()

    def test_shifted_form_and_heading_help_uses_native_previous_descriptions(self):
        cases = [('form', 0x46, 'F', 41, 'Localized previous form field')]
        cases.extend(('heading', vk, symbol, code, 'Localized previous heading %d' % level)
                     for level, vk, code, symbol in self.LEVELS)
        for command, vk, key, code, description in cases:
            with self.subTest(key=key):
                controller, original, script, action, _ = self._deferred_action(
                    command, native=True, learn=True)
                heading = script.structuralNavigation.enabledObjects['heading']
                factory = mock.Mock(side_effect=AssertionError('help created a heading action'))
                heading.goPreviousAtLevelFactory = factory
                self._key(controller, 0xA0, True)
                self._key(controller, vk, True)
                event = original.__class__(key, code, modifiers=self.SHIFT)
                self._consume_deferred(event)
                factory.assert_not_called()
                action.assert_not_called()
                self.assertEqual(script.form_calls, [])
                script.presentMessage.assert_called_once_with(description)

    def test_native_landmark_and_table_arrow_help_keeps_native_presentation(self):
        for command in ('landmark', 'arrow'):
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(
                    command, native=True, learn=True)
                self._consume_deferred(event)
                action.assert_not_called()
                script.presentMessage.assert_called_once_with('Native physical key binding')

    def test_native_dispatcher_passes_remote_commands_to_shortcut_capture(self):
        for command in self.DEFERRED_COMMANDS:
            for in_document in (True, False):
                with self.subTest(command=command, document=in_document):
                    _, event, _, action, _ = self._deferred_action(
                        command, native=True, capture=True, in_document=in_document)
                    self.assertEqual(event.consume, (False, 'Capturing keys'))
                    self.assertIsNone(event._handler)
                    self.assertIsNone(event._consumer)
                    self.assertFalse(hasattr(event, '_lrd_navigation_context'))
                    action.assert_not_called()

    def test_captured_command_claim_cannot_translate_a_later_local_key(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                controller, event, _, action, _ = self._deferred_action(
                    command, native=True, capture=True)
                sys.modules['orca'].orca_state.capturingKeys = False
                local = event.__class__(event.event_string, event.hw_code,
                                        modifiers=event.modifiers)
                self.assertIsNone(local._consumer)
                self.assertFalse(hasattr(local, '_lrd_navigation_context'))
                for marker in (controller._module._LRD_D, controller._module._LRD_T,
                               controller._module._LRD_NVDA_BROWSE,
                               controller._module._LRD_BROWSE_UNSUPPORTED,
                               controller._module._LRD_TABLE_EDGE):
                    self.assertEqual(marker['pending'], [])
                action.assert_not_called()

    def test_capture_start_passes_previously_owned_command_release(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                controller, event, _, action, _ = self._deferred_action(command, native=True)
                sys.modules['orca'].orca_state.capturingKeys = True
                release = event.__class__(event.event_string, event.hw_code,
                                          modifiers=event.modifiers, pressed=False)
                self.assertEqual(release.consume, (False, 'Capturing keys'))
                self.assertIsNone(release._consumer)
                self.assertIsNone(release._handler)
                self.assertFalse(controller._module._LRD_D['swapped'])
                for marker in (controller._module._LRD_T,
                               controller._module._LRD_NVDA_BROWSE,
                               controller._module._LRD_BROWSE_UNSUPPORTED,
                               controller._module._LRD_TABLE_EDGE):
                    self.assertEqual(marker['held'], {})
                action.assert_not_called()

    def test_deferred_browser_action_refuses_new_shortcut_capture(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                _, event, _, action, _ = self._deferred_action(command, native=True)
                sys.modules['orca'].orca_state.capturingKeys = True
                self._consume_deferred(event)
                action.assert_not_called()

    def test_native_dispatcher_keeps_commands_working_after_capture_ends(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                controller, event, _, action, _ = self._deferred_action(
                    command, native=True, capture=True)
                sys.modules['orca'].orca_state.capturingKeys = False
                self._key(controller, self.COMMAND_KEYS[command], True,
                          extended=command in ('edge', 'arrow'))
                current = event.__class__(event.event_string, event.hw_code,
                                          modifiers=event.modifiers)
                self.assertTrue(current.consume[0])
                self._consume_deferred(current)
                action.assert_called_once()

    def test_native_capture_preserves_key_identity_before_binding_lookup(self):
        for command in self.DEFERRED_COMMANDS:
            with self.subTest(command=command):
                controller, event, script, _, _ = self._deferred_action(command, native=True)
                sys.modules['orca'].orca_state.capturingKeys = True
                lookup = mock.Mock(wraps=script.keyBindings.getInputHandler)
                script.keyBindings.getInputHandler = lookup
                self._key(controller, self.COMMAND_KEYS[command], True,
                          extended=command in ('edge', 'arrow'))
                captured = event.__class__(event.event_string, event.hw_code,
                                           modifiers=event.modifiers)
                self.assertEqual(captured.consume, (False, 'Capturing keys'))
                lookup.assert_not_called()
                self.assertEqual((captured.event_string, captured.hw_code, captured.modifiers),
                                 (event.event_string, event.hw_code, event.modifiers))

    def test_shortcut_capture_accepts_unsupported_and_shifted_browse_keys(self):
        cases = (
            (0x41, 'a', 38, (), 0),
            (0x37, '&', 17, (0xA0,), self.SHIFT),
            (0x79, 'F10', 76, (0x2D, 0xA0), self.ORCA | self.SHIFT),
        )
        for vk, key, code, modifiers, mask in cases:
            with self.subTest(key=key):
                controller, event_class, script = self._native_hooked()
                script.state['browse'] = False
                script.utilities.inDocumentContent = lambda: False
                sys.modules['orca'].orca_state.capturingKeys = True
                for modifier in modifiers:
                    self._key(controller, modifier, True, extended=modifier == 0x2D)
                self._key(controller, vk, True)
                event = event_class(key, code, modifiers=mask)
                self.assertEqual(event.consume, (False, 'Capturing keys'))
                self.assertIsNone(event._handler)
                self.assertIsNone(event._consumer)
                self.assertEqual((event.event_string, event.hw_code, event.modifiers),
                                 (key, code, mask))
                sys.modules['orca'].orca_state.capturingKeys = False
                script.state['browse'] = True
                script.utilities.inDocumentContent = lambda: True
                local = event_class(key, code, modifiers=mask)
                self.assertIsNone(local._consumer)
                self.assertFalse(hasattr(local, '_lrd_navigation_context'))

    def test_capture_does_not_retire_a_claim_for_an_ineligible_earlier_key(self):
        controller, event_class, _ = self._native_hooked()
        sys.modules['orca'].orca_state.capturingKeys = True
        self._key(controller, 0x44, True)
        # An older Ctrl+D event must not steal the arriving plain D's claim.
        earlier = event_class('d', self.D_CODE, modifiers=self.CTRL)
        self.assertEqual(earlier.consume, (False, 'Capturing keys'))
        self.assertEqual(len(controller._module._LRD_D['pending']), 1)
        captured = event_class('d', self.D_CODE)
        self.assertEqual(captured.consume, (False, 'Capturing keys'))
        self.assertEqual(controller._module._LRD_D['pending'], [])
        sys.modules['orca'].orca_state.capturingKeys = False
        local = event_class('d', self.D_CODE)
        self.assertEqual(local._handler.function, 'live_region')
        self.assertIsNone(local._consumer)

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

    def test_untranslated_repeat_does_not_keep_a_previous_command_release(self):
        cases = (
            ('form', 0x46, (), False),
            ('heading', 0x37, (), False),
            ('layout', 0x56, (0x2D,), False),
            ('find', 0x46, (0xA2, 0x2D), False),
            ('find_next', 0x72, (0x2D,), False),
            ('edge', 0x23, (0xA4, 0xA2), True),
        )
        for command, vk, modifiers, extended in cases:
            with self.subTest(command=command):
                controller, event, script, _, state = self._deferred_action(command)
                # The first press was a remote browse command. A repeat after
                # a mode/chord change is ordinary application input.
                script.state['browse'] = False
                state['document'] = False
                script.keyBindings.table = {}
                for modifier in modifiers:
                    self._key(controller, modifier, False, extended=modifier == 0x2D)
                self._key(controller, vk, True, extended=extended)
                repeated = event.__class__(event.event_string, event.hw_code)
                self.assertFalse(repeated.consume)
                self._key(controller, vk, False, extended=extended)
                release = event.__class__(event.event_string, event.hw_code, pressed=False)
                self.assertFalse(release.consume)
                self.assertIsNone(release._consumer)

    def test_command_release_remains_owned_without_an_intervening_press(self):
        for command in ('form', 'heading', 'layout', 'find', 'find_next', 'edge'):
            with self.subTest(command=command):
                _, event, script, _, state = self._deferred_action(command)
                script.state['browse'] = False
                state['document'] = False
                script.keyBindings.table = {}
                release = event.__class__(event.event_string, event.hw_code, pressed=False)
                self.assertTrue(release.consume)
                self.assertIsNotNone(release._consumer)

    def test_deferred_document_commands_still_work_in_focus_mode(self):
        for command in ('layout', 'find', 'find_next'):
            with self.subTest(command=command):
                _, event, script, action, _ = self._deferred_action(command)
                script.state['browse'] = False
                self._consume_deferred(event)
                action.assert_called_once()

    def test_held_nvda_browse_commands_keep_their_native_action_on_repeat(self):
        for command, vk in (('layout', 0x56), ('find', 0x46), ('find_next', 0x72)):
            with self.subTest(command=command):
                controller, event, script, action, _ = self._deferred_action(command)
                # Bind the same physical key to an unrelated native command.
                # Without a new remote claim, repeats fall into that binding.
                unrelated = mock.Mock()
                script.keyBindings.table[(event.hw_code, event.modifiers)] = (
                    types.SimpleNamespace(function=unrelated))
                self._consume_deferred(event)
                for _ in range(2):
                    self._key(controller, vk, True)
                    repeated = event.__class__(event.event_string, event.hw_code,
                                               modifiers=event.modifiers)
                    self._consume_deferred(repeated)
                self.assertEqual(action.call_count, 3)
                unrelated.assert_not_called()

    def test_held_nvda_browse_commands_in_chrome_never_repeat_into_application(self):
        for command, vk in (('layout', 0x56), ('find', 0x46), ('find_next', 0x72)):
            with self.subTest(command=command):
                controller, event, script, action, state = self._deferred_action(command)
                state['document'] = False
                unrelated = mock.Mock()
                script.keyBindings.table[(event.hw_code, event.modifiers)] = (
                    types.SimpleNamespace(function=unrelated))
                self._key(controller, vk, True)
                repeated = event.__class__(event.event_string, event.hw_code,
                                           modifiers=event.modifiers)
                self._consume_deferred(repeated)
                action.assert_not_called()
                unrelated.assert_not_called()

    def test_unsupported_native_selection_repeat_stays_consumed(self):
        controller, event_class, script = self._hooked()
        self._key(controller, 0x2D, True, extended=True)
        self._key(controller, 0xA0, True)
        self._key(controller, 0x79, True)
        event = event_class('F10', 76, modifiers=self.ORCA | self.SHIFT)
        self.assertIsNotNone(event._consumer)
        self._key(controller, 0x79, True)
        repeated = event_class('F10', 76, modifiers=self.ORCA | self.SHIFT)
        consumed = repeated.consume[0] if isinstance(repeated.consume, tuple) else repeated.consume
        self.assertTrue(consumed)
        self.assertIsNotNone(repeated._consumer)
        self.assertIsNone(repeated._handler)

    def test_shifted_find_repeats_with_insert_or_caps_in_both_layouts(self):
        for layout in ('desktop', 'laptop'):
            for nvda_vk in (0x2D, 0x14):
                with self.subTest(layout=layout, nvda_vk=nvda_vk), mock.patch.dict(
                        'os.environ', LINUX_RDACCESS_NVDA_LAYOUT=layout):
                    controller, event_class, script = self._hooked()
                    self._key(controller, nvda_vk, True, extended=nvda_vk == 0x2D)
                    self._key(controller, 0xA0, True)
                    for _ in range(2):
                        self._key(controller, 0x72, True)
                        event = event_class('F3', 69, modifiers=self.SHIFT)
                        self.assertIsNotNone(event._consumer)
                        self._consume_deferred(event)
                    self._key(controller, 0x72, False)
                    self._key(controller, 0xA0, False)
                    self._key(controller, nvda_vk, False, extended=nvda_vk == 0x2D)
                    self.assertEqual(script.find_calls, ['previous', 'previous'])
                    self.assertFalse(controller._lrd_forwarded)
                    if nvda_vk == 0x14:
                        self.assertNotIn(('key', 0x14, True, None),
                                         controller.local_machine.events)

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
