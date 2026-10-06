"""Command semantics, key ownership, queued output, and fallback regressions."""
import sys
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class DirectCommandTests(Harness, unittest.TestCase):
    def command(self, controller, vk, *, modifier=0x2D, extended=False):
        self._key(controller, modifier, True, extended=modifier == 0x2D)
        self._key(controller, vk, True, extended=extended)
        self._key(controller, vk, False, extended=extended)
        self._key(controller, modifier, False, extended=modifier == 0x2D)

    def test_current_line_uses_native_command_and_consumes_both_key_edges(self):
        for modifier in (0x2D, 0x14):
            with self.subTest(modifier=modifier):
                controller, _, _ = self._patched_controller()
                calls = []
                controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
                self.command(controller, 0x26, modifier=modifier, extended=True)
                self.assertEqual(calls, [('presentCurrentLine',)])
                keys = [event for event in controller.local_machine.events if event[0] == 'key']
                self.assertFalse(any(event[1] == 0x26 for event in keys))
                if modifier == 0x14:
                    self.assertEqual(keys, [])

    def test_plain_up_keypad_up_and_modified_up_keep_application_input(self):
        for modifier, extended in ((None, True), (0x2D, False), (0xA2, True)):
            with self.subTest(modifier=modifier, extended=extended):
                controller, _, _ = self._patched_controller()
                controller._linux_rdaccess_script_call = mock.Mock()
                if modifier:
                    self._key(controller, modifier, True)
                self._key(controller, 0x26, True, extended=extended)
                self._key(controller, 0x26, False, extended=extended)
                controller._linux_rdaccess_script_call.assert_not_called()
                keys = [event[:3] for event in controller.local_machine.events if event[0] == 'key']
                self.assertIn(('key', 0x26, True), keys)
                self.assertIn(('key', 0x26, False), keys)

    def test_clock_taps_choose_time_then_date_without_injecting_f12(self):
        controller, _, _ = self._patched_controller()
        calls = []
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        for moment in (100.0, 100.2, 100.3, 102.0):
            with mock.patch('time.monotonic', return_value=moment):
                self.command(controller, 0x7B)
        self.assertEqual(calls, [('presentTime',), ('presentDate',), ('presentDate',), ('presentTime',)])
        self.assertFalse(any(event[0] == 'key' and event[1] == 0x7B
                             for event in controller.local_machine.events))

    def test_caps_clock_chord_preserves_lock_and_repeat_is_not_double_tap(self):
        controller, _, _ = self._patched_controller()
        calls = []
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        self._key(controller, 0x14, True)
        self._key(controller, 0x7B, True)
        self._key(controller, 0x7B, True)
        self._key(controller, 0x7B, False)
        self._key(controller, 0x14, False)
        self.assertEqual(calls, [('presentTime',)])
        self.assertFalse(any(event[0] == 'key' for event in controller.local_machine.events))

    def test_queued_clock_callbacks_keep_original_tap_choice(self):
        controller, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        calls = []
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with patches:
            for moment in (100.0, 100.2):
                with mock.patch('time.monotonic', return_value=moment):
                    self.command(controller, 0x7B)
            self.assertEqual(calls, [])
            for callback in queue:
                callback()
        self.assertEqual(calls, [('presentTime',), ('presentDate',)])

    def test_other_action_resets_clock_double_press_count(self):
        controller, _, _ = self._patched_controller()
        calls = []
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with mock.patch('time.monotonic', return_value=100.0):
            self.command(controller, 0x7B)
            self._key(controller, 0x41, True)
            self._key(controller, 0x41, False)
            self.command(controller, 0x7B)
        self.assertEqual(calls, [('presentTime',), ('presentTime',)])

    def test_control_generation_change_resets_clock_double_press_count(self):
        controller, _, _ = self._patched_controller()
        calls = []
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with mock.patch('time.monotonic', return_value=100.0):
            self.command(controller, 0x7B)
            controller.toggle_control()
            controller.toggle_control()
            self.command(controller, 0x7B)
        self.assertEqual(calls, [('presentTime',), ('presentTime',)])

    def test_braille_action_interrupts_clock_double_press_sequence(self):
        controller, _, _ = self._patched_controller()
        calls = []
        controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with mock.patch('time.monotonic', return_value=100.0):
            self.command(controller, 0x7B)
            controller._linux_rdaccess_handle_braille_input({
                'scriptPath': ['globalCommands', 'GlobalCommands', 'braille_scrollForward']})
            self.command(controller, 0x7B)
        self.assertEqual(calls, [('presentTime',), ('panBrailleRight',), ('presentTime',)])

    def test_plain_or_control_modified_f12_is_forwarded(self):
        for modifier in (None, 0xA2):
            controller, _, _ = self._patched_controller()
            controller._linux_rdaccess_script_call = mock.Mock()
            if modifier:
                self._key(controller, modifier, True)
            self._key(controller, 0x7B, True)
            self._key(controller, 0x7B, False)
            controller._linux_rdaccess_script_call.assert_not_called()
            self.assertIn(('key', 0x7B, True), [event[:3] for event in controller.local_machine.events])

    def test_extra_modifiers_keep_nvda_up_and_f12_for_the_application(self):
        for vk, extended in ((0x26, True), (0x7B, False)):
            for extra in (0xA0, 0xA2, 0xA4, 0x5B):
                with self.subTest(vk=vk, extra=extra):
                    controller, _, _ = self._patched_controller()
                    controller._linux_rdaccess_script_call = mock.Mock()
                    self._key(controller, 0x2D, True, extended=True)
                    self._key(controller, extra, True)
                    self._key(controller, vk, True, extended=extended)
                    self._key(controller, vk, False, extended=extended)
                    controller._linux_rdaccess_script_call.assert_not_called()
                    keys = [event[:3] for event in controller.local_machine.events if event[0] == 'key']
                    self.assertIn(('key', vk, True), keys)
                    self.assertIn(('key', vk, False), keys)


class AdapterResultTests(Harness, unittest.TestCase):
    def modules(self, adapter, script):
        module = types.ModuleType('linux_rdaccess_orca_adapter')
        module.OrcaRuntimeAdapter = adapter
        orca = types.ModuleType('orca')
        orca.orca_state = types.SimpleNamespace(activeScript=script)
        return mock.patch.dict(sys.modules, {'linux_rdaccess_orca_adapter': module, 'orca': orca})

    def test_declined_supported_command_is_never_retried(self):
        controller, _, _ = self._patched_controller()
        primary = mock.Mock(return_value=False)
        fallback = mock.Mock()
        with self.modules(types.SimpleNamespace(say_all=primary), types.SimpleNamespace(sayAll=fallback)):
            self.assertIs(controller._linux_rdaccess_script_call('sayAll'), False)
        primary.assert_called_once_with()
        fallback.assert_not_called()

    def test_unsupported_command_uses_legacy_handler_once(self):
        controller, _, _ = self._patched_controller()
        fallback = mock.Mock(return_value=True)
        with self.modules(types.SimpleNamespace(present_time=lambda: None), types.SimpleNamespace(presentTime=fallback)):
            self.assertTrue(controller._linux_rdaccess_script_call('presentTime'))
        fallback.assert_called_once_with(None)

    def test_command_failure_after_side_effect_never_retries_legacy_handler(self):
        for error in (ImportError, RuntimeError):
            with self.subTest(error=error):
                controller, _, _ = self._patched_controller()
                calls = []
                def primary():
                    calls.append('primary')
                    raise error('handler failed')
                fallback = mock.Mock()
                with self.modules(types.SimpleNamespace(say_all=primary), types.SimpleNamespace(sayAll=fallback)):
                    self.assertFalse(controller._linux_rdaccess_script_call('sayAll'))
                self.assertEqual(calls, ['primary'])
                fallback.assert_not_called()

    def test_legacy_mode_toggle_is_a_manual_command_event(self):
        controller, _, _ = self._patched_controller()
        fallback = mock.Mock(return_value=True)
        with self.modules(types.SimpleNamespace(), types.SimpleNamespace(togglePresentationMode=fallback)):
            self.assertTrue(controller._linux_rdaccess_script_call('togglePresentationMode'))
        event = fallback.call_args.args[0]
        self.assertTrue(event)
        self.assertEqual((event.type, event.event_string), ('keyboard', 'space'))

    def test_legacy_current_line_uses_caret_object_without_review_or_movement(self):
        controller, _, _ = self._patched_controller()
        target = object()
        handler = mock.Mock()
        utilities = types.SimpleNamespace(getCaretContext=lambda: (target, 7))
        with self.modules(types.SimpleNamespace(), types.SimpleNamespace(utilities=utilities, sayLine=handler)):
            self.assertTrue(controller._linux_rdaccess_script_call('presentCurrentLine'))
        handler.assert_called_once_with(target)

    def test_legacy_current_line_reads_focused_browser_chrome_instead_of_stale_page(self):
        controller, _, _ = self._patched_controller()
        focus, page = object(), object()
        handler = mock.Mock()
        getter = mock.Mock(return_value=(page, 7))
        predicate = mock.Mock(return_value=False)
        utilities = types.SimpleNamespace(getCaretContext=getter, inDocumentContent=predicate)
        script = types.SimpleNamespace(utilities=utilities, sayLine=handler)
        with self.modules(types.SimpleNamespace(), script):
            sys.modules['orca'].orca_state.locusOfFocus = focus
            self.assertTrue(controller._linux_rdaccess_script_call('presentCurrentLine'))
        predicate.assert_called_once_with(focus)
        getter.assert_not_called()
        handler.assert_called_once_with(focus)

    def test_declined_structural_list_never_resynthesizes_shortcut(self):
        controller, _, _ = self._patched_controller()
        primary = mock.Mock(return_value=False)
        controller._linux_rdaccess_send_structural_list = mock.Mock()
        with self.modules(types.SimpleNamespace(show_structural_list=primary), types.SimpleNamespace()):
            controller._linux_rdaccess_open_structural_list('h', None)
        primary.assert_called_once_with('h')
        controller._linux_rdaccess_send_structural_list.assert_not_called()

    def test_unsupported_structural_list_keeps_verified_fallback(self):
        controller, _, _ = self._patched_controller()
        controller._linux_rdaccess_send_structural_list = mock.Mock()
        with self.modules(types.SimpleNamespace(show_structural_list=lambda key: None), types.SimpleNamespace()):
            controller._linux_rdaccess_open_structural_list('h', None)
        controller._linux_rdaccess_send_structural_list.assert_called_once_with('h', None)

    def test_native_list_failure_after_side_effect_never_resynthesizes_keys(self):
        for error in (ImportError, RuntimeError):
            with self.subTest(error=error):
                controller, _, _ = self._patched_controller()
                calls = []
                def primary(key):
                    calls.append(key)
                    raise error('handler failed')
                controller._linux_rdaccess_send_structural_list = mock.Mock()
                with self.modules(types.SimpleNamespace(show_structural_list=primary), types.SimpleNamespace()):
                    controller._linux_rdaccess_open_structural_list('h', None)
                self.assertEqual(calls, ['h'])
                controller._linux_rdaccess_send_structural_list.assert_not_called()

    def test_chooser_failure_after_opening_list_never_opens_another_list(self):
        controller, _, _ = self._patched_controller()
        calls = []
        def chooser(open_list):
            open_list('t')
            raise ImportError('handler failed')
        module = types.ModuleType('linux_rdaccess_orca_adapter')
        module.show_elements_list = chooser
        controller._linux_rdaccess_open_structural_list = lambda *args: calls.append(args)
        with mock.patch.dict(sys.modules, {'linux_rdaccess_orca_adapter': module}):
            controller._linux_rdaccess_show_elements_list(None)
        self.assertEqual(calls, [('t', None)])
