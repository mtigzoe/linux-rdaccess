"""Coordinate and evidence contracts for the private native keyboard matrix."""

import unittest

from tools.diagnostics import vscode_native_selection_matrix as matrix
from tools.diagnostics import vscode_selection_experiment as experiment


class NativeKeyboardMatrixTests(unittest.TestCase):

    def test_selection_observation_intervals_require_monotonic_order(self):
        self.assertEqual(matrix.selection_read_intervals(100, 125, 200), (25, 100))
        self.assertEqual(matrix.selection_read_intervals(100, 100, 100), (0, 0))
        with self.assertRaises(ValueError):
            matrix.selection_read_intervals(100, 99, 110)
        with self.assertRaises(ValueError):
            matrix.selection_read_intervals(100, 110, 109)



    def test_secondary_selection_read_preserves_error_as_diagnostic(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        class SelectionError(Exception):
            pass

        glib = SimpleNamespace(Error=SelectionError)
        atspi = SimpleNamespace(Text=SimpleNamespace(get_selection=Mock()))
        text = SimpleNamespace(get_n_selections=Mock(return_value=1))
        atspi.Text.get_selection.side_effect = SelectionError("selection not ready")
        count, selection, error = matrix.observe_post_clipboard_selection(
            text, atspi, glib
        )
        self.assertIsNone(count)
        self.assertIsNone(selection)
        self.assertEqual(error, "SelectionError")

        text.get_n_selections.side_effect = SelectionError("count not ready")
        self.assertEqual(
            matrix.observe_post_clipboard_selection(text, atspi, glib),
            (None, None, "SelectionError"),
        )

    def test_secondary_selection_read_records_valid_and_empty_selection(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        glib = SimpleNamespace(Error=RuntimeError)
        atspi = SimpleNamespace(
            Text=SimpleNamespace(
                get_selection=Mock(
                    return_value=SimpleNamespace(start_offset=1, end_offset=3)
                )
            )
        )
        text = SimpleNamespace(get_n_selections=Mock(return_value=1))
        self.assertEqual(
            matrix.observe_post_clipboard_selection(text, atspi, glib),
            (1, [1, 3], None),
        )
        text.get_n_selections.return_value = 0
        self.assertEqual(
            matrix.observe_post_clipboard_selection(text, atspi, glib),
            (0, None, None),
        )

    def test_routing_positions_are_codepoints_before_each_supplementary_character(self):
        self.assertEqual(
            matrix.routing_positions(matrix.EXTENDED_CASES["distinct_astral"]),
            [1, 2, 3],
        )
        self.assertEqual(
            matrix.routing_positions(matrix.EXTENDED_CASES["multiline_astral"]),
            [1, 9, 18],
        )

    def test_distinct_supplementary_fixture_has_three_extra_utf16_units(self):
        value = matrix.EXTENDED_CASES["distinct_astral"]
        supplementary = [character for character in value if ord(character) > 0xFFFF]
        self.assertEqual(len(set(supplementary)), 3)
        self.assertEqual(len(value.encode("utf-16-le")) // 2, len(value) + 3)
        self.assertEqual(value, experiment.CASES["distinct_astral"])

    def test_multiline_fixture_keeps_codepoint_offsets_across_lines(self):
        value = matrix.EXTENDED_CASES["multiline_astral"]
        self.assertEqual(value.count("\n"), 2)
        self.assertEqual(len(value.encode("utf-16-le")) // 2, len(value) + 3)
        self.assertEqual(value, experiment.CASES["multiline_astral"])
        cases = {
            name: (keys, start, end)
            for name, keys, start, end in matrix.keyboard_cases(value, extended=True)
        }
        self.assertEqual(
            cases["full_forward"], (["ctrl+Home", "ctrl+shift+End"], 0, len(value))
        )
        self.assertEqual(
            cases["full_reverse"], (["ctrl+End", "ctrl+shift+Home"], len(value), 0)
        )

    def test_missing_provider_semantic_dom_or_clipboard_evidence_cannot_pass(self):
        self.assertFalse(matrix.sample_passes({}))
        sample = dict.fromkeys(
            (
                "dom_selected_text_equals_expected",
                "provider_selection_passed",
                "provider_caret_passed",
                "semantic_selection_passed",
                "semantic_text_equals_fixture",
                "copied_equals_expected",
            ),
            True,
        )
        sample["expected_provider_selection"] = [0, 1]
        self.assertTrue(matrix.sample_passes(sample))
        for field in set(sample) - {"expected_provider_selection"}:
            with self.subTest(field=field):
                self.assertFalse(matrix.sample_passes({**sample, field: False}))
        self.assertFalse(
            matrix.sample_passes({**sample, "copied_equals_expected": None})
        )
        self.assertTrue(
            matrix.sample_passes(
                {
                    **sample,
                    "copied_equals_expected": None,
                    "expected_provider_selection": None,
                }
            )
        )
        self.assertFalse(
            matrix.sample_passes(
                {
                    key: value
                    for key, value in sample.items()
                    if key != "copied_equals_expected"
                }
            )
        )

    def test_exact_matrix_inventory_rejects_missing_duplicate_or_wrong_cases(self):
        fixtures = {"fixture": "a\U0001f642z"}
        samples = []
        for case, _keys, start, end in matrix.keyboard_cases(fixtures["fixture"]):
            sample = dict.fromkeys(
                (
                    "dom_selected_text_equals_expected",
                    "provider_selection_passed",
                    "provider_caret_passed",
                    "semantic_selection_passed",
                    "semantic_text_equals_fixture",
                ),
                True,
            )
            sample.update(
                fixture="fixture",
                case=case,
                expected_provider_selection=[min(start, end), max(start, end)]
                if start != end
                else None,
                copied_equals_expected=True if start != end else None,
            )
            samples.append(sample)
        result = {"samples": samples, "routes": []}
        self.assertTrue(matrix.matrix_result_passes(result, fixtures))
        for invalid in (
            samples[:-1],
            samples + [samples[0]],
            samples[:-1] + [{**samples[-1], "case": "unknown"}],
        ):
            self.assertFalse(
                matrix.matrix_result_passes({"samples": invalid}, fixtures)
            )
        self.assertFalse(
            matrix.matrix_result_passes(result, fixtures, route_continuation=True)
        )
        route = {
            "fixture": "fixture",
            "requested_codepoint": 1,
            "passed": True,
            "observations": [{"key": key} for key in (None, "Right", "Left")],
        }
        self.assertTrue(
            matrix.matrix_result_passes(
                {**result, "routes": [route]}, fixtures, route_continuation=True
            )
        )
        self.assertFalse(
            matrix.matrix_result_passes(
                {
                    **result,
                    "routes": [{**route, "observations": route["observations"][:2]}],
                },
                fixtures,
                route_continuation=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
