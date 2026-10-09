"""Braille routing and return-to-focus must interrupt remote Say All."""

from pathlib import Path
import sys
from types import MethodType, ModuleType, SimpleNamespace
import unittest
from unittest import mock

import orca_adapter
from tests.shared.test_compat_lifecycle import Harness
from tests.unit.accessibility import test_say_all_presentation_lifetime as presentation


class BrailleRoutingSpeechTests(Harness, unittest.TestCase):
    native = presentation.SayAllPresentationLifetimeTests.native
    hooked = presentation.SayAllPresentationLifetimeTests.hooked
    runtime = presentation.SayAllPresentationLifetimeTests.runtime
    start = presentation.SayAllPresentationLifetimeTests.start
    drain_native = staticmethod(presentation.SayAllPresentationLifetimeTests.drain)

    def make(self):
        c, _, _ = self._patched_controller(inline=False)
        namespace, server, idle, messages, state, script, contexts, text, orca_api = self.runtime()
        namespace["controller"] = c
        c.local_machine.cancel_speech = mock.Mock(side_effect=lambda: namespace["old_stop"](server))
        script.processRoutingKey = mock.Mock(side_effect=lambda event:
            text.setCaretOffset(event.event["argument"]))
        script.panBrailleRight = mock.Mock()
        braille = ModuleType("orca.braille")
        braille._displaySize = [32, 1]
        orca = ModuleType("orca")
        orca.orca_state, orca.braille = state, braille
        patches = mock.patch.dict(sys.modules, {
            "orca": orca, "orca.orca_state": state, "orca.braille": braille,
            "linux_rdaccess_orca_adapter": orca_adapter,
        })
        queue, glib = self._fake_glib()
        patches.start()
        glib.start()
        self.addCleanup(patches.stop)
        self.addCleanup(glib.stop)
        c._linux_rdaccess_sync_state()
        return c, server, idle, messages, state, script, contexts, text, queue, braille

    @staticmethod
    def route(c, index=9, **kwargs):
        c._on_remote_braille_input(scriptPath=[
            "globalCommands", "GlobalCommands", "braille_routeTo"],
            routingIndex=index, **kwargs)

    @staticmethod
    def drain_main(queue):
        while queue:
            queue.pop(0)()

    def make_home(self):
        runtime = self.make()
        c, _, _, _, state, script, _, _, _, braille = runtime
        order = []
        namespace = {
            'braille': braille, 'orca_state': state,
            '_brlAPIAvailable': True,
            'brlapi': SimpleNamespace(**{
                'KEY_CMD_' + key: key for key in ('HWINLT', 'HWINRT', 'FWINLT',
                    'FWINRT', 'FWINLTSKIP', 'FWINRTSKIP', 'LNUP', 'LNDN')}),
            'BrailleEvent': lambda event: SimpleNamespace(event=event),
            'speech': SimpleNamespace(stop=lambda: order.append('stop')),
            'debug': SimpleNamespace(printException=lambda level: self.fail('native dispatch failed')),
        }
        fixture = Path(__file__).resolve().parents[2] / 'fixtures/orca42-braille-home-methods.py'
        exec(compile(fixture.read_text(), str(fixture), 'exec'), namespace)
        braille.dontInteruptSpeechKeys = namespace['dontInteruptSpeechKeys']
        script.flatReviewContext = None
        script.goBrailleHome = MethodType(namespace['Script'].goBrailleHome, script)
        namespace['_regionWithFocus'] = state.locusOfFocus
        namespace['setFocus'] = lambda region: order.append(('focus', region))
        namespace['refresh'] = lambda force: order.append(('refresh', force))
        braille.returnToRegionWithFocus = namespace['returnToRegionWithFocus']
        namespace['_eventManager'] = SimpleNamespace(processBrailleEvent=lambda event:
            script.goBrailleHome(event) if event.event['command'] == 'home' else True)
        stop = c.local_machine.cancel_speech.side_effect
        c.local_machine.cancel_speech.side_effect = lambda: (order.append('stop'), stop())
        return (*runtime, order)

    @staticmethod
    def home(c):
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_toFocus'])

    def test_native_orca_home_interrupts_speech_before_returning_to_focus(self):
        _, _, _, _, state, script, _, _, _, _, order = self.make_home()
        dispatch = script.goBrailleHome.__func__.__globals__['_processBrailleEvent']
        self.assertTrue(dispatch({'command': 'home'}))
        self.assertEqual(order, ['stop', ('focus', state.locusOfFocus), ('refresh', True)])
        order.clear()
        self.assertTrue(dispatch({'command': 'FWINRT'}))
        self.assertEqual(order, [])

    def test_home_interrupts_before_native_focus_return_and_expires_queued_end(self):
        c, server, idle, messages, state, script, contexts, text, queue, _, order = self.make_home()
        self.start(server, idle, script, contexts)
        server._client.queued[0][2]['callback']('end')
        self.home(c)
        self.assertEqual(order, [])
        self.assertEqual(c.transport.sent, [])
        self.drain_main(queue)
        self.assertEqual(order, ['stop', ('focus', state.locusOfFocus), ('refresh', True)])
        self.assertEqual(c.transport.sent, ['cancel'])
        self.drain_native(idle)
        self.assertEqual([m['sequence'] for m in messages], [['FIRST']])
        text.setCaretOffset.assert_not_called()
        text.setSelection.assert_not_called()
        self.assertFalse(script._inSayAll)

    def test_home_before_first_idle_never_starts_the_old_say_all(self):
        c, server, idle, messages, _, script, contexts, text, queue, _, _ = self.make_home()
        server.sayAll(iter((context, presentation.Voice(gain=5)) for context in contexts),
                      script._Script__sayAllProgressCallback)
        self.home(c)
        self.drain_main(queue)
        self.drain_native(idle)
        self.assertEqual(messages, [])
        self.assertEqual(server._client.queued, [])
        self.assertEqual(c.transport.sent, ['cancel'])
        text.setCaretOffset.assert_not_called()
        self.assertFalse(script._inSayAll)

    def test_home_preserves_native_cancel_caret_placement_at_the_spoken_word(self):
        c, server, idle, _, _, script, contexts, text, queue, _, _ = self.make_home()
        contexts[0].currentOffset = 3
        self.start(server, idle, script, contexts)
        self.home(c)
        self.drain_main(queue)
        server._client.queued[0][2]['callback']('cancel')
        self.drain_native(idle)
        text.setCaretOffset.assert_called_once_with(3)
        text.setSelection.assert_called_once_with(0, 3, 3)
        self.assertEqual(script._sayAllContexts, [])
        self.assertFalse(script._inSayAll)

    def test_home_legacy_fallback_and_snake_case_handler_keep_interrupt_order(self):
        for api in ('legacy', 'snake'):
            with self.subTest(api=api):
                c, _, _, _, state, script, _, _, queue, _, order = self.make_home()
                if api == 'snake':
                    script.go_braille_home, script.goBrailleHome = script.goBrailleHome, None
                with mock.patch.dict(sys.modules,
                        {'linux_rdaccess_orca_adapter': None} if api == 'legacy' else {}):
                    self.home(c)
                    self.drain_main(queue)
                self.assertEqual(order, ['stop', ('focus', state.locusOfFocus), ('refresh', True)])
                self.assertEqual(c.transport.sent, ['cancel'])

    def test_stale_or_unsupported_home_does_not_cancel_current_speech(self):
        for reason in ('focus', 'session', 'display', 'handler', 'legacy_handler'):
            with self.subTest(reason=reason):
                c, _, _, _, state, script, _, _, queue, _, order = self.make_home()
                c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
                self.home(c)
                if reason == 'focus':
                    state.locusOfFocus = object()
                elif reason == 'session':
                    c.transport.connected = False
                elif reason == 'display':
                    c._lrd_braille_display = {'width': 0, 'ready': True, 'owner': object()}
                else:
                    script.goBrailleHome = None
                with mock.patch.dict(sys.modules,
                        {'linux_rdaccess_orca_adapter': None} if reason == 'legacy_handler' else {}):
                    self.drain_main(queue)
                self.assertEqual(order, [])
                c.local_machine.cancel_speech.assert_not_called()
                self.assertEqual(c.transport.sent, [])

    def test_declined_home_interrupts_once_without_retrying_the_handler(self):
        c, _, _, _, _, script, _, _, queue, _, order = self.make_home()
        script.goBrailleHome = mock.Mock(return_value=False)
        self.home(c)
        self.drain_main(queue)
        script.goBrailleHome.assert_called_once_with(None)
        self.assertEqual(order, ['stop'])
        self.assertEqual(c.transport.sent, ['cancel'])

    def test_home_interrupts_before_leaving_native_flat_review(self):
        c, _, _, _, _, script, _, _, queue, _, order = self.make_home()
        script.flatReviewContext = object()
        script.toggleFlatReviewMode = mock.Mock(side_effect=lambda event:
            order.append('leave-review') or True)
        self.home(c)
        self.drain_main(queue)
        self.assertEqual(order, ['stop', 'leave-review'])
        script.toggleFlatReviewMode.assert_called_once_with(None)
        self.assertEqual(c.transport.sent, ['cancel'])

    def test_old_cancel_after_home_cannot_expire_new_say_all(self):
        c, server, idle, messages, _, script, contexts, text, queue, _, _ = self.make_home()
        self.start(server, idle, script, contexts)
        old_callback = server._client.queued[0][2]['callback']
        self.home(c)
        self.drain_main(queue)
        self.start(server, idle, script, contexts[1:])
        old_callback('cancel')
        self.drain_native(idle)
        self.assertTrue(script._inSayAll)
        self.assertEqual([m['sequence'] for m in messages], [['FIRST'], ['SECOND']])
        text.setCaretOffset.assert_not_called()
        text.setSelection.assert_not_called()

    def test_raw_braille_commands_expire_on_script_or_window_change_with_same_focus(self):
        for command in ('route', 'home', 'pan'):
            for change in ('script', 'window'):
                with self.subTest(command=command, change=change):
                    c, _, _, _, state, script, _, text, queue, _ = self.make()
                    script.goBrailleHome = mock.Mock()
                    state.activeWindow = object()
                    focus = state.locusOfFocus
                    orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
                    c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
                    if command == 'route':
                        self.route(c)
                    elif command == 'home':
                        self.home(c)
                    else:
                        c._on_remote_braille_input(scriptPath=[
                            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
                    replacement = SimpleNamespace(
                        processRoutingKey=mock.Mock(), goBrailleHome=mock.Mock(),
                        panBrailleRight=mock.Mock())
                    if change == 'script':
                        state.activeScript = replacement
                    else:
                        state.activeWindow = object()
                    self.drain_main(queue)
                    self.assertIs(state.locusOfFocus, focus)
                    c.local_machine.cancel_speech.assert_not_called()
                    self.assertEqual(c.transport.sent, [])
                    self.assertFalse(any(event[0] == 'key' for event in c.local_machine.events))
                    for owner in (script, replacement):
                        owner.processRoutingKey.assert_not_called()
                        owner.goBrailleHome.assert_not_called()
                        owner.panBrailleRight.assert_not_called()
                    text.setCaretOffset.assert_not_called()

    def test_raw_braille_context_cannot_revive_after_observed_activation_change(self):
        for change in ('script', 'window'):
            with self.subTest(change=change):
                c, _, _, _, state, script, _, _, queue, _ = self.make()
                state.activeWindow = window = object()
                orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
                context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
                c._lrd_braille_focus_context = context
                c._on_remote_braille_input(scriptPath=[
                    'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
                if change == 'script':
                    state.activeScript = object()
                else:
                    state.activeWindow = object()
                self.assertFalse(orca_adapter.OrcaRuntimeAdapter.braille_focus_is_current(context))
                state.activeScript, state.activeWindow = script, window
                self.drain_main(queue)
                script.panBrailleRight.assert_not_called()
                self.assertFalse(orca_adapter.OrcaRuntimeAdapter.braille_focus_is_current(context))

    def test_new_braille_presentation_allows_fresh_commands_after_activation_change(self):
        c, _, _, _, state, old_script, _, _, queue, _ = self.make()
        state.activeWindow = object()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        script = state.activeScript = SimpleNamespace(panBrailleRight=mock.Mock())
        state.activeWindow = object()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        self.drain_main(queue)
        old_script.panBrailleRight.assert_not_called()
        script.panBrailleRight.assert_called_once_with(None)
        c.local_machine.cancel_speech.assert_not_called()

    def test_script_identity_and_equivalent_window_proxies_preserve_current_braille(self):
        class Window:
            def __eq__(self, other):
                return isinstance(other, Window)

        c, _, _, _, state, script, _, _, queue, _ = self.make()
        state.activeWindow = Window()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._lrd_braille_focus_context = context
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        state.activeWindow = Window()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        self.assertIs(orca_adapter.OrcaRuntimeAdapter.braille_focus_context(), context)
        self.drain_main(queue)
        script.panBrailleRight.assert_called_once_with(None)

    def test_equal_script_instances_cannot_reuse_an_old_braille_context(self):
        class Script(SimpleNamespace):
            def __eq__(self, other):
                return isinstance(other, Script)

        c, _, _, _, state, _, _, _, queue, _ = self.make()
        state.activeScript = Script(panBrailleRight=mock.Mock())
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        replacement = state.activeScript = Script(panBrailleRight=mock.Mock())
        self.drain_main(queue)
        replacement.panBrailleRight.assert_not_called()

    def test_snake_case_activation_change_expires_raw_braille_with_no_focus(self):
        c, _, _, _, state, script, _, _, queue, _ = self.make()
        state.active_script, state.active_window = script, object()
        state.locus_of_focus = None
        del state.activeScript, state.activeWindow, state.locusOfFocus
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        state.active_window = object()
        self.drain_main(queue)
        script.panBrailleRight.assert_not_called()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        self.drain_main(queue)
        script.panBrailleRight.assert_called_once_with(None)

    def test_unreadable_window_expires_raw_braille_without_logging_application_text(self):
        class Window:
            def __eq__(self, other):
                raise RuntimeError('private application text')

        c, _, _, _, state, script, _, _, queue, _ = self.make()
        state.activeWindow = Window()
        orca_adapter.OrcaRuntimeAdapter.record_braille_focus()
        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
        c._on_remote_braille_input(scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_scrollForward'])
        state.activeWindow = Window()
        with mock.patch.object(c._module.log, 'error') as error:
            self.drain_main(queue)
        script.panBrailleRight.assert_not_called()
        self.assertIsNone(orca_adapter.OrcaRuntimeAdapter.braille_focus_context())
        self.assertNotIn('private application text', str(error.call_args_list))

    def test_route_stops_on_main_loop_and_expires_queued_end(self):
        c, server, idle, messages, _, script, contexts, text, queue, _ = self.make()
        self.start(server, idle, script, contexts)
        server._client.queued[0][2]["callback"]("end")
        self.route(c)
        c.local_machine.cancel_speech.assert_not_called()
        script.processRoutingKey.assert_not_called()
        self.assertEqual(c.transport.sent, [])
        self.drain_main(queue)
        c.local_machine.cancel_speech.assert_called_once_with()
        self.assertEqual(c.transport.sent, ["cancel"])
        self.drain_native(idle)
        self.assertEqual([m["sequence"] for m in messages], [["FIRST"]])
        text.setCaretOffset.assert_called_once_with(9)
        text.setSelection.assert_not_called()
        self.assertFalse(script._inSayAll)

    def test_late_native_cancel_does_not_restore_the_pre_routing_caret(self):
        c, server, idle, _, _, script, contexts, text, queue, _ = self.make()
        self.start(server, idle, script, contexts)
        self.route(c)
        self.drain_main(queue)
        server._client.queued[0][2]["callback"]("cancel")
        self.drain_native(idle)
        text.setCaretOffset.assert_called_once_with(9)
        text.setSelection.assert_not_called()
        self.assertFalse(script._inSayAll)
        self.assertEqual(script._sayAllContexts, [])

    def test_route_before_first_native_idle_never_starts_old_say_all(self):
        c, server, idle, messages, _, script, contexts, text, queue, _ = self.make()
        server.sayAll(iter((context, presentation.Voice(gain=5)) for context in contexts),
                      script._Script__sayAllProgressCallback)
        self.route(c)
        self.drain_main(queue)
        self.drain_native(idle)
        self.assertEqual(messages, [])
        self.assertEqual(server._client.queued, [])
        text.setCaretOffset.assert_called_once_with(9)
        self.assertFalse(script._inSayAll)

    def test_legacy_routing_fallback_also_interrupts_before_moving_the_caret(self):
        c, server, idle, _, _, script, contexts, text, queue, _ = self.make()
        self.start(server, idle, script, contexts)
        order = []
        stop = c.local_machine.cancel_speech.side_effect
        c.local_machine.cancel_speech.side_effect = lambda: (order.append("stop"), stop())
        script.processRoutingKey.side_effect = lambda event: (
            order.append("route"), text.setCaretOffset(event.event["argument"]))
        with mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": None}):
            self.route(c)
            self.drain_main(queue)
        self.assertEqual(order, ["stop", "route"])
        self.assertEqual(c.transport.sent, ["cancel"])
        server._client.queued[0][2]["callback"]("cancel")
        self.drain_native(idle)
        text.setCaretOffset.assert_called_once_with(9)
        text.setSelection.assert_not_called()

    def test_pan_keeps_say_all_running(self):
        c, server, idle, messages, _, script, contexts, _, queue, _ = self.make()
        self.start(server, idle, script, contexts)
        c._on_remote_braille_input(scriptPath=[
            "globalCommands", "GlobalCommands", "braille_scrollForward"])
        self.drain_main(queue)
        server._client.queued[0][2]["callback"]("end")
        self.drain_native(idle)
        c.local_machine.cancel_speech.assert_not_called()
        self.assertEqual(c.transport.sent, [])
        script.panBrailleRight.assert_called_once_with(None)
        self.assertEqual([m["sequence"] for m in messages], [["FIRST"], ["SECOND"]])

    def test_old_cancel_after_routing_cannot_expire_a_new_say_all_run(self):
        c, server, idle, messages, _, script, contexts, text, queue, _ = self.make()
        self.start(server, idle, script, contexts)
        old_callback = server._client.queued[0][2]["callback"]
        self.route(c)
        self.drain_main(queue)
        self.start(server, idle, script, contexts[1:])
        old_callback("cancel")
        self.drain_native(idle)
        self.assertTrue(script._inSayAll)
        self.assertEqual([m["sequence"] for m in messages], [["FIRST"], ["SECOND"]])
        text.setCaretOffset.assert_called_once_with(9)
        text.setSelection.assert_not_called()

    def test_native_stop_failure_still_cancels_nvda_and_routes_without_logging_text(self):
        c, server, idle, messages, _, script, contexts, text, queue, _ = self.make()
        self.start(server, idle, script, contexts)
        c.local_machine.cancel_speech.side_effect = RuntimeError("private-speech-sentinel")
        self.route(c)
        log = c._linux_rdaccess_stop_braille_speech.__func__.__globals__["log"]
        with mock.patch.object(log, "error") as error:
            self.drain_main(queue)
        error.assert_called_once_with("linux-rdaccess: failed to cancel speech for braille navigation")
        self.assertEqual(c.transport.sent, ["cancel"])
        server._client.queued[0][2]["callback"]("end")
        self.drain_native(idle)
        self.assertEqual([m["sequence"] for m in messages], [["FIRST"]])
        text.setCaretOffset.assert_called_once_with(9)
        text.setSelection.assert_not_called()

    def test_rejected_or_stale_routes_do_not_interrupt_speech(self):
        for reason in ("index", "metadata", "geometry", "focus", "session", "handler"):
            with self.subTest(reason=reason):
                c, server, idle, _, state, script, contexts, _, queue, braille = self.make()
                self.start(server, idle, script, contexts)
                if reason == "index":
                    self.route(c, 32)
                elif reason == "metadata":
                    self.route(c, cellIndexes=[8])
                else:
                    if reason == "focus":
                        c._lrd_braille_focus_context = orca_adapter.OrcaRuntimeAdapter.braille_focus_context()
                    self.route(c)
                    if reason == "geometry":
                        braille._displaySize = [8, 1]
                    elif reason == "focus":
                        state.locusOfFocus = object()
                    elif reason == "session":
                        c.transport.connected = False
                    elif reason == "handler":
                        script.processRoutingKey = None
                self.drain_main(queue)
                c.local_machine.cancel_speech.assert_not_called()
                self.assertEqual(c.transport.sent, [])


if __name__ == "__main__":
    unittest.main()
