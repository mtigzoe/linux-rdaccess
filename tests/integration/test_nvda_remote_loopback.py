"""NVDA Remote protocol integration through disposable loopback TCP sockets.

Run with ``python3 -m unittest -v tests.integration.test_nvda_remote_loopback``.
This is also included by standard unittest discovery. No desktop, external
relay, real credentials, NVDA installation, or braille display is used.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from linux_rdaccess_core.accessibility import orca_adapter
from linux_rdaccess_core.connection import remote_access
from tests.integration.nvda_remote_harness import (
    LoopbackSession, QueuedMainLoop, packet,
)
from tests.shared.test_compat_lifecycle import Harness
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeAction


CONTROLLER_LIFECYCLE = '''
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
        self.controller._linux_rdaccess_script_call = lambda *args: calls.append(args)
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
