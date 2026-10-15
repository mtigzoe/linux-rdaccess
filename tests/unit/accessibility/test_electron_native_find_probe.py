"""Native find evidence must observe the actual fixture and fallback state."""

import unittest

from tools.diagnostics import electron_native_find_probe as probe


class NativeFindEvidenceTests(unittest.TestCase):
    def test_strict_find_inventory_rejects_missing_duplicate_and_wrong_cases(self):
        value = "a\U0001f642z"
        names = ["initial_no_selection"] + [
            prefix + name
            for name, *_ in probe.find_cases(value)
            for prefix in ("find_", "clear_")
        ]
        samples = [{"case": name, "passed": True} for name in names]
        self.assertTrue(probe.find_result_passes({"samples": samples}, value))
        for invalid in (
            samples[:-1],
            samples + [samples[0]],
            samples[:-1] + [{"case": "unknown", "passed": True}],
            [{**sample, "passed": False} for sample in samples],
        ):
            self.assertFalse(probe.find_result_passes({"samples": invalid}, value))

    def test_multiline_find_offsets_count_codepoints_and_newlines(self):
        value = "a\U0001f642 caf\u00e9\nb\U0001d11e omega\nc\U00010437 fin"
        cases = probe.find_cases(value)
        for name, query, start, end in cases:
            with self.subTest(name=name):
                self.assertEqual(value[start:end], query)
        self.assertEqual(cases[1][2:], (8, 16))
        self.assertEqual(cases[2][2:], (9, 10))
        self.assertNotEqual(len(value[:9].encode("utf-16-le")) // 2, 9)

    def setUp(self):
        self.fixture = "a\U0001f642 caf\u00e9 omega"
        self.dom = {"text": self.fixture, "selected": ""}
        self.inactive = {"selection_count": 0, "selection": None}
        self.active = {"selection_count": 1, "selection": [0, 13]}

    def test_missing_nodes_cannot_pass_initial_clear_or_positive_selection(self):
        for expected in (None, [0, 13]):
            with self.subTest(expected=expected):
                self.assertFalse(
                    probe.selection_observations_match(
                        [], expected, self.dom, self.fixture
                    )
                )

    def test_observed_no_selection_passes_initial_and_clear(self):
        self.assertTrue(
            probe.selection_observations_match(
                [self.inactive], None, self.dom, self.fixture
            )
        )
        self.assertFalse(
            probe.selection_observations_match(
                [self.active], None, self.dom, self.fixture
            )
        )

    def test_selected_paragraph_and_unselected_static_child_are_valid(self):
        self.assertTrue(
            probe.selection_observations_match(
                [self.active, self.inactive], [0, 13], self.dom, self.fixture
            )
        )
        self.assertFalse(
            probe.selection_observations_match(
                [self.inactive], [0, 13], self.dom, self.fixture
            )
        )
        self.assertFalse(
            probe.selection_observations_match(
                [self.active], [0, 12], self.dom, self.fixture
            )
        )

    def test_wrong_document_or_nonempty_dom_selection_cannot_prove_fallback(self):
        for dom in (
            {"text": "different document", "selected": ""},
            {"text": self.fixture, "selected": self.fixture},
        ):
            for expected, observations in (
                (None, [self.inactive]),
                ([0, 13], [self.active, self.inactive]),
            ):
                with self.subTest(dom=dom, expected=expected):
                    self.assertFalse(
                        probe.selection_observations_match(
                            observations, expected, dom, self.fixture
                        )
                    )


if __name__ == "__main__":
    unittest.main()
