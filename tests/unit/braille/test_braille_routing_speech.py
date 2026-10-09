"""Routing must interrupt remote Say All without restoring its old caret."""

import sys
from types import ModuleType
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
        log = c._linux_rdaccess_stop_braille_routing_speech.__func__.__globals__["log"]
        with mock.patch.object(log, "error") as error:
            self.drain_main(queue)
        error.assert_called_once_with("linux-rdaccess: failed to cancel speech for braille routing")
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
