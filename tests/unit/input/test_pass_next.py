"""Remote pass-next delivery with delayed Orca flag and keyboard processing."""
from __future__ import annotations

import sys
import ast
from pathlib import Path
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness
from tests import test_remote_access as fixtures


class PassNextTests(Harness, unittest.TestCase):
    SHIFT, CTRL, ALT, ORCA = 1, 4, 8, 256
    M_CODE, D_CODE = 58, 40
    LEFT, RIGHT, UP, DOWN, KP_DOWN = 113, 114, 111, 116, 88
    _orca_env = fixtures.LegacyConfigTests._orca_env
    _hooked = fixtures.LegacyConfigTests._hooked

    def environment(self, queued=False):
        controller, keyboard_event, script = self._hooked()
        state = types.SimpleNamespace(bypassNextCommand=False, activeScript=script)
        sys.modules['orca'].orca_state = state
        script.addKeyGrabs = mock.Mock()
        calls = []

        def command(method, *args):
            calls.append(method)
            if method == 'bypassNextCommand':
                state.bypassNextCommand = True
            return True

        controller._linux_rdaccess_script_call = command
        queue = []
        if queued:
            controller._linux_rdaccess_run_main = queue.append
        return controller, keyboard_event, script, state, calls, queue

    def arm(self, controller, release_modifier=True):
        self._key(controller, 0x2D, True, extended=True)
        self._key(controller, 0x71, True)
        self._key(controller, 0x71, False)
        if release_modifier:
            self._key(controller, 0x2D, False, extended=True)

    @staticmethod
    def drain(queue):
        while queue:
            queue.pop(0)()

    def assertPassed(self, event):
        consumed = event.consume[0] if isinstance(event.consume, tuple) else event.consume
        self.assertFalse(consumed)
        self.assertIsNone(event._handler)

    @staticmethod
    def pending_claims(controller):
        return [token for token in controller._module._LRD_BYPASS['pending']
                if token[3] is not None]

    def test_raw_d_reaches_application_before_activation_callback(self):
        c, KE, _script, state, calls, queue = self.environment(queued=True)
        self.arm(c)
        self._key(c, 0x44, True)
        self.assertPassed(KE('d', self.D_CODE))
        self.drain(queue)
        self.assertNotIn('bypassNextCommand', calls)
        self.assertFalse(state.bypassNextCommand)

    def test_name_only_modifier_does_not_use_up_pass_next_gesture(self):
        for name in ("Shift_L", "Control_L", "Alt_L"):
            with self.subTest(name=name):
                c, KE, _script, _state, _calls, queue = self.environment(queued=True)
                self.arm(c)
                c._on_remote_key(key_name=name, pressed=True)
                self.assertTrue(c._lrd_bypass_next)
                self.assertFalse(c._lrd_bypass_request["used"])
                self._key(c, 0x44, True)
                self.assertPassed(KE("d", self.D_CODE))
                self._key(c, 0x44, False)
                self.assertPassed(KE("d", self.D_CODE, pressed=False))
                c._on_remote_key(key_name=name, pressed=False)
                self.drain(queue)
                self.assertFalse(c._lrd_forwarded)

    def test_only_one_gesture_passes_while_native_flag_is_still_armed(self):
        c, KE, script, state, calls, _queue = self.environment()
        self.arm(c, release_modifier=False)
        self.assertTrue(state.bypassNextCommand)
        self._key(c, 0x20, True)
        self._key(c, 0x20, False)
        # The first native event has not been constructed/processed yet.
        self.assertTrue(state.bypassNextCommand)
        self._key(c, 0x54, True)
        self.assertIn('presentTitle', calls)
        self.assertNotIn(('key', 0x54, True, None), c.local_machine.events)
        import orca.keybindings as bindings
        old = bindings.getKeycode
        bindings.getKeycode = lambda name: 65 if name == 'space' else old(name)
        self.assertPassed(KE('space', 65, modifiers=self.ORCA))
        self.assertFalse(state.bypassNextCommand)
        script.addKeyGrabs.assert_called_once()

    def test_repeats_and_release_remain_raw_after_new_commands(self):
        c, KE, _script, _state, _calls, queue = self.environment(queued=True)
        self.arm(c)
        self._key(c, 0x44, True)
        self._key(c, 0x44, True)
        self._key(c, 0x44, False)
        self._key(c, 0x44, True)
        for pressed in (True, True, False):
            self.assertPassed(KE('d', self.D_CODE, pressed=pressed))
        self.assertEqual(KE('d', self.D_CODE)._handler.function, 'landmark_next')
        self.assertEqual(c._lrd_bypass_keys, {})
        self.drain(queue)

    def test_failed_first_injection_keeps_request_for_next_delivered_key(self):
        for failure in (False, RuntimeError('backend unavailable')):
            with self.subTest(failure=type(failure).__name__):
                c, KE, _script, state, _calls, _queue = self.environment()
                self.arm(c)
                backend = c.local_machine.send_key
                c.local_machine.send_key = mock.Mock(return_value=failure)
                if isinstance(failure, Exception):
                    c.local_machine.send_key.side_effect = failure
                self._key(c, 0x44, True)
                self.assertTrue(c._lrd_bypass_next)
                self.assertFalse(c._lrd_bypass_request['used'])
                self.assertEqual(self.pending_claims(c), [])
                self.assertEqual(c._lrd_bypass_keys, {})
                c.local_machine.send_key = backend
                self._key(c, 0x44, True)
                self.assertPassed(KE('d', self.D_CODE))
                self.assertFalse(state.bypassNextCommand)

    def test_failed_repeat_does_not_grant_a_second_bypass_gesture(self):
        c, KE, _script, _state, calls, _queue = self.environment()
        self.arm(c, release_modifier=False)
        self._key(c, 0x44, True)
        backend = c.local_machine.send_key
        c.local_machine.send_key = mock.Mock(return_value=False)
        self._key(c, 0x44, True)
        c.local_machine.send_key = backend
        self._key(c, 0x54, True)
        self.assertIn('presentTitle', calls)
        self.assertPassed(KE('d', self.D_CODE, modifiers=self.ORCA))
        self.assertEqual(self.pending_claims(c), [])

    def test_key_resolver_exception_preserves_unconsumed_request(self):
        c, KE, _script, _state, _calls, _queue = self.environment()
        self.arm(c)
        c.local_machine._resolve_key = mock.Mock(side_effect=RuntimeError('backend unavailable'))
        self._key(c, 0x44, True)
        self.assertTrue(c._lrd_bypass_next)
        self.assertFalse(c._lrd_bypass_request['used'])
        self.assertEqual(self.pending_claims(c), [])
        del c.local_machine._resolve_key
        self._key(c, 0x44, True)
        self.assertPassed(KE('d', self.D_CODE))

    def test_failed_release_retains_original_release_ownership(self):
        c, KE, _script, _state, _calls, _queue = self.environment()
        self.arm(c)
        self._key(c, 0x44, True)
        self.assertPassed(KE('d', self.D_CODE))
        backend = c.local_machine.send_key
        c.local_machine.send_key = mock.Mock(return_value=False)
        self._key(c, 0x44, False)
        self.assertIn((0x44, False), c._lrd_bypass_keys)
        self.assertIn((0x44, False), c._lrd_forwarded)
        self.assertEqual(self.pending_claims(c), [])
        c.local_machine.send_key = backend
        self._key(c, 0x44, False)
        self.assertPassed(KE('d', self.D_CODE, pressed=False))
        self.assertEqual(c._lrd_bypass_keys, {})
        self.assertEqual(c._lrd_forwarded, {})

    def test_native_claim_is_published_before_backend_dispatch(self):
        c, KE, _script, state, _calls, queue = self.environment(queued=True)
        self.arm(c)
        backend = c.local_machine.send_key

        def dispatch(**payload):
            if payload['vk_code'] == 0x44:
                self.assertPassed(KE('d', self.D_CODE, pressed=payload['pressed']))
            return backend(**payload)

        c.local_machine.send_key = dispatch
        self._key(c, 0x44, True)
        self._key(c, 0x44, False)
        self.drain(queue)
        self.assertFalse(state.bypassNextCommand)

    def test_queued_normal_d_cannot_take_a_later_bypass_d_claim(self):
        c, KE, _script, state, _calls, queue = self.environment(queued=True)
        self._key(c, 0x44, True)
        self._key(c, 0x44, False)
        self.arm(c)
        self._key(c, 0x44, True)
        self.assertEqual(KE('d', self.D_CODE)._handler.function, 'landmark_next')
        self.assertEqual(KE('d', self.D_CODE, pressed=False)._handler.function, 'landmark_next')
        self.assertPassed(KE('d', self.D_CODE))
        self.drain(queue)
        self.assertFalse(state.bypassNextCommand)

    def test_bypassed_repeat_clears_prior_structural_release_identity(self):
        c, KE, _script, _state, _calls, _queue = self.environment(queued=True)
        self._key(c, 0x44, True)
        self.assertEqual(KE('d', self.D_CODE)._handler.function, 'landmark_next')
        self.arm(c)
        self._key(c, 0x44, True)
        self.assertPassed(KE('d', self.D_CODE))
        self.assertFalse(c._module._LRD_D['swapped'])
        self._key(c, 0x44, False)
        self.assertPassed(KE('d', self.D_CODE, pressed=False))

    def test_normal_forward_rejection_removes_only_its_native_fifo_token(self):
        for failure in (False, RuntimeError('backend unavailable')):
            with self.subTest(failure=type(failure).__name__):
                c, KE, _script, _state, _calls, _queue = self.environment()
                self._key(c, 0x44, True)
                initial = list(c._module._LRD_BYPASS['pending'])
                c.local_machine.send_key = mock.Mock(return_value=failure)
                if isinstance(failure, Exception):
                    c.local_machine.send_key.side_effect = failure
                self._key(c, 0x27, True, extended=True)
                self.assertEqual(c._module._LRD_BYPASS['pending'], initial)
                self.assertEqual(KE('d', self.D_CODE)._handler.function, 'landmark_next')

    def test_native_fifo_is_bounded_for_all_forwarded_keyboard_events(self):
        c, _KE, _script, _state, _calls, _queue = self.environment()
        for _ in range(c._module._LRD_BYPASS_MAX_PENDING + 5):
            self._key(c, 0x41, True)
        self.assertEqual(len(c._module._LRD_BYPASS['pending']), c._module._LRD_BYPASS_MAX_PENDING)

    def test_handoff_clears_owned_native_flag_and_cannot_rearm_old_request(self):
        c, _KE, script, state, _calls, _queue = self.environment()
        self.arm(c)
        old = c._lrd_bypass_request
        c.toggle_control()
        self.assertFalse(state.bypassNextCommand)
        script.addKeyGrabs.assert_called_once()
        self.assertFalse(c._linux_rdaccess_activate_bypass(old))
        self.assertEqual(c._module._LRD_BYPASS['pending'], [])

    def test_used_request_callback_does_not_activate_a_new_request(self):
        c, _KE, _script, state, calls, queue = self.environment(queued=True)
        self.arm(c)
        old = c._lrd_bypass_request
        self._key(c, 0x44, True)
        self._key(c, 0x44, False)
        self.arm(c)
        new = c._lrd_bypass_request
        self.assertIsNot(new, old)
        self.drain(queue)
        self.assertEqual(calls.count('bypassNextCommand'), 1)
        self.assertIs(c._module._LRD_BYPASS['owner'], new)
        self.assertTrue(state.bypassNextCommand)

    def test_external_orca_bypass_is_preserved_and_cleanup_restores_grabs(self):
        c, KE, script, state, calls, _queue = self.environment()
        state.bypassNextCommand = True
        self._key(c, 0x44, True)
        self.assertPassed(KE('d', self.D_CODE))
        self.assertFalse(state.bypassNextCommand)
        script.addKeyGrabs.assert_called_once()
        self.assertNotIn('bypassNextCommand', calls)
        # A subsequent independently armed local request still bypasses.
        self._key(c, 0x44, False)
        self.assertPassed(KE('d', self.D_CODE, pressed=False))
        state.bypassNextCommand = True
        self._key(c, 0x44, True)
        self.assertPassed(KE('d', self.D_CODE))
        self.assertEqual(script.addKeyGrabs.call_count, 2)

    def test_handoff_preserves_unrelated_local_native_bypass(self):
        c, _KE, script, state, _calls, _queue = self.environment()
        state.bypassNextCommand = True
        self._key(c, 0x44, True)
        c.toggle_control()
        self.assertTrue(state.bypassNextCommand)
        script.addKeyGrabs.assert_not_called()

    def test_installed_orca_event_processor_passes_claimed_key_in_both_orders(self):
        source_path = Path('/usr/lib/python3/dist-packages/orca/input_event.py')
        if not source_path.exists():
            self.skipTest('installed Orca source unavailable')
        source = source_path.read_text()
        tree = ast.parse(source)
        event_class = next(node for node in tree.body
                           if isinstance(node, ast.ClassDef) and node.name == 'KeyboardEvent')
        methods = [node for node in event_class.body if isinstance(node, ast.FunctionDef)
                   and node.name in ('shouldConsume', '_process')]
        if len(methods) != 2:
            self.skipTest('installed Orca has a different event processor API')
        for queued in (True, False):
            with self.subTest(activation_queued=queued):
                c, _KE, script, state, _calls, queue = self.environment(queued=queued)
                state.capturingKeys = False
                state.learnModeEnabled = False
                state.listNotificationsModeEnabled = False
                script.consumesKeyboardEvent = lambda event: bool(script.keyBindings.getInputHandler(event))
                namespace = {'orca_state': state, 'GLib': types.SimpleNamespace(timeout_add=mock.Mock())}
                exec(compile(ast.Module(body=methods, type_ignores=[]), str(source_path), 'exec'), namespace)

                class NativeEvent:
                    shouldConsume = namespace['shouldConsume']
                    _process = namespace['_process']

                    def __init__(self, pressed):
                        self.timestamp = 1
                        self._script = script
                        self.is_duplicate = self._bypassOrca = False
                        self.hw_code, self.modifiers, self.event_string = self.D_CODE, 0, 'd'
                        self._handler = self._consumer = None
                        self._pressed = pressed
                        self._should_consume, self._consume_reason = self.shouldConsume()

                    D_CODE = self.D_CODE
                    isPressedKey = lambda self: self._pressed
                    _getUserHandler = lambda self: None
                    _isReleaseForLastNonModifierKeyEvent = lambda self: False
                    isModifierKey = lambda self: False
                    isOrcaModifier = lambda self: False
                    getClickCount = lambda self: 1
                    _present = lambda self: None

                sys.modules['orca.input_event'].KeyboardEvent = NativeEvent
                self.assertTrue(c._module._lrd_install_orca_hook())
                # A normal gesture was already queued before pass-next. Native
                # FIFO ownership must keep its handler ahead of the bypass.
                self._key(c, 0x44, True)
                self._key(c, 0x44, False)
                self.arm(c)
                self._key(c, 0x44, True)
                self._key(c, 0x44, False)
                earlier = NativeEvent(True)
                self.assertTrue(earlier._should_consume)
                self.assertEqual(earlier._handler.function, 'landmark_next')
                NativeEvent(False)
                for pressed in (True, False):
                    event = NativeEvent(pressed)
                    self.assertFalse(event._should_consume)
                    self.assertFalse(event._process()[0])
                self.drain(queue)
                self.assertFalse(state.bypassNextCommand)


if __name__ == '__main__':
    unittest.main()
