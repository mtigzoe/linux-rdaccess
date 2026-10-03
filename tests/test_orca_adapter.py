from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from orca_adapter import ELEMENT_LIST_TYPES, OrcaRuntimeAdapter


class ElementsListTests(unittest.TestCase):
    def test_nvda_elements_categories_cover_primary_orca_structural_lists(self):
        categories = dict(ELEMENT_LIST_TYPES)
        self.assertEqual(categories["Headings"], "h")
        self.assertEqual(categories["Links"], "k")
        self.assertEqual(categories["Form fields"], "f")
        self.assertEqual(categories["Buttons"], "b")
        self.assertEqual(categories["Tables"], "t")
        self.assertEqual(categories["Landmarks"], "m")


class OrcaRuntimeAdapterTests(unittest.TestCase):
    def _fake_orca(self, script, *, snake_state=False):
        orca = types.ModuleType("orca")
        state = types.ModuleType("orca.orca_state")
        if snake_state:
            state.active_script = script
        else:
            state.activeScript = script
        orca.orca_state = state
        return mock.patch.dict(
            sys.modules,
            {"orca": orca, "orca.orca_state": state},
        )

    def test_orca42_camelcase_braille_handlers(self):
        calls = []
        script = types.SimpleNamespace(
            panBrailleLeft=lambda event=None: calls.append(("left", event)),
            panBrailleRight=lambda event=None: calls.append(("right", event)),
            processRoutingKey=lambda event=None: calls.append(
                ("route", event.event["argument"])
            ),
        )
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.pan_braille_left())
            self.assertTrue(OrcaRuntimeAdapter.pan_braille_right())
            self.assertTrue(OrcaRuntimeAdapter.route_braille(12))
        self.assertEqual(calls, [("left", None), ("right", None), ("route", 12)])

    def test_snake_case_aliases_are_supported(self):
        calls = []
        script = types.SimpleNamespace(
            pan_braille_left=lambda event=None: calls.append("left"),
            pan_braille_right=lambda event=None: calls.append("right"),
            process_routing_key=lambda event=None: calls.append(
                ("route", event.event["argument"])
            ),
        )
        with self._fake_orca(script, snake_state=True):
            self.assertTrue(OrcaRuntimeAdapter.pan_braille_left())
            self.assertTrue(OrcaRuntimeAdapter.pan_braille_right())
            self.assertTrue(OrcaRuntimeAdapter.route_braille(3))
        self.assertEqual(calls, ["left", "right", ("route", 3)])

    def test_invalid_routing_indexes_are_rejected(self):
        script = types.SimpleNamespace(
            processRoutingKey=lambda event=None: self.fail("must not be called")
        )
        with self._fake_orca(script):
            for value in (-1, 1024, True, "4", None):
                self.assertFalse(OrcaRuntimeAdapter.route_braille(value))

    def test_missing_active_script_is_safe(self):
        with self._fake_orca(None):
            self.assertFalse(OrcaRuntimeAdapter.pan_braille_left())
            self.assertFalse(OrcaRuntimeAdapter.route_braille(1))

    def test_where_am_i_uses_available_script_handler(self):
        calls = []
        script = types.SimpleNamespace(
            presentCurrentObject=lambda event=None: calls.append(event)
        )
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.where_am_i())
        self.assertEqual(calls, [None])


if __name__ == "__main__":
    unittest.main()
