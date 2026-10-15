"""Native find evidence must observe the actual fixture and fallback state."""

import unittest

from tools.diagnostics import electron_native_find_probe as probe


class NativeFindEvidenceTests(unittest.TestCase):
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
