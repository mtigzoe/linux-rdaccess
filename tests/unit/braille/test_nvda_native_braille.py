"""NVDA-native semantic braille negotiation and fallback tests."""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import a11y_model
import orca_adapter
import remote_access
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeAction


class SemanticFocusPayloadTests(unittest.TestCase):
    def test_orca_focus_is_serialized_with_name_role_and_state(self):
        app = FakeAccessible("Smoke App", "application")
        button = FakeAccessible(
            "Apply changes",
            "push button",
            app,
            states=("focusable", "enabled"),
        )
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = button
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
        self.assertIsNotNone(payload)
        by_id = {item["id"]: item for item in payload["objects"]}
        focus = by_id[payload["focus_id"]]
        self.assertEqual(focus["name"], "Apply changes")
        self.assertEqual(focus["role"], "push button")
        self.assertIn("focused", focus["states"])
        self.assertIn("focusable", focus["states"])


    def test_semantic_focus_registry_performs_only_current_bounded_actions(self):
        action = FakeAction(["click"])
        app = FakeAccessible("Smoke App", "application")
        button = FakeAccessible(
            "Apply changes",
            "push button",
            app,
            states=("focusable", "enabled"),
            action_iface=action,
        )
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = button
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
            self.assertIsNotNone(payload)
            focus_id = payload["focus_id"]
            self.assertTrue(
                orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(focus_id, 0),
            )
            self.assertEqual(action.performed, [0])
            self.assertFalse(
                orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(focus_id, 32),
            )
            orca_adapter.OrcaRuntimeAdapter.clear_semantic_focus()
            self.assertFalse(
                orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(focus_id, 0),
            )


    def test_oversized_semantic_tree_fails_back_and_clears_previous_action_registry(self):
        action = FakeAction(["click"])
        first_app = FakeAccessible("First App", "application")
        first = FakeAccessible(
            "First button",
            "push button",
            first_app,
            action_iface=action,
        )
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = first
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
            self.assertIsNotNone(payload)
            old_id = payload["focus_id"]
            self.assertTrue(
                orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(old_id, 0))

            large_app = FakeAccessible("Large App", "application")
            large_focus = FakeAccessible(
                "Focused",
                "push button",
                large_app,
                "x" * 8192,
            )
            for index in range(30):
                FakeAccessible(
                    f"Sibling {index}",
                    "push button",
                    large_app,
                    "y" * 8192,
                )
            orca_state.locusOfFocus = large_focus
            self.assertIsNone(
                orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload())
            self.assertFalse(
                orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(old_id, 0))

    def test_missing_orca_focus_fails_closed(self):
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = None
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            self.assertIsNone(orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload())


class CustomizationSemanticBrailleTests(unittest.TestCase):
    def run_hook(self, *, native=False, semantic=None, offer_available=True,
                 offer_error=None):
        messages = []
        braille = types.ModuleType("orca.braille")
        braille.refresh = mock.Mock(return_value="native refresh")

        class Adapter:
            @staticmethod
            def semantic_focus_payload():
                return semantic

            @staticmethod
            def braille_cells(*, get_link_mask=True):
                return [1, 2, 3, 0]

        adapter = types.ModuleType("linux_rdaccess_orca_adapter")
        adapter.OrcaRuntimeAdapter = Adapter
        orca = types.ModuleType("orca")
        orca.braille = braille
        offers = []
        controller = types.SimpleNamespace(
            transport=types.SimpleNamespace(
                connected=True,
                connection_type="slave",
                send=lambda **kwargs: messages.append(kwargs),
            ),
            _lrd_nvda_native_braille=native,
            _lrd_last_semantic_braille=None,
            _linux_rdaccess_offer_native_braille=lambda: offers.append(True),
        )
        controller._lrd_native_braille_offers = offers
        if not offer_available:
            del controller._linux_rdaccess_offer_native_braille
        elif offer_error is not None:
            controller._linux_rdaccess_offer_native_braille = mock.Mock(side_effect=offer_error)
        namespace = {"controller": controller, "_dbg": lambda *_args: None}
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.braille": braille,
            "linux_rdaccess_orca_adapter": adapter,
        }):
            exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, namespace)
            first = braille.refresh()
            second = braille.refresh()
        return first, messages, controller

    def test_without_capability_raw_orca_cells_remain_fallback_and_reoffers(self):
        result, messages, controller = self.run_hook(
            native=False,
            semantic={"focus_id": "button", "objects": []},
        )
        self.assertEqual(result, "native refresh")
        self.assertEqual(
            messages,
            [
                {"type": "display", "cells": [1, 2, 3, 0]},
                {"type": "display", "cells": [1, 2, 3, 0]},
            ],
        )
        self.assertEqual(controller._lrd_native_braille_offers, [True, True])

    def test_older_controller_without_semantic_offer_still_forwards_raw_cells(self):
        result, messages, _controller = self.run_hook(offer_available=False)
        self.assertEqual(result, "native refresh")
        self.assertEqual(messages, [
            {"type": "display", "cells": [1, 2, 3, 0]},
            {"type": "display", "cells": [1, 2, 3, 0]},
        ])

    def test_failed_optional_semantic_offer_still_forwards_raw_cells(self):
        result, messages, controller = self.run_hook(
            offer_error=RuntimeError("capability unavailable"))
        self.assertEqual(result, "native refresh")
        self.assertEqual(messages, [
            {"type": "display", "cells": [1, 2, 3, 0]},
            {"type": "display", "cells": [1, 2, 3, 0]},
        ])
        self.assertEqual(controller._linux_rdaccess_offer_native_braille.call_count, 2)

    def test_v2_optional_negotiation_hook_upgrade_is_strict_and_idempotent(self):
        original = remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V2
        self.assertFalse(remote_access.legacy_customization_braille_cells_patch_current(original))
        updated = remote_access._patch_legacy_customization_braille_cells(original)
        self.assertTrue(remote_access.legacy_customization_braille_cells_patch_current(updated))
        self.assertEqual(remote_access._patch_legacy_customization_braille_cells(updated), updated)
        tampered = original.replace("cells=cells", "cells=[]")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            remote_access._patch_legacy_customization_braille_cells(tampered)

    def test_capability_sends_semantics_and_dedupes_identical_focus(self):
        semantic = {
            "focus_id": "button",
            "objects": [{
                "id": "button",
                "name": "Apply changes",
                "role": "push button",
            }],
        }
        _, messages, controller = self.run_hook(native=True, semantic=semantic)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["type"], "lrd_a11y_focus")
        self.assertEqual(messages[0]["version"], 1)
        self.assertEqual(messages[0]["focus_id"], "button")
        self.assertEqual(messages[0]["objects"], semantic["objects"])
        self.assertIsNotNone(controller._lrd_last_semantic_braille)

    def test_semantic_snapshot_failure_notifies_windows_then_falls_back_to_raw_cells(self):
        _, messages, controller = self.run_hook(native=True, semantic=None)
        self.assertEqual(
            messages,
            [
                {"type": "lrd_a11y_fallback", "version": 1},
                {"type": "display", "cells": [1, 2, 3, 0]},
                {"type": "display", "cells": [1, 2, 3, 0]},
            ],
        )
        self.assertFalse(controller._lrd_nvda_native_braille)
        self.assertEqual(controller._lrd_native_braille_offers, [True])


class LegacyStateSet:
    def __init__(self, *states):
        self._states = states

    def getStates(self):
        return list(self._states)


class LegacyAction:
    def __init__(self):
        self.nActions = 1
        self.performed = []

    def getName(self, index):
        return "click" if index == 0 else ""

    def doAction(self, index):
        self.performed.append(index)
        return True


class LegacyText:
    def __init__(self, text, caret):
        self.characterCount = len(text)
        self.caretOffset = caret
        self._text = text
        self.nSelections = 0

    def getText(self, start, end):
        return self._text[start:end]

    def getNSelections(self):
        return self.nSelections

    def setCaretOffset(self, offset):
        self.caretOffset = offset
        return True


class LegacyAccessible:
    def __init__(self, name, role, parent=None, *, states=(), action=None, text=None):
        self.name = name
        self._role = role
        self.parent = parent
        self.children = []
        self.childCount = 0
        self._states = states
        self._action = action
        self._text = text
        self.description = ""
        if parent is not None:
            parent.children.append(self)
            parent.childCount = len(parent.children)

    def getRoleName(self):
        return self._role

    def getState(self):
        return LegacyStateSet(*self._states)

    def getChildAtIndex(self, index):
        return self.children[index]

    def queryAction(self):
        if self._action is None:
            raise RuntimeError("no action")
        return self._action

    def queryText(self):
        if self._text is None:
            raise RuntimeError("no text")
        return self._text


class Orca42LegacyApiTests(unittest.TestCase):
    def test_semantic_focus_supports_pyatspi_style_name_role_tree_and_actions(self):
        action = LegacyAction()
        app = LegacyAccessible("Smoke App", "application")
        button = LegacyAccessible(
            "Apply changes",
            "push button",
            app,
            states=("focusable", "enabled"),
            action=action,
        )
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = button
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
            self.assertIsNotNone(payload)
            focus = next(item for item in payload["objects"]
                         if item["id"] == payload["focus_id"])
            self.assertEqual(focus["name"], "Apply changes")
            self.assertEqual(focus["role"], "push button")
            self.assertIn("focusable", focus["states"])
            self.assertEqual(focus["actions"], ["click"])
            self.assertTrue(
                orca_adapter.OrcaRuntimeAdapter.perform_semantic_action(
                    payload["focus_id"], 0))
        self.assertEqual(action.performed, [0])

    def test_semantic_focus_supports_pyatspi_query_text_and_caret(self):
        app = LegacyAccessible("Editor App", "application")
        editor = LegacyAccessible(
            "Notes",
            "text",
            app,
            states=("focusable", "editable"),
            text=LegacyText("alpha bravo", 5),
        )
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = editor
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
        self.assertIsNotNone(payload)
        focus = next(item for item in payload["objects"]
                     if item["id"] == payload["focus_id"])
        self.assertTrue(focus["text_supported"])
        self.assertEqual(focus["text"], "alpha bravo")
        self.assertEqual(focus["caret_offset"], 5)

    def test_semantic_text_routing_updates_only_current_registered_object(self):
        text = LegacyText("alpha bravo", 2)
        app = LegacyAccessible("Editor App", "application")
        editor = LegacyAccessible(
            "Notes",
            "text",
            app,
            states=("focusable", "editable"),
            text=text,
        )
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = editor
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
        }):
            payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
            self.assertIsNotNone(payload)
            focus_id = payload["focus_id"]
            self.assertTrue(
                orca_adapter.OrcaRuntimeAdapter.set_semantic_caret(focus_id, 7))
            self.assertEqual(text.caretOffset, 7)
            self.assertFalse(
                orca_adapter.OrcaRuntimeAdapter.set_semantic_caret(focus_id, 99))
            orca_adapter.OrcaRuntimeAdapter.clear_semantic_focus()
            self.assertFalse(
                orca_adapter.OrcaRuntimeAdapter.set_semantic_caret(focus_id, 1))

    def test_legacy_action_exception_fails_closed(self):
        class BrokenAction(LegacyAction):
            def doAction(self, index):
                raise RuntimeError("gone")

        button = LegacyAccessible(
            "Gone", "push button", action=BrokenAction())
        self.assertFalse(a11y_model.perform_action(button, 0))


class SemanticBrailleUpgradeTests(unittest.TestCase):
    def test_v1_braille_hook_upgrades_to_v2_and_is_idempotent(self):
        source = "# before\n" + remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V1 + "\n# after\n"
        updated = remote_access._patch_legacy_customization_braille_cells(source)
        self.assertIn(remote_access.CUSTOMIZATION_BRAILLE_CELLS_MARKER, updated)
        self.assertNotIn(remote_access.CUSTOMIZATION_BRAILLE_CELLS_MARKER_V1, updated)
        self.assertTrue(remote_access.legacy_customization_braille_cells_patch_current(updated))
        self.assertEqual(remote_access._patch_legacy_customization_braille_cells(updated), updated)

    def test_damaged_v1_hook_is_rejected_instead_of_guessed(self):
        damaged = remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK_V1.replace(
            "cells=cells", "cells=[]", 1)
        with self.assertRaisesRegex(ValueError, "incomplete legacy"):
            remote_access._patch_legacy_customization_braille_cells(damaged)


if __name__ == "__main__":
    unittest.main()
