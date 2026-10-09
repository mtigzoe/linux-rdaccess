"""NVDA Remote braille script names preserve the driver's original case.

NVDA 2026.2 papenmeier, brailleNote and seikantk bind kb:pageup/pagedown.
scriptHandler._makeKbEmulateScript and getScriptName preserve those names;
KeyboardInputGesture.fromName accepts named keys and modifiers without case.
These tests reuse the installed-controller harness and do not infer gestures
from a display's model or raw hardware identifiers.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.test_compat_lifecycle import Harness


class BrailleProtocolTests(Harness, unittest.TestCase):
    GLOBAL = ["globalCommands", "GlobalCommands"]

    def _send(self, controller, name, **metadata):
        controller._on_remote_braille_input(scriptPath=self.GLOBAL + [name], **metadata)

    def _keys(self, controller):
        return [event[:3] for event in controller.local_machine.events if event[0] == "key"]

    def test_upstream_lowercase_page_bindings_reach_linux(self):
        # These are exact driver gesture identifiers from NVDA release-2026.2.
        bindings = (
            ("br(papenmeier):space+d3", "kb:pageup", 0x21),
            ("br(papenmeier):space+d6", "kb:pagedown", 0x22),
            ("br(braillenote):space+d1+d3", "kb:pageup", 0x21),
            ("br(braillenote):space+d4+d6", "kb:pagedown", 0x22),
            ("br(seikantk):SPACE+LJ_RIGHT", "kb:pageup", 0x21),
            ("br(seikantk):SPACE+LJ_LEFT", "kb:pagedown", 0x22),
        )
        for identifier, name, vk in bindings:
            with self.subTest(identifier=identifier, name=name):
                c, _, _ = self._patched_controller()
                self._send(c, name, identifiers=[identifier], dots=0, space=False)
                self.assertEqual(self._keys(c), [("key", vk, True), ("key", vk, False)])
                self.assertFalse(c._lrd_forwarded)

    def test_existing_and_case_variant_named_keys_use_the_same_canonical_commands(self):
        keys = (("upArrow", 0x26), ("downArrow", 0x28), ("leftArrow", 0x25),
                ("rightArrow", 0x27), ("pageUp", 0x21), ("pageDown", 0x22),
                ("home", 0x24), ("end", 0x23), ("enter", 0x0D),
                ("tab", 0x09), ("escape", 0x1B), ("backspace", 0x08),
                ("delete", 0x2E))
        for canonical, vk in keys:
            for variant in (canonical, canonical.lower(), canonical.upper()):
                with self.subTest(canonical=canonical, variant=variant):
                    c, _, _ = self._patched_controller()
                    payload = {"scriptPath": self.GLOBAL + ["kb:" + variant]}
                    action, record = c._linux_rdaccess_classify_braille(payload)
                    self.assertEqual(action, "key")
                    self.assertEqual(record, {
                        "action": "key", "scriptPath": self.GLOBAL + ["kb:" + canonical],
                    })
                    self._send(c, "kb:" + variant)
                    self.assertEqual(self._keys(c), [("key", vk, True), ("key", vk, False)])

    def test_case_variant_modifiers_borrow_existing_held_keys(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0xA0, True)
        c.local_machine.events.clear()
        self._send(c, "kb:Shift+CONTROL+PageDOWN")
        self.assertEqual(self._keys(c), [
            ("key", 0xA2, True), ("key", 0x22, True),
            ("key", 0x22, False), ("key", 0xA2, False),
        ])
        self.assertEqual(set(c._lrd_forwarded), {(0xA0, False)})
        self._key(c, 0xA0, False)
        self.assertFalse(c._lrd_forwarded)

    def test_braille_key_does_not_release_a_held_name_only_keyboard_key(self):
        for name, gesture in (("Tab", "tab"), ("Return", "enter"), ("Down", "downArrow")):
            with self.subTest(name=name):
                c, _, _ = self._patched_controller()
                c._on_remote_key(key_name=name, pressed=True)
                c.local_machine.events.clear()
                self._send(c, "kb:" + gesture)
                self.assertEqual(self._keys(c), [])
                self.assertEqual(set(c._lrd_forwarded), {(name, False)})
                c._on_remote_key(key_name=name, pressed=False)
                self.assertEqual(self._keys(c), [("key", None, False)])
                self.assertFalse(c._lrd_forwarded)

    def test_braille_chord_borrows_name_only_modifiers_without_releasing_them(self):
        for name, modifier in (("Shift_L", "shift"), ("Control_L", "control"),
                               ("Alt_L", "alt")):
            with self.subTest(name=name):
                c, _, _ = self._patched_controller()
                c._on_remote_key(key_name=name, pressed=True)
                c.local_machine.events.clear()
                self._send(c, "kb:" + modifier + "+tab")
                self.assertEqual(self._keys(c), [("key", 0x09, True), ("key", 0x09, False)])
                self.assertEqual(set(c._lrd_forwarded), {(name, False)})
                c._on_remote_key(key_name=name, pressed=False)
                self.assertFalse(c._lrd_forwarded)

    def test_v99_controller_upgrades_without_replacing_its_original_backup(self):
        import remote_access
        _, path, _ = self._patched_controller()
        backup = path.with_name(path.name + ".linux-rdaccess-backup")
        original = backup.read_text()
        path.write_text(path.read_text().replace(
            remote_access.LEGACY_COMPAT_MARKER, remote_access.LEGACY_COMPAT_MARKER_V99))
        self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
        self.assertTrue(remote_access.legacy_controller_patch_current(path.read_text()))
        self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))
        self.assertEqual(backup.read_text(), original)

    def test_unknown_character_and_malformed_commands_stay_redacted(self):
        c, _, _ = self._patched_controller()
        for name in ("kb:A", "kb:Control+A", "kb:SPACE", "kb:private-sentinel",
                     "kb:Shift+shift+TAB", "kb:CTRL+Tab", "kb:Windows+Tab", "kb:"):
            with self.subTest(name=name):
                action, record = c._linux_rdaccess_classify_braille({
                    "scriptPath": self.GLOBAL + [name], "id": "private-sentinel",
                })
                self.assertEqual(action, "keyboard")
                self.assertEqual(record, {"redacted": "braille-keyboard-input"})
                self._send(c, name, id="private-sentinel")
        self.assertEqual(self._keys(c), [])

    def test_case_variants_do_not_authorize_an_unknown_script_location(self):
        c, _, _ = self._patched_controller()
        c._on_remote_braille_input(
            scriptPath=["private-sentinel", "AddonCommands", "kb:PAGEUP"],
            routingIndex=4,
        )
        self.assertEqual(self._keys(c), [])

    def test_trace_records_only_canonical_key_and_modifier_names(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_sync_state()
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_TRACE": "1"}), \
                mock.patch.object(c, "_linux_rdaccess_trace") as trace, \
                mock.patch.object(c, "_linux_rdaccess_trace_braille") as braille_trace:
            self._send(c, "kb:Shift+PAGEUP", id="private-sentinel",
                       identifiers=["private-sentinel"], source="private-sentinel",
                       model="private-sentinel", dots=3, space=True)
        braille_trace.assert_called_once_with({
            "action": "key", "scriptPath": self.GLOBAL + ["kb:shift+pageUp"],
        })
        rows = [call for call in trace.call_args_list if call.args == ("braille",)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kwargs["emulated"], {"mods": ["shift"], "key": "pageUp"})
        self.assertNotIn("private-sentinel", str(trace.call_args_list))
        self.assertNotIn("private-sentinel", str(braille_trace.call_args_list))

    def test_failed_case_variant_key_release_is_retried_before_modifier_cleanup(self):
        for failure in (False, OSError("private-sentinel")):
            with self.subTest(failure=type(failure).__name__):
                c, _, _ = self._patched_controller()
                successes = []
                failed = []

                def send(**payload):
                    event = (payload["vk_code"], payload["pressed"])
                    if event == (0x21, False) and not failed:
                        failed.append(event)
                        if isinstance(failure, Exception):
                            raise failure
                        return failure
                    successes.append(event)
                    return True

                c.local_machine.send_key = send
                with mock.patch.object(c._module.log, "error") as error:
                    self._send(c, "kb:SHIFT+pageup")
                self.assertNotIn("private-sentinel", str(error.call_args_list))
                self.assertEqual(successes, [
                    (0xA0, True), (0x21, True), (0x21, False), (0xA0, False),
                ])
                self.assertFalse(c._lrd_forwarded)
                c._linux_rdaccess_reset_keys()
                self.assertEqual(len(successes), 4)
                self._send(c, "kb:pagedown")
                self.assertEqual(successes[-2:], [(0x22, True), (0x22, False)])

    def test_reset_discards_queued_routing_and_later_braille_commands_still_work(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        calls = []
        c._linux_rdaccess_script_call = lambda *args: calls.append(args)
        with patches:
            self._send(c, "braille_routeTo", routingIndex=4)
            c._linux_rdaccess_reset_keys()
            while queue:
                queue.pop(0)()
            self.assertEqual(calls, [])
            self._send(c, "braille_scrollForward")
            while queue:
                queue.pop(0)()
            self._send(c, "kb:pageup")
        self.assertEqual(calls, [("panBrailleRight",)])
        self.assertEqual(self._keys(c), [("key", 0x21, True), ("key", 0x21, False)])


if __name__ == "__main__":
    unittest.main()
