"""NVDA Remote protocol integration through disposable loopback TCP sockets.

Run with ``python3 -m unittest -v tests.integration.test_nvda_remote_loopback``.
This is also included by standard unittest discovery. No desktop, external
relay, real credentials, NVDA installation, or braille display is used.
"""

from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest import mock

from linux_rdaccess_core.accessibility import orca_adapter
from linux_rdaccess_core.connection import remote_access
from tests.integration.nvda_remote_harness import (
    LoopbackSession, QueuedMainLoop, packet,
)
from tests.shared.test_compat_lifecycle import Harness
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeAction, FakeText
from tests.unit.accessibility import test_customization_say_all_callbacks as say_all_callbacks
from tests.unit.accessibility import test_say_all_presentation_lifetime as say_all_presentation


CONTROLLER_LIFECYCLE = '''
    def disconnect(self):
        self.control_state = 0
        self.transport.close()

    def _on_transport_connected(self, **kwargs):
        pass

    def _on_transport_disconnected(self, **kwargs):
        pass
'''


class NvdaRemoteLoopbackTests(Harness, unittest.TestCase):
    def setUp(self):
        self.session = LoopbackSession()
        self.addCleanup(self.session.close)
        self.controller, _, _ = self._patched_controller(
            source=self.UPSTREAM_CONTROLLER + CONTROLLER_LIFECYCLE,
        )
        self.controller.transport = self.session.transport
        self.controller.connected_clients = {7: {"connection_type": "master"}}
        manager = self.session.transport.callback_manager
        for event, method in (
            ("transport_connected", "_on_transport_connected"),
            ("transport_disconnected", "_on_transport_disconnected"),
            ("msg_key", "_on_remote_key"),
            ("msg_channel_joined", "_on_channel_joined"),
            ("msg_client_left", "_on_client_left"),
            ("msg_braille_input", "_on_remote_braille_input"),
            ("msg_braille_info", "_on_remote_braille_info"),
        ):
            manager.register_callback(event, getattr(self.controller, method))

    def connect(self, *, native_reconnector=False):
        worker = self.session.start(native_reconnector=native_reconnector)
        self.session.send(type="channel_joined", channel="test-only")
        self.session.barrier()
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "lrd_a11y_hello", "version": 1},
        ])
        return worker

    def tearDown(self):
        # unittest runs tearDown before cleanup callbacks stop the Orca/GLib
        # patches, so receiver teardown cannot call the user's native runtime.
        self.session.close()

    def key(self, vk, pressed, **kwargs):
        self.session.send(
            type="key", vk_code=vk, pressed=pressed, scan_code=0,
            extended=kwargs.pop("extended", False), **kwargs,
        )

    def speech(self, *, pending_cancel=False):
        local = []
        namespace = {
            "transport": self.session.transport, "_want_cancel": pending_cancel,
            "old_speak": lambda *args, **kwargs: local.append((args, kwargs)),
        }
        source = remote_access._patch_legacy_customization_speech_sequence(
            remote_access._CUSTOMIZATION_SPEECH_FORWARD_SOURCE,
        )
        exec(compile(source, "loopback-orca-speech", "exec"), namespace)
        return namespace, local

    def braille_runtime(self, *, queued=False):
        app = FakeAccessible("Loopback controls", "application")
        action = FakeAction(["click"])
        button = FakeAccessible(
            "Apply café", "push button", app,
            states=("focusable", "enabled"), action_iface=action,
        )
        state = types.ModuleType("orca.orca_state")
        state.locusOfFocus = button
        braille = types.ModuleType("orca.braille")
        braille.refresh = mock.Mock(return_value="native refresh")
        orca = types.ModuleType("orca")
        orca.braille, orca.orca_state = braille, state
        modules = {
            "orca": orca, "orca.braille": braille,
            "orca.orca_state": state,
            "linux_rdaccess_orca_adapter": orca_adapter,
        }
        idle = QueuedMainLoop()
        if queued:
            modules.update(idle.modules)
            # Use the production generation guard, rather than Harness's
            # inline dispatcher, for callbacks crossing a reconnect.
            self.controller._linux_rdaccess_run_main = (
                self.controller.__class__._linux_rdaccess_run_main.__get__(
                    self.controller)
            )
        for patch in (
            mock.patch.dict(sys.modules, modules),
            mock.patch.object(orca_adapter.OrcaRuntimeAdapter, "braille_cells",
                              return_value=[1, 2, 0, 255]),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(orca_adapter.OrcaRuntimeAdapter.clear_semantic_focus)
        namespace = {"controller": self.controller, "_dbg": lambda *_args: None}
        exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, namespace)
        self.braille_namespace = namespace
        return braille, state, button, action, idle

    def test_fragmented_keyboard_messages_preserve_delivery_and_modifier_ownership(self):
        self.connect()
        keys = []
        self.controller.local_machine.send_key = lambda **kwargs: keys.append(kwargs)
        # Split inside the wire key name; a real stream recv must reassemble it.
        data = packet(type="key", key_name="Shift_L", vk_code=0xA0,
                      pressed=True, extended=False, scan_code=42, modifiers=1)
        self.session.peer.sendall(data[:13])
        self.session.wait_for_buffer(data[:13])
        self.session.peer.sendall(data[13:])
        self.key(0x09, True, modifiers=1)
        self.key(0x09, True, modifiers=1)  # application auto-repeat is preserved
        self.key(0x09, False, modifiers=1)
        self.session.barrier()
        self.assertEqual([(k["vk_code"], k["pressed"]) for k in keys], [
            (0xA0, True), (0x09, True), (0x09, True), (0x09, False),
        ])
        self.assertEqual(keys[0]["key_name"], "Shift_L")
        self.assertEqual(keys[0]["scan_code"], 42)
        self.assertTrue(all(k["modifiers"] == 1 for k in keys))
        self.session.disconnect_peer()
        self.session.transport.callback_manager.wait_for("transport_disconnected")
        self.assertEqual((keys[-1]["vk_code"], keys[-1]["pressed"]), (0xA0, False))
        self.assertEqual(self.controller._lrd_forwarded, {})

    def test_wire_routing_rechecks_native_width_after_local_display_reconnect(self):
        braille, state, _, _, idle = self.braille_runtime(queued=True)
        braille._displaySize = [32, 1]
        routes = []
        state.activeScript = types.SimpleNamespace(
            processRoutingKey=lambda event: routes.append(event.event['argument']))
        self.connect()
        self.session.send(type='braille_info', numCells=80)
        self.session.barrier()
        idle.drain()
        self.session.read_through_barrier()
        self.session.send(type='braille_input', scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_routeTo'], routingIndex=79)
        self.session.barrier()
        # The network receiver accepted an 80-cell coordinate. Orca's local
        # BrlAPI reconnect changes geometry before main-loop execution.
        braille._displaySize = [20, 1]
        idle.drain()
        self.assertEqual(routes, [])
        for index in (19, 20):
            self.session.send(type='braille_input', scriptPath=[
                'globalCommands', 'GlobalCommands', 'braille_routeTo'], routingIndex=index)
        self.session.barrier()
        idle.drain()
        self.assertEqual(routes, [19])

    def test_controller_disconnect_does_not_deadlock_receiver_teardown(self):
        worker = self.connect()
        self.key(0xA0, True)
        self.key(0x41, True)
        self.session.barrier()
        receiver_owns_connection = threading.Event()
        close_started = threading.Event()
        transport = self.session.transport
        connection_lock = transport._linux_rdaccess_connection_lock

        class BoundedConnectionLock:
            # Bound only the acquisition that would otherwise deadlock the
            # test. The receiver and controller still use the native RLock.
            def __enter__(self):
                if not connection_lock.acquire(timeout=1):
                    raise AssertionError("disconnect waited on receiver while holding input lock")
                return self

            def __exit__(self, *_args):
                connection_lock.release()

        def before_disconnected_callback():
            receiver_owns_connection.set()
            if not close_started.wait(2):
                raise AssertionError("controller did not start close")

        original_close = transport.close

        def observed_close():
            close_started.set()
            return original_close()

        transport.callback_manager.callbacks["transport_disconnected"].insert(
            0, before_disconnected_callback)
        failure = None
        with mock.patch.object(transport, "_linux_rdaccess_connection_lock", BoundedConnectionLock()), \
                mock.patch.object(transport, "close", observed_close):
            try:
                self.session.disconnect_peer()
                self.assertTrue(receiver_owns_connection.wait(2))
                try:
                    self.controller.disconnect()
                except AssertionError as error:
                    failure = error
            finally:
                close_started.set()
                worker.join(3)
        self.assertIsNone(failure)
        self.assertFalse(worker.is_alive())
        self.assertTrue(transport.closed)
        self.assertEqual(self.controller._lrd_forwarded, {})
        self.assertEqual(self.controller.local_machine.events, [
            ("key", 0xA0, True, None), ("cancel",), ("key", 0x41, True, None),
            ("key", 0x41, False, None), ("key", 0xA0, False, None),
        ])

    def test_output_serialized_in_old_session_is_not_delivered_after_reconnect(self):
        self.connect()
        entered, release = threading.Event(), threading.Event()
        errors = []
        serialize = self.session.transport.serializer.serialize

        def delayed(**kwargs):
            if kwargs.get("sequence") == ["old-session"]:
                entered.set()
                if not release.wait(5):
                    raise AssertionError("old speech serialization was never released")
            return serialize(**kwargs)

        def speak():
            try:
                self.session.transport.send(type="speak", sequence=["old-session"])
            except BaseException as error:
                errors.append(error)

        self.session.transport.serializer.serialize = delayed
        sender = threading.Thread(target=speak)
        sender.start()
        try:
            self.assertTrue(entered.wait(2))
            self.session.disconnect_peer()
            self.session.transport.callback_manager.wait_for("transport_disconnected")
            self.connect()
        finally:
            release.set()
            sender.join(2)
        self.assertFalse(sender.is_alive())
        self.assertEqual(errors, [])
        self.session.transport.send(type="speak", sequence=["new-session"])
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "speak", "sequence": ["new-session"]},
        ])

    def test_legacy_name_only_ctrl_cancels_windows_speech_without_losing_key_ownership(self):
        self.connect()
        for pressed in (True, True, False, True, False):
            self.session.send(type="key", key_name="Control_R", pressed=pressed)
        self.session.barrier()
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "cancel"}, {"type": "cancel"},
        ])
        delivered = [event for event in self.controller.local_machine.events if event[0] == "key"]
        self.assertEqual(delivered, [("key", None, pressed, "Control_R")
                                     for pressed in (True, True, False, True, False)])
        self.assertFalse(self.controller._lrd_forwarded)

    def test_native_reconnector_rejoins_and_discards_partial_message_and_held_modifier(self):
        self.connect(native_reconnector=True)
        self.key(0xA0, True)
        self.session.barrier()
        self.session.peer.sendall(b'{"type":"key","vk_code":')
        self.session.wait_for_buffer(b'{"type":"key","vk_code":')
        self.session.disconnect_peer()
        self.session.transport.callback_manager.wait_for("transport_disconnected")
        self.session.accept()
        self.session.transport.callback_manager.wait_for("transport_connected", count=2)
        self.assertEqual(self.session.transport.successful_connects, 2)
        self.assertEqual(self.session.transport.buffer, b"")
        self.session.send(type="channel_joined", channel="test-only")
        self.key(0x41, True)
        self.key(0x41, False)
        self.session.barrier()
        self.assertEqual(self.controller._lrd_down, set())
        self.assertEqual(self.controller._lrd_forwarded, {})
        delivered = [e[:3] for e in self.controller.local_machine.events if e[0] == "key"]
        self.assertEqual(delivered, [
            ("key", 0xA0, True), ("key", 0xA0, False),
            ("key", 0x41, True), ("key", 0x41, False),
        ])

    def test_ctrl_cancel_precedes_ordered_utterances_without_character_expansion_or_duplicates(self):
        self.connect()
        self.key(0xA2, True)
        self.key(0xA2, True)
        self.key(0xA2, False)
        self.session.barrier()
        speech, local = self.speech()
        utterances = ["First café.  αβ\nsecond line!", "Second utterance"]
        for text in utterances:
            speech["my_speak"](None, text, None)
        speech["my_speak"](None, "", None)
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "cancel"},
            {"type": "speak", "sequence": [utterances[0]]},
            {"type": "speak", "sequence": [utterances[1]]},
        ])
        self.assertEqual(len(local), 1)  # empty speech remains a local call
        self.assertEqual(self.controller.local_machine.events.count(("cancel",)), 1)

    def test_deferred_speech_cancel_is_once_and_sequence_commands_keep_order(self):
        self.connect()
        speech, local = self.speech(pending_cancel=True)
        sequence = ["Word", ["CharacterModeCommand", {"state": True}], "A"]
        speech["my_speak"](None, sequence, None)
        speech["my_speak"](None, "Next", None)
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "cancel"}, {"type": "speak", "sequence": sequence},
            {"type": "speak", "sequence": ["Next"]},
        ])
        self.assertFalse(speech["_want_cancel"])
        self.assertEqual(local, [])
        self.session.disconnect_peer()
        self.session.transport.callback_manager.wait_for("transport_disconnected")
        speech["my_speak"](None, "Local after disconnect", None)
        self.assertEqual(len(local), 1)

    def test_say_all_stops_forwarding_after_an_orca_window_change(self):
        self.connect()
        helper = say_all_callbacks.SayAllCallbacksTests()
        namespace, server, native_speak, idle, _ = helper.hooked()
        namespace["controller"] = self.controller
        namespace["transport"] = self.session.transport
        state = native_speak.__globals__["orca_state"]
        state.activeScript = types.SimpleNamespace(
            utilities=types.SimpleNamespace(adjustForPronunciation=lambda text: text))
        state.activeWindow = object()
        contexts = [types.SimpleNamespace(utterance=text, startOffset=0, endOffset=len(text))
                    for text in ("FIRST", "SECOND")]
        progress = []
        server.sayAll(iter((context, say_all_callbacks.Voice(gain=5)) for context in contexts),
                      lambda *args: progress.append(args))
        func, args = idle.pop(0)
        func(*args)
        server._client.queued[0][2]["callback"]("end")
        state.activeWindow = object()
        while idle:
            func, args = idle.pop(0)
            func(*args)
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "speak", "sequence": ["FIRST"]},
        ])
        self.assertEqual(progress, [])

    def test_remote_routing_cancels_say_all_and_preserves_the_chosen_caret(self):
        braille, state, _, _, main = self.braille_runtime(queued=True)
        self.connect()
        helper = say_all_presentation.SayAllPresentationLifetimeTests()
        namespace, server, idle, _, native_state, script, contexts, text, _ = helper.runtime()
        namespace["controller"], namespace["transport"] = self.controller, self.session.transport
        state.activeScript, state.activeWindow = script, native_state.activeWindow
        state.locusOfFocus = contexts[0].obj
        type(server).sayAll._linux_rdaccess_original.__globals__["orca_state"] = state
        script._Script__sayAllProgressCallback.__func__.__globals__["orca_state"] = state
        script.processRoutingKey = lambda event: text.setCaretOffset(event.event["argument"])
        braille._displaySize = [32, 1]
        self.controller.local_machine.cancel_speech = mock.Mock(
            side_effect=lambda: namespace["old_stop"](server))
        helper.start(server, idle, script, contexts)
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "speak", "sequence": ["FIRST"]},
        ])
        self.session.send(type="braille_input", routingIndex=9,
                          scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"])
        self.session.barrier()
        self.controller.local_machine.cancel_speech.assert_not_called()
        main.drain()
        self.controller.local_machine.cancel_speech.assert_called_once_with()
        self.assertEqual(self.session.read_through_barrier(), [{"type": "cancel"}])
        callback = server._client.queued[0][2]["callback"]
        callback("end")
        callback("cancel")
        helper.drain(idle)
        self.assertEqual(self.session.read_through_barrier(), [])
        text.setCaretOffset.assert_called_once_with(9)
        text.setSelection.assert_not_called()
        self.assertFalse(script._inSayAll)

    def test_master_departure_during_elements_lookup_discards_the_key_fallback(self):
        self.braille_runtime(queued=True)
        self.connect()
        keys = []
        self.controller.local_machine.send_key = lambda **payload: keys.append(payload)

        def unsupported(*args, **kwargs):
            self.session.send(type="client_left", client={
                "id": 7, "connection_type": "master",
            })
            self.session.barrier()
            return None

        with mock.patch.object(orca_adapter.OrcaRuntimeAdapter, "show_structural_list",
                               side_effect=unsupported):
            self.controller._linux_rdaccess_open_structural_list("m", None)
        self.assertEqual(self.controller.connected_clients, {})
        self.assertEqual(keys, [])
        self.assertFalse(getattr(self.controller, "_lrd_forwarded", {}))

    def test_remote_braille_home_cancels_say_all_before_native_home_over_wire(self):
        _, state, _, _, main = self.braille_runtime(queued=True)
        self.connect()
        helper = say_all_presentation.SayAllPresentationLifetimeTests()
        namespace, server, idle, _, native_state, script, contexts, text, _ = helper.runtime()
        namespace['controller'], namespace['transport'] = self.controller, self.session.transport
        state.activeScript, state.activeWindow = script, native_state.activeWindow
        state.locusOfFocus = contexts[0].obj
        state.lastInputEvent = native_state.lastInputEvent
        type(server).sayAll._linux_rdaccess_original.__globals__['orca_state'] = state
        script._Script__sayAllProgressCallback.__func__.__globals__['orca_state'] = state
        order = []
        contexts[0].currentOffset = 3
        script.goBrailleHome = lambda event: order.append('home')
        self.controller.local_machine.cancel_speech = mock.Mock(side_effect=lambda:
            (order.append('stop'), namespace['old_stop'](server)))
        self.controller._linux_rdaccess_sync_state()
        helper.start(server, idle, script, contexts)
        self.assertEqual(self.session.read_through_barrier(), [
            {'type': 'speak', 'sequence': ['FIRST']},
        ])
        self.session.send(type='braille_input', scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_toFocus'])
        self.session.barrier()
        self.assertEqual(order, [])
        main.drain()
        self.assertEqual(order, ['stop', 'home'])
        self.assertEqual(self.session.read_through_barrier(), [{'type': 'cancel'}])
        callback = server._client.queued[0][2]['callback']
        callback('cancel')
        helper.drain(idle)
        callback('end')
        helper.drain(idle)
        self.assertEqual(self.session.read_through_barrier(), [])
        text.setCaretOffset.assert_called_once_with(3)
        text.setSelection.assert_called_once_with(0, 3, 3)
        self.assertFalse(script._inSayAll)

    def test_master_departure_expires_queued_braille_home_without_cancelling_speech(self):
        _, state, _, _, main = self.braille_runtime(queued=True)
        self.connect()
        home = mock.Mock()
        state.activeScript = types.SimpleNamespace(goBrailleHome=home)
        self.controller.local_machine.cancel_speech = mock.Mock()
        self.session.send(type='braille_input', scriptPath=[
            'globalCommands', 'GlobalCommands', 'braille_toFocus'])
        self.session.send(type='client_left', client={'id': 7, 'connection_type': 'master'})
        self.session.barrier()
        main.drain()
        self.controller.local_machine.cancel_speech.assert_not_called()
        home.assert_not_called()
        self.assertEqual(self.session.read_through_barrier(), [])

    def test_raw_braille_native_focus_actions_and_fallback_cross_real_wire(self):
        braille, state, button, action, _ = self.braille_runtime()
        self.connect()
        self.assertEqual(braille.refresh(), "native refresh")
        self.assertEqual(self.session.read_through_barrier()[-1],
                         {"type": "display", "cells": [1, 2, 0, 255]})
        self.session.send(type="lrd_a11y_capability", version=2, presentation="nvda")
        self.session.barrier()
        self.assertFalse(self.controller._lrd_nvda_native_braille)
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        messages = self.session.read_through_barrier()
        self.assertEqual(len(messages), 1)
        focus = messages[0]
        self.assertEqual(focus["type"], "lrd_a11y_focus")
        obj = next(o for o in focus["objects"] if o["id"] == focus["focus_id"])
        self.assertEqual(obj["name"], "Apply café")
        self.assertEqual(obj["role"], "push button")
        self.assertIn("focused", obj["states"])
        braille.refresh()
        self.assertEqual(self.session.read_through_barrier(), [])
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=True)
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id="stale-object-id", action_index=0)
        self.session.barrier()
        self.assertEqual(action.performed, [])
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        self.assertEqual(action.performed, [0])
        button.name = "Changed focus text"
        braille.refresh()
        self.assertEqual(len(self.session.read_through_barrier()), 1)
        state.locusOfFocus = None
        braille.refresh()
        self.assertEqual(self.session.read_through_barrier(), [
            {"type": "lrd_a11y_fallback", "version": 1},
            {"type": "display", "cells": [1, 2, 0, 255]},
        ])
        self.assertFalse(self.controller._lrd_nvda_native_braille)
        self.assertFalse(orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(focus["focus_id"], 0))

    def test_raw_braille_pan_and_routing_messages_reject_ambiguous_input(self):
        self.connect()
        calls = []
        self.controller._linux_rdaccess_script_call = lambda *args, **kwargs: calls.append(args)
        for script in ("braille_scrollBack", "braille_scrollForward"):
            self.session.send(type="braille_input", dots=0, space=False,
                              scriptPath=["globalCommands", "GlobalCommands", script])
        self.session.send(type="braille_input", dots=0, space=False,
                          routingIndex=3, cellIndexes=[3],
                          scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"])
        # Conflicting routing metadata and typed dots must not pan or route.
        self.session.send(type="braille_input", routingIndex=3, cellIndexes=[4])
        self.session.send(type="braille_input", routingIndex=True)
        self.session.send(type="braille_input", dots=1, space=True,
                          scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"])
        self.session.barrier()
        self.assertEqual([args[0] for args in calls], [
            "panBrailleLeft", "panBrailleRight", "processRoutingKey",
        ])
        self.assertEqual(calls[-1][1].event["argument"], 3)

    def test_departing_master_clears_native_braille_and_rejects_stale_queued_action(self):
        braille, _, _, action, idle = self.braille_runtime(queued=True)
        self.connect()
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        idle.drain()
        focus = self.session.read_through_barrier()[0]
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        self.assertFalse(idle.callbacks.empty())
        self.session.send(type="client_left", client={"id": 7})
        self.session.barrier()
        idle.drain()
        self.assertEqual(action.performed, [])
        self.assertFalse(self.controller._lrd_nvda_native_braille)
        braille.refresh()
        self.assertEqual(self.session.read_through_barrier()[-1],
                         {"type": "display", "cells": [1, 2, 0, 255]})

    def test_queued_raw_routing_expires_when_focus_moves_without_refresh(self):
        braille, state, _, _, idle = self.braille_runtime(queued=True)
        self.connect()
        braille.refresh()
        self.session.read_through_barrier()
        calls = []
        self.controller._linux_rdaccess_script_call = lambda *args, **kwargs: calls.append(args)
        self.session.send(type="braille_input", routingIndex=2)
        self.session.barrier()
        self.assertFalse(idle.callbacks.empty())
        state.locusOfFocus = FakeAccessible("Another editor", "text")
        idle.drain()
        self.assertEqual(calls, [])
        braille.refresh()
        self.session.read_through_barrier()
        self.session.send(type="braille_input", routingIndex=2)
        self.session.barrier()
        idle.drain()
        self.assertEqual(calls[0][0], "processRoutingKey")
        self.assertEqual(calls[0][1].event["argument"], 2)
        self.assertEqual(len(calls), 1)

    def test_queued_raw_pan_expires_after_focus_leaves_and_returns(self):
        braille, state, button, _, idle = self.braille_runtime(queued=True)
        self.connect()
        braille.refresh()
        self.session.read_through_barrier()
        calls = []
        self.controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
        self.session.send(type="braille_input", scriptPath=[
            "globalCommands", "GlobalCommands", "braille_scrollForward"])
        self.session.barrier()
        state.locusOfFocus = FakeAccessible("Another control", "push button")
        braille.refresh()
        state.locusOfFocus = button
        braille.refresh()
        self.session.read_through_barrier()
        idle.drain()
        self.assertEqual(calls, [])

    def test_queued_raw_pans_survive_refreshes_of_the_same_focus(self):
        braille, _, _, _, idle = self.braille_runtime(queued=True)
        self.connect()
        braille.refresh()
        self.session.read_through_barrier()
        calls = []

        def pan(*args):
            calls.append(args[0])
            braille.refresh()

        self.controller._linux_rdaccess_script_call = pan
        for _ in range(2):
            self.session.send(type="braille_input", scriptPath=[
                "globalCommands", "GlobalCommands", "braille_scrollForward"])
        self.session.barrier()
        braille.refresh()
        idle.drain()
        self.assertEqual(calls, ["panBrailleRight", "panBrailleRight"])

    def test_raw_pan_keeps_working_when_a_refresh_has_no_accessible_focus(self):
        braille, state, _, _, idle = self.braille_runtime(queued=True)
        state.locusOfFocus = None
        self.connect()
        braille.refresh()
        self.session.read_through_barrier()
        calls = []
        self.controller._linux_rdaccess_script_call = lambda *args: calls.append(args[0])
        self.session.send(type="braille_input", scriptPath=[
            "globalCommands", "GlobalCommands", "braille_scrollForward"])
        self.session.barrier()
        idle.drain()
        self.assertEqual(calls, ["panBrailleRight"])

    def test_queued_semantic_action_expires_when_focus_moves_without_refresh(self):
        _, state, _, action, idle = self.braille_runtime(queued=True)
        self.connect()
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        idle.drain()
        focus = self.session.read_through_barrier()[0]
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        state.locusOfFocus = FakeAccessible("New target", "push button")
        idle.drain()
        self.assertEqual(action.performed, [])

    def test_queued_semantic_action_expires_even_if_old_target_remains_a_sibling(self):
        braille, state, button, action, idle = self.braille_runtime(queued=True)
        self.connect()
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        idle.drain()
        focus = self.session.read_through_barrier()[0]
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        state.locusOfFocus = FakeAccessible("New target", "push button", button.parent)
        braille.refresh()
        replacement = self.session.read_through_barrier()[0]
        self.assertIn(focus["focus_id"], [obj["id"] for obj in replacement["objects"]])
        idle.drain()
        self.assertEqual(action.performed, [])
        # A fresh command may still act on a neighbor in the current snapshot.
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        idle.drain()
        self.assertEqual(action.performed, [0])

    def test_queued_semantic_caret_expires_when_an_editor_loses_focus(self):
        braille, state, button, _, idle = self.braille_runtime(queued=True)
        text = FakeText("alpha bravo", caret=2)
        text.set_caret_offset = lambda offset: setattr(text, "caret", offset) or True
        editor = FakeAccessible("Editor", "text", button.parent, text_iface=text)
        state.locusOfFocus = editor
        self.connect()
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        idle.drain()
        focus = self.session.read_through_barrier()[0]
        self.session.send(type="lrd_a11y_caret", version=1,
                          object_id=focus["focus_id"], offset=7)
        self.session.barrier()
        state.locusOfFocus = button
        braille.refresh()
        self.session.read_through_barrier()
        idle.drain()
        self.assertEqual(text.caret, 2)
        state.locusOfFocus = editor
        braille.refresh()
        self.session.read_through_barrier()
        self.session.send(type="lrd_a11y_caret", version=1,
                          object_id=focus["focus_id"], offset=7)
        self.session.barrier()
        idle.drain()
        self.assertEqual(text.caret, 7)

    def test_same_focus_refresh_preserves_a_queued_semantic_action(self):
        braille, _, _, action, idle = self.braille_runtime(queued=True)
        self.connect()
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        idle.drain()
        focus = self.session.read_through_barrier()[0]
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        braille.refresh()
        idle.drain()
        self.assertEqual(action.performed, [0])

    def test_queued_semantic_action_expires_after_focus_moves_away_and_back(self):
        braille, state, button, action, idle = self.braille_runtime(queued=True)
        self.connect()
        self.session.send(type="lrd_a11y_capability", version=1, presentation="nvda")
        self.session.barrier()
        idle.drain()
        focus = self.session.read_through_barrier()[0]
        self.session.send(type="lrd_a11y_action", version=1,
                          object_id=focus["focus_id"], action_index=0)
        self.session.barrier()
        state.locusOfFocus = FakeAccessible("New target", "push button", button.parent)
        braille.refresh()
        state.locusOfFocus = button
        braille.refresh()
        self.session.read_through_barrier()
        idle.drain()
        self.assertEqual(action.performed, [])

    def test_braille_customization_reload_forwards_once_without_recursing(self):
        braille, _, _, _, _ = self.braille_runtime()
        self.connect()
        original = self.braille_namespace["_old_braille_refresh"]
        exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, self.braille_namespace)
        self.assertEqual(braille.refresh(), "native refresh")
        self.assertEqual(self.session.read_through_barrier()[-1:], [
            {"type": "display", "cells": [1, 2, 0, 255]},
        ])
        original.assert_called_once()

    def test_malformed_json_disconnects_cleans_sender_and_can_reconnect(self):
        worker = self.connect()
        self.key(0xA0, True)
        self.session.barrier()
        self.session.peer.sendall(b'{"type":"key",invalid}\n')
        self.session.transport.callback_manager.wait_for("transport_disconnected")
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(self.session.transport.connected)
        self.assertIsNone(self.session.transport.server_sock)
        self.assertEqual(self.controller._lrd_forwarded, {})
        self.assertEqual(self.session.transport.buffer, b"")
        self.assertTrue(self.session.transport.queue_thread is None
                        or not self.session.transport.queue_thread.is_alive())
        self.session.disconnect_peer()
        self.connect()
        self.key(0x09, True)
        self.key(0x09, False)
        self.session.barrier()
        self.assertEqual(self.controller._lrd_forwarded, {})

    def test_callback_disconnect_stops_remaining_batched_key_messages(self):
        self.connect()
        manager = self.session.transport.callback_manager
        manager.register_callback("msg_disconnect_now", self.session.transport.close)
        self.session.peer.sendall(
            packet(type="disconnect_now")
            + packet(type="key", vk_code=0x41, pressed=True, extended=False),
        )
        manager.wait_for("msg_disconnect_now")
        self.assertFalse(any(e[0] == "key" for e in self.controller.local_machine.events))
        self.assertFalse(any(name == "msg_key" for name, _ in manager.events))
        self.assertIsNone(self.session.transport.server_sock)


if __name__ == "__main__":
    unittest.main()
