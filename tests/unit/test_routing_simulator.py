"""A simulated route must be explicit, guarded, bounded and clearly labelled."""

import contextlib
import io
import json
import types
import unittest
from unittest import mock

from diagnostics.atspi import simulate_routing as simulator


class Editor:
    def __init__(self):
        self.caret, self.count, self.selections = 2, 19, 0
        self.app = types.SimpleNamespace(get_name=lambda: "Mousepad", get_process_id=lambda: 123)
        self.set_caret_offset = mock.Mock(side_effect=self.write)

    def get_application(self):
        return self.app

    def get_text_iface(self):
        return self

    def get_caret_offset(self):
        return self.caret

    def get_character_count(self):
        return self.count

    def get_n_selections(self):
        return self.selections

    def write(self, offset):
        self.caret = offset
        return True

    def get_text(self, *_args):
        raise AssertionError("Editor text must never be read")


class RoutingSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.editor = Editor()
        self.snapshot = {"object": self.editor, "name": "private document title",
                         "role": "text", "states": ["focused", "editable"]}
        self.focus = types.SimpleNamespace(read=mock.Mock(return_value=self.snapshot))
        self.guards = dict(apply=True, expected_pid=123, expected_caret=2, expected_count=19)

    def run_apply(self, **changes):
        guards = dict(self.guards, **changes)
        return simulator.simulate(self.focus, "mousepad", 7, **guards)

    def observation(self, *, before_ready=None, after_write=None, dropped=0):
        """Stub only the event loop; use the real production caret setter."""
        def observe(focus, app, duration, emit):
            if before_ready:
                before_ready()
            emit({"observer": "ready", "input_sent": False})
            if after_write:
                after_write()
            return {"before_caret": 2, "after_caret": self.editor.caret,
                    "same_initial_focus": True, "focus_changed_during_observation": False,
                    "events": [], "dropped_events": dropped}
        return mock.patch.object(simulator, "observe", side_effect=observe)

    def test_default_preview_never_starts_observer_or_writes(self):
        with mock.patch.object(simulator, "observe") as observe:
            result = simulator.simulate(self.focus, "mousepad", 7)
        observe.assert_not_called()
        self.editor.set_caret_offset.assert_not_called()
        self.assertEqual(result["operation"], "preview")
        self.assertEqual(result["target"]["caret"], 2)
        self.assertFalse(result["caret_write_attempted"])
        self.assertEqual(result["physical_braille"], "unverified")
        self.assertNotIn("private", json.dumps(result))

    def test_one_write_after_ready_and_separate_readback(self):
        emitted = []
        with self.observation():
            result = self.run_apply(emit=emitted.append)
        self.editor.set_caret_offset.assert_called_once_with(7)
        self.assertEqual(result["setter_reasons"], ["setter_returned"])
        self.assertTrue(result["caret_write_attempted"])
        self.assertTrue(result["caret_readback_matches"])
        self.assertFalse(result["keyboard_input_sent"])
        self.assertEqual(emitted[0]["stimulus"], "direct-atspi-simulation")
        self.assertEqual(result["nvda_output"], "unverified")

    def test_missing_or_stale_preview_values_prevent_write(self):
        for key, value in (("expected_pid", None), ("expected_pid", 456),
                           ("expected_caret", None), ("expected_caret", 3),
                           ("expected_count", None), ("expected_count", 18)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.run_apply(**{key: value})
        self.editor.set_caret_offset.assert_not_called()

    def test_password_noneditable_and_wrong_application_never_write(self):
        for role, states, app in (("password-text", [], "Mousepad"),
                                  ("text", ["focused"], "Mousepad"),
                                  ("text", ["editable"], "Mousepad"),
                                  ("text", ["focused", "editable"], "xfce4-terminal")):
            self.snapshot.update(role=role, states=states)
            self.editor.app.get_name = lambda: app
            with self.subTest(role=role, states=states, app=app), self.assertRaises(ValueError):
                self.run_apply()
        self.editor.set_caret_offset.assert_not_called()

    def test_selection_is_preserved_by_refusing_apply(self):
        self.editor.selections = 1
        with self.assertRaises(ValueError):
            self.run_apply()
        self.editor.set_caret_offset.assert_not_called()

    def test_changed_focus_between_preview_and_write_is_refused(self):
        other = dict(self.snapshot, object=Editor())
        with self.observation(before_ready=lambda: self.focus.read.configure_mock(return_value=other)):
            result = self.run_apply()
        self.assertFalse(result["caret_write_attempted"])
        self.assertFalse(result["caret_readback_matches"])
        self.assertEqual(result["setter_reasons"], ["before_route_error"])
        self.editor.set_caret_offset.assert_not_called()

    def test_changed_caret_or_count_or_selection_before_write_is_refused(self):
        for attribute, value in (("caret", 3), ("count", 20), ("selections", 1)):
            with self.subTest(attribute=attribute):
                self.editor.caret, self.editor.count, self.editor.selections = 2, 19, 0
                with self.observation(before_ready=lambda: setattr(self.editor, attribute, value)):
                    result = self.run_apply()
                self.assertFalse(result["caret_write_attempted"])
        self.editor.set_caret_offset.assert_not_called()

    def test_provider_return_does_not_substitute_for_readback(self):
        self.editor.set_caret_offset.side_effect = None
        self.editor.set_caret_offset.return_value = True
        with self.observation():
            result = self.run_apply()
        self.assertTrue(result["setter_returned"])
        self.assertFalse(result["caret_readback_matches"])
        self.editor.set_caret_offset.assert_called_once_with(7)

    def test_provider_exception_is_not_exported_or_retried(self):
        self.editor.set_caret_offset.side_effect = RuntimeError("private provider text")
        with self.observation():
            result = self.run_apply()
        self.assertFalse(result["setter_returned"])
        self.assertEqual(result["setter_reasons"], ["provider_error"])
        self.assertNotIn("private", json.dumps(result))
        self.editor.set_caret_offset.assert_called_once_with(7)

    def test_overflow_prevents_positive_readback_conclusion(self):
        with self.observation(dropped=1):
            result = self.run_apply()
        self.assertFalse(result["caret_readback_matches"])

    def test_focus_change_after_write_prevents_positive_readback_conclusion(self):
        with mock.patch.object(simulator, "observe") as observe:
            def changed(_focus, _app, _duration, emit):
                emit({"observer": "ready", "input_sent": False})
                return {"after_caret": 7, "same_initial_focus": True,
                        "focus_changed_during_observation": True, "dropped_events": 0}
            observe.side_effect = changed
            result = self.run_apply()
        self.assertFalse(result["caret_readback_matches"])
        self.editor.set_caret_offset.assert_called_once_with(7)

    def test_observer_failure_before_ready_never_writes(self):
        with mock.patch.object(simulator, "observe", side_effect=ValueError("registration refused")):
            with self.assertRaises(ValueError):
                self.run_apply()
        self.editor.set_caret_offset.assert_not_called()

    def test_invalid_offsets_or_unbounded_duration_never_write(self):
        for offset in (-1, True, 20, 8193):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                simulator.simulate(self.focus, "mousepad", offset, **self.guards)
        for duration in (0, 11, float("inf"), float("nan")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.run_apply(duration=duration)
        self.editor.set_caret_offset.assert_not_called()

    def test_cli_does_not_echo_invalid_arguments(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = simulator.main(["--offset", "private argument"])
        self.assertEqual(code, 2)
        self.assertNotIn("private argument", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["caret_write_outcome"], "unknown")
