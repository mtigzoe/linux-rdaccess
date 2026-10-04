from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from orca_adapter import ELEMENT_LIST_TYPES, OrcaRuntimeAdapter


class ElementsListTests(unittest.TestCase):

    def test_elements_list_labels_and_focuses_category_control(self):
        class FakeBox:
            def pack_start(self, *args):
                pass

        class FakeCombo:
            last = None

            def __init__(self):
                self.items = []
                self.active = None
                self.focused = False
                FakeCombo.last = self

            def append(self, key, name):
                self.items.append((key, name))

            def set_active(self, index):
                self.active = index

            def get_active_id(self):
                return self.items[self.active][0]

            def grab_focus(self):
                self.focused = True

        class FakeLabel:
            last = None

            def __init__(self, label):
                self.label = label
                self.underline = False
                self.mnemonic = None
                FakeLabel.last = self

            def set_use_underline(self, value):
                self.underline = value

            def set_xalign(self, value):
                pass

            def set_mnemonic_widget(self, widget):
                self.mnemonic = widget

        class FakeDialog:
            def __init__(self, title):
                self.box = FakeBox()

            def set_modal(self, value):
                pass

            def add_button(self, *args):
                pass

            def get_content_area(self):
                return self.box

            def show_all(self):
                pass

            def run(self):
                return 1

            def destroy(self):
                pass

        fake_gtk = types.SimpleNamespace(
            Dialog=FakeDialog,
            Label=FakeLabel,
            ComboBoxText=FakeCombo,
            ResponseType=types.SimpleNamespace(CANCEL=0, OK=1),
        )
        gi = types.ModuleType("gi")
        gi.require_version = lambda *args: None
        repository = types.ModuleType("gi.repository")
        repository.Gtk = fake_gtk
        gi.repository = repository
        calls = []
        with mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
            from orca_adapter import show_elements_list
            self.assertTrue(show_elements_list(calls.append))
        self.assertTrue(FakeCombo.last.focused)
        self.assertTrue(FakeLabel.last.underline)
        self.assertIs(FakeLabel.last.mnemonic, FakeCombo.last)
        self.assertEqual(calls, ["h"])

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

    def test_snake_case_active_script_is_used_when_camelcase_is_none(self):
        calls = []
        script = types.SimpleNamespace(
            pan_braille_left=lambda event=None: calls.append("left"),
        )
        orca = types.ModuleType("orca")
        state = types.ModuleType("orca.orca_state")
        state.activeScript = None
        state.active_script = script
        orca.orca_state = state
        with mock.patch.dict(sys.modules, {"orca": orca, "orca.orca_state": state}):
            self.assertTrue(OrcaRuntimeAdapter.pan_braille_left())
        self.assertEqual(calls, ["left"])

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

    def test_structural_list_uses_orca42_enabled_object_show_list(self):
        calls = []
        script = types.SimpleNamespace()
        heading = types.SimpleNamespace(
            bindings={"list": ["h", 0, "Headings"]},
            showList=lambda script_obj, event: calls.append(
                ("headings", script_obj is script, event)
            ),
        )
        link = types.SimpleNamespace(
            bindings={"list": ["k", 0, "Links"]},
            showList=lambda script_obj, event: calls.append(
                ("links", script_obj is script, event)
            ),
        )
        script.structuralNavigation = types.SimpleNamespace(
            enabledObjects={"heading": heading, "link": link}
        )
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.show_structural_list("h"))
            self.assertFalse(OrcaRuntimeAdapter.show_structural_list("m"))
        self.assertEqual(calls, [("headings", True, None)])

    def test_bypass_next_command_supports_legacy_and_snake_case_handlers(self):
        legacy_calls = []
        legacy = types.SimpleNamespace(
            bypassNextCommand=lambda event=None: legacy_calls.append(event)
        )
        with self._fake_orca(legacy):
            self.assertTrue(OrcaRuntimeAdapter.bypass_next_command())
        self.assertEqual(legacy_calls, [None])

        snake_calls = []
        snake = types.SimpleNamespace(
            bypass_next_command=lambda event=None: snake_calls.append(event)
        )
        with self._fake_orca(snake, snake_state=True):
            self.assertTrue(OrcaRuntimeAdapter.bypass_next_command())
        self.assertEqual(snake_calls, [None])

    def test_braille_to_focus_supports_legacy_and_snake_case_handlers(self):
        legacy_calls = []
        legacy = types.SimpleNamespace(
            goBrailleHome=lambda event=None: legacy_calls.append(event)
        )
        with self._fake_orca(legacy):
            self.assertTrue(OrcaRuntimeAdapter.to_braille_focus())
        self.assertEqual(legacy_calls, [None])

        snake_calls = []
        snake = types.SimpleNamespace(
            go_braille_home=lambda event=None: snake_calls.append(event)
        )
        with self._fake_orca(snake, snake_state=True):
            self.assertTrue(OrcaRuntimeAdapter.to_braille_focus())
        self.assertEqual(snake_calls, [None])

    def test_browse_and_structural_navigation_support_legacy_handlers(self):
        calls = []
        script = types.SimpleNamespace()
        script.togglePresentationMode = lambda event=None: calls.append(("presentation", event))
        script.structuralNavigation = types.SimpleNamespace(
            toggleStructuralNavigation=lambda script_obj, event=None: calls.append(
                ("structural", script_obj is script, event)
            )
        )
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.toggle_presentation_mode())
            self.assertTrue(OrcaRuntimeAdapter.toggle_structural_navigation())
        self.assertEqual(
            calls,
            [("presentation", None), ("structural", True, None)],
        )

    def test_structural_navigation_supports_snake_case_aliases(self):
        calls = []
        script = types.SimpleNamespace()
        script.toggle_presentation_mode = lambda event=None: calls.append(("presentation", event))
        script.structural_navigation = types.SimpleNamespace(
            toggle_structural_navigation=lambda script_obj, event=None: calls.append(
                ("structural", script_obj is script, event)
            )
        )
        with self._fake_orca(script, snake_state=True):
            self.assertTrue(OrcaRuntimeAdapter.toggle_presentation_mode())
            self.assertTrue(OrcaRuntimeAdapter.toggle_structural_navigation())
        self.assertEqual(
            calls,
            [("presentation", None), ("structural", True, None)],
        )

    def test_say_all_supports_legacy_and_snake_case_handlers(self):
        legacy_calls = []
        legacy = types.SimpleNamespace(
            sayAll=lambda event=None: legacy_calls.append(event)
        )
        with self._fake_orca(legacy):
            self.assertTrue(OrcaRuntimeAdapter.say_all())
        self.assertEqual(legacy_calls, [None])

        snake_calls = []
        snake = types.SimpleNamespace(
            say_all=lambda event=None: snake_calls.append(event)
        )
        with self._fake_orca(snake, snake_state=True):
            self.assertTrue(OrcaRuntimeAdapter.say_all())
        self.assertEqual(snake_calls, [None])

    def test_title_and_status_support_legacy_and_snake_case_handlers(self):
        legacy_calls = []
        legacy = types.SimpleNamespace(
            presentTitle=lambda event=None: legacy_calls.append(("title", event)),
            presentStatusBar=lambda event=None: legacy_calls.append(("status", event)),
        )
        with self._fake_orca(legacy):
            self.assertTrue(OrcaRuntimeAdapter.present_title())
            self.assertTrue(OrcaRuntimeAdapter.present_status_bar())
        self.assertEqual(legacy_calls, [("title", None), ("status", None)])

        snake_calls = []
        snake = types.SimpleNamespace(
            present_title=lambda event=None: snake_calls.append(("title", event)),
            present_status_bar=lambda event=None: snake_calls.append(("status", event)),
        )
        with self._fake_orca(snake, snake_state=True):
            self.assertTrue(OrcaRuntimeAdapter.present_title())
            self.assertTrue(OrcaRuntimeAdapter.present_status_bar())
        self.assertEqual(snake_calls, [("title", None), ("status", None)])

    def test_where_am_i_uses_orca42_basic_handler(self):
        calls = []
        script = types.SimpleNamespace(
            whereAmIBasic=lambda event: calls.append(("basic", event))
        )
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.where_am_i())
        self.assertEqual(calls, [("basic", None)])

    def test_where_am_i_uses_available_fallback_handler(self):
        calls = []
        script = types.SimpleNamespace(
            presentCurrentObject=lambda event=None: calls.append(event)
        )
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.where_am_i())
        self.assertEqual(calls, [None])


if __name__ == "__main__":
    unittest.main()
