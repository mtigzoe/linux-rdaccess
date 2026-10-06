from __future__ import annotations

import ast
from pathlib import Path
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
        self.assertEqual(calls, ["k"])

    def test_nvda_elements_categories_match_nvda_2026_2_default_order(self):
        self.assertEqual(
            ELEMENT_LIST_TYPES,
            (
                ("Links", "k"),
                ("Headings", "h"),
                ("Form fields", "f"),
                ("Buttons", "b"),
                ("Landmarks", "m"),
            ),
        )


class OrcaRuntimeAdapterTests(unittest.TestCase):
    def _fake_orca(self, script, *, snake_state=False, focus=None):
        orca = types.ModuleType("orca")
        state = types.ModuleType("orca.orca_state")
        if snake_state:
            state.active_script = script
        else:
            state.activeScript = script
        state.locusOfFocus = focus
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
            self.assertIsNone(OrcaRuntimeAdapter.pan_braille_left())
            self.assertIsNone(OrcaRuntimeAdapter.route_braille(1))

    def test_dispatch_preserves_explicit_false_without_trying_an_alias(self):
        handler = mock.Mock(return_value=False)
        alias = mock.Mock()
        script = types.SimpleNamespace(handler=handler, alias=alias)
        with self._fake_orca(script):
            self.assertIs(
                OrcaRuntimeAdapter.call_script(("handler", "alias"), default_event=True),
                False,
            )
        handler.assert_called_once_with(None)
        alias.assert_not_called()

    def test_dispatch_distinguishes_unavailable_handler_from_void_handler(self):
        handler = mock.Mock(return_value=None)
        script = types.SimpleNamespace(handler=handler)
        with self._fake_orca(script):
            self.assertIsNone(OrcaRuntimeAdapter.call_script("missing"))
            self.assertIs(OrcaRuntimeAdapter.call_script("handler", "message"), True)
        handler.assert_called_once_with("message")

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
            self.assertIsNone(OrcaRuntimeAdapter.show_structural_list("m"))
        self.assertEqual(calls, [("headings", True, None)])

    def test_structural_list_preserves_false_without_calling_another_match(self):
        handler = mock.Mock(return_value=False)
        duplicate_handler = mock.Mock()
        script = types.SimpleNamespace(structuralNavigation=types.SimpleNamespace(
            enabledObjects={
                "heading": types.SimpleNamespace(
                    bindings={"list": ["h", 0, "Headings"]}, showList=handler),
                "duplicate": types.SimpleNamespace(
                    bindings={"list": ["h", 0, "Headings"]}, showList=duplicate_handler),
            }
        ))
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.show_structural_list("h"), False)
        handler.assert_called_once_with(script, None)
        duplicate_handler.assert_not_called()

    def test_structural_list_can_use_explicit_originating_script(self):
        handler = mock.Mock()
        script = types.SimpleNamespace(structuralNavigation=types.SimpleNamespace(
            enabledObjects={"heading": types.SimpleNamespace(
                bindings={"list": ["h", 0, "Headings"]}, showList=handler)}))
        with mock.patch.object(
            OrcaRuntimeAdapter, "active_script", side_effect=AssertionError("wrong focus")
        ):
            self.assertIs(OrcaRuntimeAdapter.show_structural_list("h", script=script), True)
        handler.assert_called_once_with(script, None)

    def test_progress_output_cycles_four_states_without_touching_braille(self):
        state = {"speakProgressBarUpdates": True,
                 "beepProgressBarUpdates": True,
                 "brailleProgressBarUpdates": True}
        messages = []
        script = types.SimpleNamespace(presentMessage=messages.append)

        class Manager:
            def getSetting(self, name):
                return state.get(name)
            def setSetting(self, name, value):
                state[name] = value

        settings_manager = types.ModuleType("orca.settings_manager")
        settings_manager.getManager = lambda: Manager()
        for expected, label in (
            ((False, False), "No progress bar updates"),
            ((True, False), "Speak progress bar updates"),
            ((False, True), "Beep for progress bar updates"),
            ((True, True), "Beep and speak progress bar updates"),
        ):
            with self._fake_orca(script), mock.patch.dict(
                    sys.modules, {"orca.settings_manager": settings_manager}):
                self.assertIs(OrcaRuntimeAdapter.cycle_progress_bar_output(), True)
            self.assertEqual(
                (state["speakProgressBarUpdates"], state["beepProgressBarUpdates"]),
                expected,
            )
            self.assertTrue(state["brailleProgressBarUpdates"])
            self.assertEqual(messages[-1], label)

    def test_mouse_review_uses_orca_input_handler(self):
        calls = []
        handler = types.SimpleNamespace(
            function=lambda script, event=None: calls.append((script, event)))
        script = types.SimpleNamespace(
            inputEventHandlers={"toggleMouseReviewHandler": handler})
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.toggle_mouse_review(), True)
        self.assertEqual(calls, [(script, None)])

    def test_mouse_review_is_unsupported_without_native_handler(self):
        script = types.SimpleNamespace(inputEventHandlers={})
        with self._fake_orca(script):
            self.assertIsNone(OrcaRuntimeAdapter.toggle_mouse_review())

    def test_input_help_toggles_orca42_learn_mode(self):
        calls = []
        script = types.SimpleNamespace(
            enterLearnMode=lambda event=None: calls.append(("enter", event)) or True,
            exitLearnMode=lambda event=None: calls.append(("exit", event)) or True,
        )
        with self._fake_orca(script):
            state = sys.modules["orca.orca_state"]
            state.learnModeEnabled = False
            self.assertIs(OrcaRuntimeAdapter.toggle_input_help(), True)
            state.learnModeEnabled = True
            self.assertIs(OrcaRuntimeAdapter.toggle_input_help(), True)
        self.assertEqual(calls, [("enter", None), ("exit", None)])

    def test_input_help_distinguishes_unavailable_and_rejected_handlers(self):
        with self._fake_orca(None):
            self.assertIsNone(OrcaRuntimeAdapter.toggle_input_help())
        script = types.SimpleNamespace(enterLearnMode=mock.Mock(return_value=False))
        with self._fake_orca(script):
            sys.modules["orca.orca_state"].learnModeEnabled = False
            self.assertIs(OrcaRuntimeAdapter.toggle_input_help(), False)
        script.enterLearnMode.assert_called_once_with(None)

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
        self.assertEqual(calls[0][0], "presentation")
        self.assertTrue(calls[0][1])
        self.assertEqual(calls[0][1].event_string, "space")
        self.assertEqual(calls[1], ("structural", True, None))

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
        self.assertEqual(calls[0][0], "presentation")
        self.assertTrue(calls[0][1])
        self.assertEqual(calls[0][1].event_string, "space")
        self.assertEqual(calls[1], ("structural", True, None))

    def test_structural_navigation_distinguishes_unsupported_and_rejected_command(self):
        script = types.SimpleNamespace()
        with self._fake_orca(script):
            self.assertIsNone(OrcaRuntimeAdapter.toggle_structural_navigation())
        script.structuralNavigation = types.SimpleNamespace(
            toggleStructuralNavigation=mock.Mock(return_value=False))
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.toggle_structural_navigation(), False)
        script.structuralNavigation.toggleStructuralNavigation.assert_called_once_with(
            script, None)

    def test_explicit_focus_mode_command_focuses_entry_without_recent_navigation(self):
        entry = object()
        utilities = types.SimpleNamespace(
            grabFocusWhenSettingCaret=lambda obj: False,
            grabFocus=mock.Mock(),
        )
        script = types.SimpleNamespace(
            utilities=utilities,
            _lastCommandWasCaretNav=False,
            _lastCommandWasStructNav=False,
        )

        def toggle_mode(event):
            # Orca 42's web togglePresentationMode uses inputEvent truthiness
            # to distinguish explicit commands from automatic mode switches.
            if not script.utilities.grabFocusWhenSettingCaret(entry) and (
                script._lastCommandWasCaretNav
                or script._lastCommandWasStructNav
                or event
            ):
                script.utilities.grabFocus(entry)

        script.togglePresentationMode = toggle_mode
        with self._fake_orca(script):
            self.assertTrue(OrcaRuntimeAdapter.toggle_presentation_mode())
        utilities.grabFocus.assert_called_once_with(entry)

    def test_mode_toggle_guard_uses_snake_case_focus_when_camelcase_is_none(self):
        address_bar = object()
        script = types.SimpleNamespace(
            togglePresentationMode=mock.Mock(),
            utilities=types.SimpleNamespace(inDocumentContent=mock.Mock(return_value=False)),
        )
        with self._fake_orca(script):
            sys.modules["orca.orca_state"].locus_of_focus = address_bar
            self.assertIs(OrcaRuntimeAdapter.toggle_presentation_mode(), False)
        script.utilities.inDocumentContent.assert_called_once_with(address_bar)
        script.togglePresentationMode.assert_not_called()

    def test_mode_toggle_preserves_unavailable_and_rejected_handler_results(self):
        with self._fake_orca(None):
            self.assertIsNone(OrcaRuntimeAdapter.toggle_presentation_mode())
        with self._fake_orca(types.SimpleNamespace()):
            self.assertIsNone(OrcaRuntimeAdapter.toggle_presentation_mode())
        script = types.SimpleNamespace(togglePresentationMode=mock.Mock(return_value=False))
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.toggle_presentation_mode(), False)
        script.togglePresentationMode.assert_called_once()

    def test_show_preferences_uses_orca_global_preferences_command(self):
        calls = []
        script = types.SimpleNamespace()
        orca_pkg = types.ModuleType("orca")
        state = types.ModuleType("orca.orca_state")
        state.activeScript = script
        orca_module = types.ModuleType("orca.orca")
        orca_module.showPreferencesGUI = (
            lambda script_obj=None, event=None: calls.append((script_obj, event)) or True
        )
        orca_pkg.orca_state = state
        orca_pkg.orca = orca_module
        with mock.patch.dict(
            sys.modules,
            {
                "orca": orca_pkg,
                "orca.orca": orca_module,
                "orca.orca_state": state,
            },
        ):
            self.assertTrue(OrcaRuntimeAdapter.show_preferences())
        self.assertEqual(calls, [(script, None)])

    def test_show_preferences_returns_false_when_orca_command_is_unavailable(self):
        orca_pkg = types.ModuleType("orca")
        state = types.ModuleType("orca.orca_state")
        state.activeScript = types.SimpleNamespace()
        orca_module = types.ModuleType("orca.orca")
        orca_pkg.orca_state = state
        orca_pkg.orca = orca_module
        with mock.patch.dict(
            sys.modules,
            {
                "orca": orca_pkg,
                "orca.orca": orca_module,
                "orca.orca_state": state,
            },
        ):
            self.assertIsNone(OrcaRuntimeAdapter.show_preferences())

    def test_show_preferences_preserves_false_result(self):
        script = types.SimpleNamespace()
        orca_module = types.ModuleType("orca.orca")
        orca_module.showPreferencesGUI = mock.Mock(return_value=False)
        with self._fake_orca(script), mock.patch.dict(
            sys.modules, {"orca.orca": orca_module}
        ):
            sys.modules["orca"].orca = orca_module
            self.assertIs(OrcaRuntimeAdapter.show_preferences(), False)
        orca_module.showPreferencesGUI.assert_called_once_with(script, None)

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

    def test_time_and_date_delegate_to_orca_formatting_commands(self):
        script = types.SimpleNamespace(
            presentTime=mock.Mock(return_value=True),
            presentDate=mock.Mock(return_value=True),
        )
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.present_time(), True)
            self.assertIs(OrcaRuntimeAdapter.present_date(), True)
        script.presentTime.assert_called_once_with(None)
        script.presentDate.assert_called_once_with(None)

    def test_time_and_date_distinguish_missing_and_rejected_handlers(self):
        script = types.SimpleNamespace()
        with self._fake_orca(script):
            self.assertIsNone(OrcaRuntimeAdapter.present_time())
            self.assertIsNone(OrcaRuntimeAdapter.present_date())
        script.presentTime = mock.Mock(return_value=False)
        script.presentDate = mock.Mock(return_value=False)
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.present_time(), False)
            self.assertIs(OrcaRuntimeAdapter.present_date(), False)

    def test_current_line_uses_browse_caret_without_changing_navigation_state(self):
        browse_obj, focus_obj, flat_review = object(), object(), object()
        script = types.SimpleNamespace(
            sayLine=mock.Mock(return_value=None),
            utilities=types.SimpleNamespace(
                getCaretContext=mock.Mock(return_value=(browse_obj, 17)),
                inDocumentContent=mock.Mock(return_value=True)),
            flatReviewContext=flat_review,
            _lastCommandWasCaretNav=False,
            _lastCommandWasStructNav=True,
        )
        with self._fake_orca(script, focus=focus_obj):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)
        script.sayLine.assert_called_once_with(browse_obj)
        script.utilities.getCaretContext.assert_called_once_with()
        script.utilities.inDocumentContent.assert_called_once_with(focus_obj)
        self.assertIs(script.flatReviewContext, flat_review)
        self.assertIs(script._lastCommandWasCaretNav, False)
        self.assertIs(script._lastCommandWasStructNav, True)

    def test_current_line_reports_address_bar_without_consulting_cached_page_caret(self):
        address_bar, stale_page_caret = object(), object()
        script = types.SimpleNamespace(
            sayLine=mock.Mock(return_value=None),
            utilities=types.SimpleNamespace(
                # Orca web documentFrame() prefers the active document even
                # when locusOfFocus is a browser toolbar control.
                getCaretContext=mock.Mock(return_value=(stale_page_caret, 19)),
                inDocumentContent=mock.Mock(return_value=False)),
        )
        with self._fake_orca(script, focus=address_bar):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)
        script.sayLine.assert_called_once_with(address_bar)
        script.utilities.inDocumentContent.assert_called_once_with(address_bar)
        script.utilities.getCaretContext.assert_not_called()

    def test_current_line_supports_snake_case_locus_when_camelcase_is_none(self):
        focus_obj = object()
        script = types.SimpleNamespace(sayLine=mock.Mock())
        with self._fake_orca(script):
            sys.modules["orca.orca_state"].locus_of_focus = focus_obj
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)
        script.sayLine.assert_called_once_with(focus_obj)

    def test_current_line_falls_back_to_focus_when_caret_is_unavailable(self):
        focus_obj = object()
        for utilities in (None, types.SimpleNamespace(
            getCaretContext=lambda: (None, -1))):
            with self.subTest(utilities=utilities):
                script = types.SimpleNamespace(sayLine=mock.Mock(), utilities=utilities)
                with self._fake_orca(script, focus=focus_obj):
                    self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)
                script.sayLine.assert_called_once_with(focus_obj)

    def test_current_line_distinguishes_unsupported_from_missing_target(self):
        with self._fake_orca(None):
            self.assertIsNone(OrcaRuntimeAdapter.present_current_line())
        with self._fake_orca(types.SimpleNamespace()):
            self.assertIsNone(OrcaRuntimeAdapter.present_current_line())
        script = types.SimpleNamespace(sayLine=mock.Mock())
        with self._fake_orca(script):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), False)
        script.sayLine.assert_not_called()

    def test_current_line_preserves_rejected_handler_result(self):
        focus_obj = object()
        script = types.SimpleNamespace(sayLine=mock.Mock(return_value=False))
        with self._fake_orca(script, focus=focus_obj):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), False)
        script.sayLine.assert_called_once_with(focus_obj)

    def test_current_line_focus_mode_uses_focus_without_consulting_browse_caret(self):
        entry, stale_page_caret = object(), object()
        script = types.SimpleNamespace(
            sayLine=mock.Mock(),
            utilities=types.SimpleNamespace(
                inDocumentContent=lambda obj: True,
                getCaretContext=mock.Mock(return_value=(stale_page_caret, 19))),
            _inFocusMode=True,
            _lastCommandWasCaretNav=True,
            _lastCommandWasStructNav=False,
        )
        with self._fake_orca(script, focus=entry):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)
        script.sayLine.assert_called_once_with(entry)
        script.utilities.getCaretContext.assert_not_called()
        self.assertIs(script._lastCommandWasCaretNav, True)
        self.assertIs(script._lastCommandWasStructNav, False)

    def test_current_line_restores_navigation_flags_when_handler_raises(self):
        entry = object()
        script = types.SimpleNamespace(
            utilities=types.SimpleNamespace(inDocumentContent=lambda obj: False),
            _lastCommandWasCaretNav=True,
            _lastCommandWasStructNav=False,
        )

        def failing_handler(obj):
            self.assertIs(obj, entry)
            self.assertIs(script._lastCommandWasCaretNav, False)
            self.assertIs(script._lastCommandWasStructNav, False)
            raise RuntimeError("presentation failure")

        script.sayLine = failing_handler
        with self._fake_orca(script, focus=entry), self.assertRaises(RuntimeError):
            OrcaRuntimeAdapter.present_current_line()
        self.assertIs(script._lastCommandWasCaretNav, True)
        self.assertIs(script._lastCommandWasStructNav, False)

    def test_current_line_does_not_add_web_navigation_flags_to_other_scripts(self):
        entry = object()
        script = types.SimpleNamespace(
            utilities=types.SimpleNamespace(inDocumentContent=lambda obj: False),
            sayLine=mock.Mock(),
        )
        with self._fake_orca(script, focus=entry):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)
        self.assertFalse(hasattr(script, "_lastCommandWasCaretNav"))
        self.assertFalse(hasattr(script, "_lastCommandWasStructNav"))

    def test_present_lock_state_uses_authoritative_xkb_state(self):
        calls = []
        script = types.SimpleNamespace(
            presentMessage=lambda message: calls.append(message)
        )
        with self._fake_orca(script), mock.patch.object(
            OrcaRuntimeAdapter,
            "_xkb_named_lock_state",
            side_effect=lambda name: {"Num Lock": True, "Caps Lock": False}[name],
        ):
            self.assertTrue(OrcaRuntimeAdapter.present_lock_state(0x90))
            self.assertTrue(OrcaRuntimeAdapter.present_lock_state(0x14))
        self.assertEqual(calls, ["Num Lock on", "Caps Lock off"])

    def test_present_lock_state_rejects_unknown_or_unavailable_state(self):
        script = types.SimpleNamespace(
            presentMessage=lambda message: self.fail("must not present")
        )
        with self._fake_orca(script):
            self.assertFalse(OrcaRuntimeAdapter.present_lock_state(0x91))
        with self._fake_orca(script), mock.patch.object(
            OrcaRuntimeAdapter, "_xkb_named_lock_state", return_value=None
        ):
            self.assertFalse(OrcaRuntimeAdapter.present_lock_state(0x90))

    def test_lock_snapshot_does_not_access_orca_script(self):
        with mock.patch.object(
            OrcaRuntimeAdapter, "_xkb_named_lock_state", return_value=False
        ) as query, mock.patch.object(
            OrcaRuntimeAdapter, "active_script", side_effect=AssertionError("Orca API")
        ):
            self.assertIs(OrcaRuntimeAdapter.read_lock_state(0x90), False)
            self.assertIsNone(OrcaRuntimeAdapter.read_lock_state(0x91))
        query.assert_called_once_with("Num Lock")

    def test_lock_presentation_uses_snapshot_without_reading_later_state(self):
        calls = []
        script = types.SimpleNamespace(presentMessage=lambda message: calls.append(message))
        with self._fake_orca(script), mock.patch.object(
            OrcaRuntimeAdapter, "read_lock_state", side_effect=AssertionError("stale read")
        ):
            self.assertTrue(OrcaRuntimeAdapter.present_lock_state(0x90, True))
            self.assertTrue(OrcaRuntimeAdapter.present_lock_state(0x90, False))
            self.assertFalse(OrcaRuntimeAdapter.present_lock_state(0x90, "off"))
        self.assertEqual(calls, ["Num Lock on", "Num Lock off"])

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


class InstalledOrcaLineHandlerTests(unittest.TestCase):
    """Exercise installed web handlers without initializing Orca or a GUI."""

    @classmethod
    def setUpClass(cls):
        path = Path("/usr/lib/python3/dist-packages/orca/scripts/web/script.py")
        if not path.is_file():
            raise unittest.SkipTest("Installed Orca web script is unavailable")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        script = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "Script")
        methods = [node for node in script.body if isinstance(node, ast.FunctionDef)
                   and node.name in ("sayLine", "togglePresentationMode")]

        class Base:
            def sayLine(self, obj):
                self.physical_lines.append(obj)

        # Retain the exact installed method, including its super() dispatch.
        module = ast.Module(body=[ast.ClassDef(
            name="Script", bases=[ast.Name(id="Base", ctx=ast.Load())],
            keywords=[], body=methods, decorator_list=[])], type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {
            "Base": Base,
            "pyatspi": types.SimpleNamespace(ROLE_LIST_BOX="list_box", ROLE_MENU="menu"),
            "messages": types.SimpleNamespace(MODE_FOCUS="focus", MODE_BROWSE="browse"),
        }
        exec(compile(module, str(path), "exec"), namespace)
        cls.script_class = namespace["Script"]

    def _script(self, *, document=True, focus_mode=False, editable=False,
                caret_flag=False, struct_flag=False):
        script = self.script_class()
        focus, browse_caret, document_obj = object(), object(), object()
        script._lastCommandWasCaretNav = caret_flag
        script._lastCommandWasStructNav = struct_flag
        script._inFocusMode = focus_mode
        script._loadingDocumentContent = False
        script._focusModeIsSticky = False
        script._browseModeIsSticky = False
        script.presentMessage = mock.Mock()
        script.refreshKeyGrabs = mock.Mock()
        script.pointOfReference = {}
        script.physical_lines = []
        script.speakContents = mock.Mock()
        script.utilities = types.SimpleNamespace(
            inDocumentContent=lambda obj: document,
            isContentEditableWithEmbeddedObjects=lambda obj: editable,
            getTopLevelDocumentForObject=lambda obj: document_obj,
            getCaretContext=mock.Mock(return_value=(browse_caret, 19)),
            getPriorContext=lambda **kwargs: (None, -1),
            getLineContentsAtOffset=mock.Mock(return_value=[(browse_caret, 19)]),
            grabFocusWhenSettingCaret=lambda obj: False,
            grabFocus=mock.Mock(),
        )
        return script, focus, browse_caret

    def _toggle_mode(self, script, focus, result=True):
        orca = types.ModuleType("orca")
        orca.orca_state = types.SimpleNamespace(locusOfFocus=focus)
        with mock.patch.object(
            OrcaRuntimeAdapter, "active_script", return_value=script
        ), mock.patch.dict(sys.modules, {"orca": orca}):
            self.assertIs(OrcaRuntimeAdapter.toggle_presentation_mode(), result)

    def _present(self, script, focus):
        orca = types.ModuleType("orca")
        orca.orca_state = types.SimpleNamespace(locusOfFocus=focus)
        with mock.patch.object(
            OrcaRuntimeAdapter, "active_script", return_value=script
        ), mock.patch.dict(sys.modules, {"orca": orca}):
            self.assertIs(OrcaRuntimeAdapter.present_current_line(), True)

    def test_browse_line_uses_virtual_offset_after_non_navigation_command(self):
        script, focus, browse_caret = self._script()
        self._present(script, focus)
        self.assertEqual(script.physical_lines, [])
        script.utilities.getLineContentsAtOffset.assert_called_once_with(
            browse_caret, 19, useCache=True)
        script.speakContents.assert_called_once_with([(browse_caret, 19)], priorObj=None)
        self.assertIs(script._lastCommandWasCaretNav, False)
        self.assertIs(script._lastCommandWasStructNav, False)

    def test_toolbar_line_uses_physical_focus_despite_stale_navigation_flags(self):
        script, focus, _ = self._script(document=False, struct_flag=True)
        self._present(script, focus)
        self.assertEqual(script.physical_lines, [focus])
        script.utilities.getCaretContext.assert_not_called()
        script.speakContents.assert_not_called()
        self.assertIs(script._lastCommandWasCaretNav, False)
        self.assertIs(script._lastCommandWasStructNav, True)

    def test_focus_mode_entry_uses_native_physical_line_despite_stale_flags(self):
        script, focus, _ = self._script(focus_mode=True, caret_flag=True)
        self._present(script, focus)
        self.assertEqual(script.physical_lines, [focus])
        script.utilities.getCaretContext.assert_not_called()
        script.speakContents.assert_not_called()
        self.assertIs(script._lastCommandWasCaretNav, True)

    def test_rich_editable_retains_native_embedded_object_line_behavior(self):
        script, focus, browse_caret = self._script(focus_mode=True, editable=True)
        self._present(script, focus)
        self.assertEqual(script.physical_lines, [])
        script.utilities.getLineContentsAtOffset.assert_called_once_with(
            browse_caret, 19, useCache=True)
        script.speakContents.assert_called_once()

    def test_mode_toggle_outside_document_preserves_address_bar_focus_and_mode(self):
        script, focus, cached_page_caret = self._script(document=False)
        # The native handler reproduces the bug: its cached page caret is
        # focused even though the application locus is a toolbar control.
        script.togglePresentationMode(types.SimpleNamespace(type="keyboard"))
        script.utilities.grabFocus.assert_called_once_with(cached_page_caret)
        self.assertIs(script._inFocusMode, True)

        script._inFocusMode = False
        script.utilities.getCaretContext.reset_mock()
        script.utilities.grabFocus.reset_mock()
        script.presentMessage.reset_mock()
        script.refreshKeyGrabs.reset_mock()
        self._toggle_mode(script, focus, result=False)
        script.utilities.getCaretContext.assert_not_called()
        script.utilities.grabFocus.assert_not_called()
        script.presentMessage.assert_not_called()
        script.refreshKeyGrabs.assert_not_called()
        self.assertIs(script._inFocusMode, False)

    def test_mode_toggle_in_document_keeps_explicit_entry_focus_behavior(self):
        script, focus, cached_page_caret = self._script()
        self._toggle_mode(script, focus)
        script.utilities.grabFocus.assert_called_once_with(cached_page_caret)
        script.presentMessage.assert_called_once_with("focus")
        self.assertIs(script._inFocusMode, True)

    def test_mode_toggle_in_document_can_return_to_browse_mode(self):
        script, focus, _ = self._script(focus_mode=True)
        self._toggle_mode(script, focus)
        script.utilities.grabFocus.assert_not_called()
        script.presentMessage.assert_called_once_with("browse")
        self.assertIs(script._inFocusMode, False)


if __name__ == "__main__":
    unittest.main()
