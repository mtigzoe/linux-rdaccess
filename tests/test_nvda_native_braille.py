"""NVDA-native semantic braille negotiation and fallback tests."""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import a11y_model
import orca_adapter
import remote_access
from tests.test_a11y_model import FakeAccessible, FakeAction


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
            "linux_rdaccess_a11y_model": a11y_model,
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
            "linux_rdaccess_a11y_model": a11y_model,
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

    def test_missing_orca_focus_fails_closed(self):
        orca_state = types.ModuleType("orca.orca_state")
        orca_state.locusOfFocus = None
        orca = types.ModuleType("orca")
        orca.orca_state = orca_state
        with mock.patch.dict(sys.modules, {
            "orca": orca,
            "orca.orca_state": orca_state,
            "linux_rdaccess_a11y_model": a11y_model,
        }):
            self.assertIsNone(orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload())


class CustomizationSemanticBrailleTests(unittest.TestCase):
    def run_hook(self, *, native=False, semantic=None):
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
        controller = types.SimpleNamespace(
            transport=types.SimpleNamespace(
                connected=True,
                connection_type="slave",
                send=lambda **kwargs: messages.append(kwargs),
            ),
            _lrd_nvda_native_braille=native,
            _lrd_last_semantic_braille=None,
        )
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

    def test_without_capability_raw_orca_cells_remain_fallback(self):
        result, messages, _ = self.run_hook(
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

    def test_semantic_snapshot_failure_falls_back_to_raw_cells(self):
        _, messages, _ = self.run_hook(native=True, semantic=None)
        self.assertEqual(
            messages,
            [
                {"type": "display", "cells": [1, 2, 3, 0]},
                {"type": "display", "cells": [1, 2, 3, 0]},
            ],
        )


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
