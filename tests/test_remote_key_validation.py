"""Remote keyboard protocol boundaries must not mutate held-key ownership.

NVDA 2026.2 source/_remoteClient/client.py:processKeyInput forwards vk_code,
scan_code, extended and pressed from winInputHook's KBDLLHOOKSTRUCT callback.
The hook converts the flags to bool; vkCode and scanCode are DWORD fields.
The legacy Orca Remote path also accepts name-only keys and omitted scans.
"""
from __future__ import annotations

import copy
import os
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class RemoteKeyValidationTests(Harness, unittest.TestCase):
    def _state(self, controller):
        names = (
            "_lrd_down", "_lrd_forwarded", "_lrd_swapped", "_lrd_nvda_down",
            "_lrd_nvda_key", "_lrd_insert_pending", "_lrd_insert_used",
            "_lrd_caps_pending", "_lrd_caps_used",
        )
        return copy.deepcopy({name: getattr(controller, name, None) for name in names})

    def _keys(self, controller):
        return [event[:3] for event in controller.local_machine.events if event[0] == "key"]

    def test_malformed_pressed_flag_cannot_repeat_a_held_modifier(self):
        for value in ("false", "true", 2, -1, {}, [], None):
            with self.subTest(value=repr(value)):
                c, _, _ = self._patched_controller()
                self._key(c, 0xA0, True)
                before = self._state(c)
                self._key(c, 0xA0, value)
                self.assertEqual(self._state(c), before)
                self.assertEqual(self._keys(c), [("key", 0xA0, True)])
                self._key(c, 0xA0, False)
                c._linux_rdaccess_reset_keys()
                self.assertEqual(self._keys(c), [
                    ("key", 0xA0, True), ("key", 0xA0, False),
                ])
                self.assertFalse(c._lrd_forwarded)

    def test_malformed_extended_flag_cannot_misidentify_numpad_insert_release(self):
        for value in ("false", "true", 2, -1, {}, []):
            with self.subTest(value=repr(value)):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=False, scan_code=0x52)
                before = self._state(c)
                self._key(c, 0x2D, False, extended=value, scan_code=0x52)
                self.assertEqual(self._state(c), before)
                self.assertEqual(self._keys(c), [])
                # The real release still owns the pending press. It must not
                # leave a deferred Insert to leak into the next session/key.
                self._key(c, 0x2D, False, extended=False, scan_code=0x52)
                self._key(c, 0x41, True)
                self._key(c, 0x41, False)
                self.assertEqual(self._keys(c), [
                    ("key", 0x2D, True), ("key", 0x2D, False),
                    ("key", 0x41, True), ("key", 0x41, False),
                ])
                self.assertFalse(c._lrd_forwarded)
                self.assertIsNone(c._lrd_insert_pending)

    def test_invalid_key_fields_cannot_flush_deferred_nvda_modifiers(self):
        invalid_fields = {
            "vk_code": (True, False, "65", 65.0, -1, 256, [], {}),
            "scan_code": (True, False, "30", 30.0, -1, 0x100000000, [], {}),
            "key_name": (True, False, 65, 65.0, [], {}),
        }
        for field, values in invalid_fields.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    c, _, _ = self._patched_controller()
                    self._key(c, 0x14, True, scan_code=0x3A)
                    self._key(c, 0x2D, True, extended=True, scan_code=0x52)
                    before = self._state(c)
                    payload = dict(key_name=None, pressed=True, modifiers=None,
                                   vk_code=0x41, scan_code=0x1E, extended=False)
                    payload[field] = value
                    c._on_remote_key(**payload)
                    self.assertEqual(self._state(c), before)
                    self.assertEqual(self._keys(c), [])
                    c._linux_rdaccess_reset_keys()
                    self.assertEqual(self._keys(c), [])
                    self.assertFalse(c._lrd_down)
                    self.assertFalse(c._lrd_swapped)
                    self.assertIsNone(c._lrd_insert_pending)
                    self.assertIsNone(c._lrd_caps_pending)

    def test_boolean_and_binary_integer_flags_preserve_press_release(self):
        for down, up in ((True, False), (1, 0)):
            for extended in (None, False, True, 0, 1):
                with self.subTest(down=down, extended=extended):
                    c, _, _ = self._patched_controller()
                    self._key(c, 0x41, down, extended=extended, scan_code=None)
                    self._key(c, 0x41, up, extended=extended, scan_code=None)
                    self.assertEqual(self._keys(c), [
                        ("key", 0x41, down), ("key", 0x41, up),
                    ])
                    self.assertFalse(c._lrd_down)
                    self.assertFalse(c._lrd_forwarded)

    def test_legacy_name_only_and_missing_scan_keys_keep_release_ownership(self):
        c, _, _ = self._patched_controller()
        c._on_remote_key(key_name="Tab", pressed=True)
        c._on_remote_key(key_name="Tab", pressed=False)
        c._linux_rdaccess_reset_keys()
        keys = [event for event in c.local_machine.events if event[0] == "key"]
        self.assertEqual(keys, [
            ("key", None, True, "Tab"), ("key", None, False, "Tab"),
        ])
        self.assertFalse(c._lrd_forwarded)

    def test_unknown_legal_vk_is_not_guessed_as_an_nvda_command(self):
        for vk in (0, 0xFF):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, vk, True, scan_code=0xFFFFFFFF)
                self._key(c, vk, False, scan_code=0xFFFFFFFF)
                self.assertEqual(self._keys(c), [
                    ("key", vk, True), ("key", vk, False),
                ])
                self.assertFalse(c._lrd_forwarded)

    def test_unowned_keyup_and_reset_do_not_duplicate_releases(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0xA2, False)
        self._key(c, 0xA2, True)
        self._key(c, 0xA2, True)
        self._key(c, 0xA2, False)
        self._key(c, 0xA2, False)
        c._linux_rdaccess_reset_keys()
        self.assertEqual(self._keys(c), [
            ("key", 0xA2, True), ("key", 0xA2, True), ("key", 0xA2, False),
        ])
        self.assertFalse(c._lrd_down)
        self.assertFalse(c._lrd_forwarded)

    def test_malformed_metadata_is_not_sent_to_private_input_trace(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        before = self._state(c)
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_TRACE": "1"}), \
                mock.patch.object(c, "_linux_rdaccess_trace") as trace, \
                mock.patch.object(c._module.log, "error") as error:
            c._on_remote_key(pressed="private-sentinel", vk_code=0x14,
                             extended="private-sentinel", scan_code="private-sentinel")
        self.assertEqual(self._state(c), before)
        trace.assert_not_called()
        self.assertNotIn("private-sentinel", str(error.call_args_list))
        self.assertEqual(self._keys(c), [])

    def test_key_without_an_identity_cannot_flush_a_deferred_nvda_modifier(self):
        for modifier, extended in ((0x14, False), (0x2D, False), (0x2D, True)):
            for payload in (
                {"pressed": True},
                {"pressed": True, "key_name": ""},
                {"pressed": True, "vk_code": None, "scan_code": 0x1E, "extended": False},
            ):
                with self.subTest(modifier=modifier, extended=extended, payload=payload):
                    c, _, _ = self._patched_controller()
                    self._key(c, modifier, True, extended=extended)
                    before = self._state(c)
                    c._on_remote_key(**payload)
                    self.assertEqual(self._state(c), before)
                    self.assertEqual(self._keys(c), [])
                    self._key(c, modifier, False, extended=extended)
                    self.assertEqual(self._keys(c), [
                        ("key", modifier, True), ("key", modifier, False),
                    ])
                    self.assertFalse(c._lrd_forwarded)


class NvdaModifierProtocolTests(Harness, unittest.TestCase):
    # NVDA keyboardHandler.isNVDAModifierKey distinguishes these VK_INSERT
    # forms solely by the extended flag. VK_NUMPAD0 is a different key when
    # Num Lock is on; it must never be guessed to mean an NVDA modifier.
    MODIFIERS = ((0x2D, False, 0x52), (0x2D, True, 0x52), (0x14, False, 0x3A))

    def test_all_nvda_modifier_forms_own_consumed_command_repeat_and_release(self):
        for vk, extended, scan in self.MODIFIERS:
            with self.subTest(vk=vk, extended=extended):
                c, _, _ = self._patched_controller()
                calls = []
                c._linux_rdaccess_script_call = lambda *args: calls.append(args)
                self._key(c, vk, True, extended=extended, scan_code=scan)
                self._key(c, vk, True, extended=extended, scan_code=scan)
                self._key(c, 0x54, True)
                self._key(c, 0x54, True)
                self._key(c, 0x54, False)
                self._key(c, vk, False, extended=extended, scan_code=scan)
                self.assertEqual(calls, [("presentTitle",)])
                self.assertFalse([e for e in c.local_machine.events if e[0] == "key"])
                self.assertFalse(c._lrd_down)
                self.assertFalse(c._lrd_swapped)
                self.assertFalse(getattr(c, "_lrd_forwarded", {}))
                self.assertIsNone(c._lrd_insert_pending)
                self.assertIsNone(c._lrd_caps_pending)

    def test_both_physical_insert_modifiers_do_not_overwrite_pending_ownership(self):
        forms = ((0x2D, False, 0x52), (0x2D, True, 0x52))
        for first, second in (forms, forms[::-1]):
            with self.subTest(first_extended=first[1]):
                c, _, _ = self._patched_controller()
                self._key(c, *first[:1], extended=first[1], scan_code=first[2], pressed=True)
                self._key(c, *second[:1], extended=second[1], scan_code=second[2], pressed=True)
                self._key(c, *second[:1], extended=second[1], scan_code=second[2], pressed=True)
                self._key(c, *second[:1], extended=second[1], scan_code=second[2], pressed=False)
                self._key(c, *first[:1], extended=first[1], scan_code=first[2], pressed=False)
                self.assertFalse([e for e in c.local_machine.events if e[0] == "key"])
                self.assertFalse(c._lrd_down)
                self.assertFalse(c._lrd_swapped)
                self.assertFalse(c._lrd_forwarded)
                self.assertIsNone(c._lrd_insert_pending)

    def test_both_physical_insert_modifiers_own_one_nvda_command(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        self._key(c, 0x2D, True, extended=True, scan_code=0x52)
        self._key(c, 0x2D, True, extended=False, scan_code=0x52)
        self._key(c, 0x54, True)
        self._key(c, 0x54, False)
        self._key(c, 0x2D, False, extended=False, scan_code=0x52)
        self._key(c, 0x2D, False, extended=True, scan_code=0x52)
        self.assertEqual(calls, [("presentTitle",)])
        self.assertFalse([e for e in c.local_machine.events if e[0] == "key"])
        self.assertFalse(c._lrd_down)
        self.assertFalse(c._lrd_swapped)
        self.assertIsNone(c._lrd_insert_pending)

    def test_numpad_zero_is_ordinary_input(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x60, True, scan_code=0x52)
        self._key(c, 0x60, False, scan_code=0x52)
        self.assertEqual([e[:3] for e in c.local_machine.events if e[0] == "key"], [
            ("key", 0x60, True), ("key", 0x60, False),
        ])
        self.assertFalse(c._lrd_nvda_down)

    def test_reset_and_reconnect_discard_each_unforwarded_modifier(self):
        for vk, extended, scan in self.MODIFIERS:
            with self.subTest(vk=vk, extended=extended):
                c, _, _ = self._patched_controller()
                self._key(c, vk, True, extended=extended, scan_code=scan)
                c._linux_rdaccess_reset_keys()
                c.transport.connected = False
                c._linux_rdaccess_sync_state()
                c.transport.connected = True
                c._linux_rdaccess_sync_state()
                self._key(c, vk, False, extended=extended, scan_code=scan)
                self._key(c, 0x41, True)
                self._key(c, 0x41, False)
                self.assertEqual([e[:3] for e in c.local_machine.events if e[0] == "key"], [
                    ("key", 0x41, True), ("key", 0x41, False),
                ])
                self.assertFalse(c._lrd_down)
                self.assertFalse(c._lrd_forwarded)

    def test_standalone_modifier_replays_original_scan_and_extended_payload_once(self):
        for vk, extended, scan in self.MODIFIERS:
            with self.subTest(vk=vk, extended=extended):
                c, _, _ = self._patched_controller()
                payloads = []
                c.local_machine.send_key = lambda **payload: payloads.append(payload) or True
                self._key(c, vk, True, extended=extended, scan_code=scan)
                self._key(c, vk, True, extended=extended, scan_code=scan)
                self._key(c, vk, False, extended=extended, scan_code=scan)
                c._linux_rdaccess_reset_keys()
                self.assertEqual([(p["vk_code"], p["pressed"], p["extended"], p["scan_code"])
                                  for p in payloads], [
                    (vk, True, extended, scan), (vk, False, extended, scan),
                ])
                self.assertFalse(c._lrd_forwarded)

    def test_pass_next_does_not_replay_any_consumed_nvda_modifier_form(self):
        for vk, extended, scan in self.MODIFIERS:
            with self.subTest(vk=vk, extended=extended):
                c, _, _ = self._patched_controller()
                # Receive-side bypass ownership is independent of a queued
                # Orca callback; this exercises the original F2 race too.
                c._linux_rdaccess_run_main = lambda callback: True
                self._key(c, vk, True, extended=extended, scan_code=scan)
                self._key(c, 0x71, True)
                self._key(c, 0x71, True)
                self._key(c, 0x71, False)
                self._key(c, 0x20, True)
                self._key(c, 0x20, False)
                self._key(c, vk, False, extended=extended, scan_code=scan)
                keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
                self.assertEqual(keys, [("key", 0x20, True), ("key", 0x20, False)])
                self.assertFalse(c._lrd_forwarded)
                self.assertFalse(c._lrd_down)
                self.assertFalse(c._lrd_swapped)

    def test_failed_replay_of_both_insert_forms_cannot_degrade_an_application_chord(self):
        for extended in (False, True):
            for failure in (False, OSError("backend unavailable")):
                with self.subTest(extended=extended, failure=type(failure).__name__):
                    c, _, _ = self._patched_controller()
                    attempts = []

                    def send(**payload):
                        attempts.append((payload["vk_code"], payload["pressed"]))
                        if payload["vk_code"] == 0x2D and payload["pressed"]:
                            if isinstance(failure, Exception):
                                raise failure
                            return failure
                        return True

                    c.local_machine.send_key = send
                    self._key(c, 0x2D, True, extended=extended, scan_code=0x52)
                    self._key(c, 0x59, True)
                    self._key(c, 0x59, True)
                    self._key(c, 0x59, False)
                    self._key(c, 0x2D, False, extended=extended, scan_code=0x52)
                    c._linux_rdaccess_reset_keys()
                    self.assertEqual(attempts, [(0x2D, True)])
                    self.assertFalse(getattr(c, "_lrd_forwarded", {}))
                    self.assertFalse(c._lrd_swapped)
                    self.assertIsNone(c._lrd_insert_pending)
                    self._key(c, 0x41, True)
                    self._key(c, 0x41, False)
                    self.assertEqual(attempts[-2:], [(0x41, True), (0x41, False)])


if __name__ == "__main__":
    unittest.main()
