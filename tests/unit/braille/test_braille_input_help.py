"""Remote raw braille commands preserve Orca's native help preferences."""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import orca_adapter
from tests.shared.test_compat_lifecycle import Harness
from tests.unit.accessibility.test_a11y_model import FakeAccessible


class BrailleInputHelpTests(Harness, unittest.TestCase):
    COMMANDS = {
        'route': ('braille_routeTo', 'processRoutingKey', 'processRoutingKeyHandler'),
        'home': ('braille_toFocus', 'goBrailleHome', 'goBrailleHomeHandler'),
        'left': ('braille_scrollBack', 'panBrailleLeft', 'panBrailleLeftHandler'),
        'right': ('braille_scrollForward', 'panBrailleRight', 'panBrailleRightHandler'),
    }

    def runtime(self, *, learn=True, snake=False):
        c, _, _ = self._patched_controller(inline=False)
        methods = {method: mock.Mock(return_value=True) for _, method, _ in self.COMMANDS.values()}
        present = mock.Mock()
        handlers = {
            name: types.SimpleNamespace(description='Localized ' + name,
                                         learnModeEnabled=kind in ('route', 'home'))
            for kind, (_, _, name) in self.COMMANDS.items()
        }
        script = types.SimpleNamespace(**methods, presentMessage=present, inputEventHandlers=handlers)
        state = types.SimpleNamespace(activeScript=script, activeWindow=object(),
                                      locusOfFocus=FakeAccessible('Control', 'push button'),
                                      learnModeEnabled=learn)
        if snake:
            script.present_message, script.input_event_handlers = present, handlers
            del script.presentMessage, script.inputEventHandlers
            state.active_script, state.learn_mode_enabled = script, learn
            del state.activeScript, state.learnModeEnabled
        orca = types.ModuleType('orca')
        orca.orca_state = state
        braille = types.ModuleType('orca.braille')
        braille._displaySize = [32, 1]
        orca.braille = braille
        queue, glib = self._fake_glib()
        for patch in (glib, mock.patch.dict(sys.modules, {
                'orca': orca, 'orca.orca_state': state, 'orca.braille': braille,
                'linux_rdaccess_orca_adapter': orca_adapter})):
            patch.start()
            self.addCleanup(patch.stop)
        c.local_machine.cancel_speech = mock.Mock()
        c._linux_rdaccess_sync_state()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        return c, script, state, queue, methods, handlers, present

    def send(self, c, kind):
        name, _, _ = self.COMMANDS[kind]
        c._on_remote_braille_input(scriptPath=['globalCommands', 'GlobalCommands', name],
                                  **({'routingIndex': 4} if kind == 'route' else {}))

    @staticmethod
    def drain(queue):
        while queue:
            queue.pop(0)()

    def test_routing_and_home_present_help_without_moving_focus_or_caret(self):
        for kind in ('route', 'home'):
            with self.subTest(kind=kind):
                c, _, _, queue, methods, _, present = self.runtime()
                self.send(c, kind)
                present.assert_not_called()
                self.drain(queue)
                present.assert_called_once_with('Localized ' + self.COMMANDS[kind][2])
                for method in methods.values():
                    method.assert_not_called()
                c.local_machine.cancel_speech.assert_called_once_with()
                self.assertEqual(c.transport.sent, ['cancel'])
                self.assertEqual(getattr(c, '_lrd_braille_route_epoch', 0), 0)

    def test_help_request_cannot_execute_after_help_ends_before_dispatch(self):
        for kind in ('route', 'home'):
            with self.subTest(kind=kind):
                c, _, state, queue, methods, _, present = self.runtime()
                self.send(c, kind)
                state.learnModeEnabled = False
                self.drain(queue)
                methods[self.COMMANDS[kind][1]].assert_not_called()
                present.assert_not_called()
                c.local_machine.cancel_speech.assert_not_called()
                self.assertEqual(c.transport.sent, [])

    def test_help_started_before_dispatch_prevents_a_real_command(self):
        for kind in ('route', 'home'):
            with self.subTest(kind=kind):
                c, _, state, queue, methods, _, present = self.runtime(learn=False)
                self.send(c, kind)
                state.learnModeEnabled = True
                self.drain(queue)
                methods[self.COMMANDS[kind][1]].assert_not_called()
                present.assert_called_once_with('Localized ' + self.COMMANDS[kind][2])

    def test_native_panning_exception_and_custom_help_preferences_are_preserved(self):
        for kind in ('left', 'right'):
            for enabled in (False, True):
                with self.subTest(kind=kind, enabled=enabled):
                    c, _, _, queue, methods, handlers, present = self.runtime()
                    handlers[self.COMMANDS[kind][2]].learnModeEnabled = enabled
                    self.send(c, kind)
                    self.drain(queue)
                    if enabled:
                        methods[self.COMMANDS[kind][1]].assert_not_called()
                        present.assert_called_once_with('Localized ' + self.COMMANDS[kind][2])
                    else:
                        methods[self.COMMANDS[kind][1]].assert_called_once_with(None)
                        present.assert_not_called()
                    c.local_machine.cancel_speech.assert_not_called()
                    self.assertEqual(c.transport.sent, [])

    def test_routing_and_home_can_execute_when_native_handler_exempts_help(self):
        for kind in ('route', 'home'):
            with self.subTest(kind=kind):
                c, _, _, queue, methods, handlers, present = self.runtime()
                handlers[self.COMMANDS[kind][2]].learnModeEnabled = False
                self.send(c, kind)
                self.drain(queue)
                self.assertEqual(methods[self.COMMANDS[kind][1]].call_count, 1)
                present.assert_not_called()
                self.assertEqual(c.transport.sent, ['cancel'])

    def test_missing_help_metadata_never_turns_routing_or_home_into_an_action(self):
        for kind in ('route', 'home'):
            for missing in ('handler', 'description', 'presenter'):
                with self.subTest(kind=kind, missing=missing):
                    c, script, _, queue, methods, handlers, present = self.runtime()
                    if missing == 'handler':
                        handlers.clear()
                    elif missing == 'description':
                        handlers[self.COMMANDS[kind][2]].description = ''
                    else:
                        script.presentMessage = None
                    self.send(c, kind)
                    self.drain(queue)
                    methods[self.COMMANDS[kind][1]].assert_not_called()
                    present.assert_not_called()
                    c.local_machine.cancel_speech.assert_not_called()
                    self.assertEqual(c.transport.sent, [])

    def test_obsolete_help_never_presents_or_operates_in_another_context(self):
        for change in ('handoff', 'disconnect', 'script', 'window', 'focus'):
            with self.subTest(change=change):
                c, _, state, queue, methods, _, present = self.runtime()
                self.send(c, 'route')
                if change == 'handoff':
                    c.toggle_control()
                elif change == 'disconnect':
                    c.transport.connected = False
                else:
                    setattr(state, {'script': 'activeScript', 'window': 'activeWindow',
                                    'focus': 'locusOfFocus'}[change], object())
                self.drain(queue)
                methods['processRoutingKey'].assert_not_called()
                present.assert_not_called()
                c.local_machine.cancel_speech.assert_not_called()
                self.assertEqual(c.transport.sent, [])

    def test_snake_case_help_and_fresh_commands_after_exit(self):
        c, _, state, queue, methods, _, present = self.runtime(snake=True)
        self.send(c, 'home')
        self.drain(queue)
        present.assert_called_once_with('Localized goBrailleHomeHandler')
        methods['goBrailleHome'].assert_not_called()
        state.learn_mode_enabled = False
        self.send(c, 'home')
        self.drain(queue)
        methods['goBrailleHome'].assert_called_once_with(None)
        self.assertEqual(c.transport.sent, ['cancel', 'cancel'])

    def test_help_is_preserved_when_the_adapter_cannot_be_imported(self):
        for kind in ('route', 'home'):
            with self.subTest(kind=kind):
                c, _, _, queue, methods, _, present = self.runtime()
                with mock.patch.dict(sys.modules, {'linux_rdaccess_orca_adapter': None}):
                    self.send(c, kind)
                    self.drain(queue)
                methods[self.COMMANDS[kind][1]].assert_not_called()
                present.assert_called_once_with('Localized ' + self.COMMANDS[kind][2])
                self.assertEqual(c.transport.sent, ['cancel'])
