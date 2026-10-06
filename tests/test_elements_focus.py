"""Modal chooser focus must restore before Orca creates its native list GUI."""
import sys
import types
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class ElementsFocusTests(Harness, unittest.TestCase):
    def setup_context(self, *, chooser=True, timer_result=1):
        controller, _, _ = self._patched_controller()
        self.document = object()
        origin = types.SimpleNamespace(utilities=types.SimpleNamespace(
            documentFrame=lambda: self.document))
        window = object()
        state = types.SimpleNamespace(activeScript=origin, activeWindow=window)
        orca = types.ModuleType('orca')
        orca.orca_state = state
        queue, calls = [], []
        controller._linux_rdaccess_open_structural_list = (
            lambda *args: calls.append((args, state.activeScript, state.activeWindow)))
        repository = types.ModuleType('gi.repository')
        def schedule(interval, callback):
            self.assertEqual(interval, 25)
            if timer_result:
                queue.append(callback)
            return timer_result
        repository.GLib = types.SimpleNamespace(timeout_add=schedule)
        gi = types.ModuleType('gi')
        gi.repository = repository
        adapter = types.ModuleType('linux_rdaccess_orca_adapter')
        def show(open_list):
            if chooser:
                state.activeScript = object()
                state.activeWindow = object()
                open_list('t')
                return True
            return None
        adapter.show_elements_list = show
        patches = mock.patch.dict(sys.modules, {
            'orca': orca, 'gi': gi, 'gi.repository': repository,
            'linux_rdaccess_orca_adapter': adapter})
        return controller, state, origin, window, queue, calls, patches

    def test_selection_waits_for_both_original_script_and_window(self):
        c, state, origin, window, queue, calls, patches = self.setup_context()
        with patches:
            c._linux_rdaccess_show_elements_list(None)
            self.assertEqual(calls, [])
            self.assertEqual(len(queue), 1)
            self.assertTrue(queue[0]())
            state.activeScript = origin
            self.assertTrue(queue[0]())
            state.activeWindow = window
            self.assertFalse(queue[0]())
        self.assertEqual(calls, [(('t', None), origin, window)])

    def test_changed_document_never_opens_list_or_injects_fallback(self):
        c, state, origin, window, queue, calls, patches = self.setup_context()
        with patches:
            c._linux_rdaccess_show_elements_list(None)
            state.activeScript, state.activeWindow = origin, window
            self.document = object()
            self.assertFalse(queue[0]())
        self.assertEqual(calls, [])
        self.assertEqual(c.local_machine.events, [])

    def test_handoff_expires_waiting_selection(self):
        c, state, origin, window, queue, calls, patches = self.setup_context()
        with patches:
            c._linux_rdaccess_show_elements_list(None)
            c.toggle_control()
            state.activeScript, state.activeWindow = origin, window
            self.assertFalse(queue[0]())
        self.assertEqual(calls, [])

    def test_new_chooser_expires_previous_waiting_selection(self):
        c, state, origin, window, queue, calls, patches = self.setup_context()
        with patches:
            c._linux_rdaccess_show_elements_list(None)
            state.activeScript, state.activeWindow = origin, window
            c._linux_rdaccess_show_elements_list(None)
            state.activeScript, state.activeWindow = origin, window
            self.assertFalse(queue[0]())
            self.assertFalse(queue[1]())
        self.assertEqual(calls, [(('t', None), origin, window)])

    def test_focus_wait_is_bounded_and_never_sends_keys_to_another_window(self):
        c, _, _, _, queue, calls, patches = self.setup_context()
        with patches:
            c._linux_rdaccess_show_elements_list(None)
            for _ in range(79):
                self.assertTrue(queue[0]())
            self.assertFalse(queue[0]())
        self.assertEqual(calls, [])
        self.assertEqual(c.local_machine.events, [])

    def test_failed_scheduling_does_not_use_unsafe_immediate_fallback(self):
        c, _, _, _, queue, calls, patches = self.setup_context(timer_result=0)
        with patches:
            c._linux_rdaccess_show_elements_list(None)
        self.assertEqual(queue, [])
        self.assertEqual(calls, [])

    def test_delayed_first_callback_expires_even_if_origin_has_restored(self):
        c, state, origin, window, queue, calls, patches = self.setup_context()
        with patches:
            with mock.patch('time.monotonic', return_value=100.0):
                c._linux_rdaccess_show_elements_list(None)
            state.activeScript, state.activeWindow = origin, window
            with mock.patch('time.monotonic', return_value=102.1):
                self.assertFalse(queue[0]())
        self.assertEqual(calls, [])

    def test_unavailable_chooser_uses_headings_after_origin_check(self):
        c, _, origin, window, queue, calls, patches = self.setup_context(chooser=False)
        with patches:
            c._linux_rdaccess_show_elements_list(None)
            self.assertEqual(calls, [])
            self.assertFalse(queue[0]())
        self.assertEqual(calls, [(('h', None), origin, window)])

    def test_reentrant_f7_cannot_use_active_chooser_as_its_origin(self):
        c, state, origin, window, queue, calls, patches = self.setup_context()
        dialogs = []
        def show(open_list):
            dialogs.append('chooser')
            state.activeScript, state.activeWindow = object(), object()
            c._linux_rdaccess_show_elements_list(None)
            open_list('t')
            return True
        with patches:
            sys.modules['linux_rdaccess_orca_adapter'].show_elements_list = show
            c._linux_rdaccess_show_elements_list(None)
            self.assertFalse(c._lrd_elements_dialog_active)
            state.activeScript, state.activeWindow = origin, window
            self.assertFalse(queue[0]())
        self.assertEqual(dialogs, ['chooser'])
        self.assertEqual(calls, [(('t', None), origin, window)])

    def test_chooser_exception_releases_reentrancy_guard(self):
        c, _, _, _, _, calls, patches = self.setup_context()
        def show(open_list):
            raise RuntimeError('dialog failed')
        with patches:
            sys.modules['linux_rdaccess_orca_adapter'].show_elements_list = show
            c._linux_rdaccess_show_elements_list(None)
        self.assertFalse(c._lrd_elements_dialog_active)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
