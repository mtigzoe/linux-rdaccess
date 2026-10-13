"""Evidence from one layer must never certify another layer or a whole issue."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import linux_rdaccess_acceptance as legacy
from linux_rdaccess_core import acceptance_report as report


class LayeredAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = report.template()
        self.evidence["context"].update(
            application="Firefox",
            gesture="physical route to 'b'",
            expected="Linux caret moves to the selected b",
            braille_model="Eurobraille b.note",
        )

    def record(self, layer_id, *, source, status="pass"):
        layer = next(item for item in self.evidence["layers"] if item["id"] == layer_id)
        layer.update(status=status, source=source, observed="Observed in this interaction")

    def test_template_has_no_observed_success(self):
        result = report.summary(report.template())
        self.assertEqual(result["counts"]["unverified"], 5)
        self.assertFalse(result["physical_braille_user_confirmed"])
        self.assertFalse(result["nvda_speech_user_confirmed"])

    def test_linux_caret_does_not_certify_keyboard_speech_or_braille(self):
        self.record("linux_focus", source="linux-atspi")
        result = report.summary(self.evidence)
        self.assertEqual(result["counts"]["pass"], 1)
        self.assertEqual(result["layers"]["keyboard_delivery"]["status"], "unverified")
        self.assertEqual(result["layers"]["semantic_braille"]["status"], "unverified")
        self.assertFalse(result["physical_braille_user_confirmed"])
        self.assertFalse(result["nvda_speech_user_confirmed"])

    def test_only_human_confirmation_can_verify_physical_output(self):
        for source in ("linux-atspi", "windows-nvda", "remote-protocol", "isolated-test"):
            with self.subTest(source=source):
                self.record("physical_braille", source=source)
                with self.assertRaisesRegex(ValueError, "compatible source"):
                    report.summary(self.evidence)
        self.record("physical_braille", source="user-confirmation")
        self.assertTrue(report.summary(self.evidence)["physical_braille_user_confirmed"])

    def test_windows_speech_event_is_not_audible_confirmation(self):
        self.record("nvda_speech", source="windows-nvda")
        self.assertFalse(report.summary(self.evidence)["nvda_speech_user_confirmed"])
        self.record("nvda_speech", source="user-confirmation")
        self.assertTrue(report.summary(self.evidence)["nvda_speech_user_confirmed"])

    def test_physical_result_identifies_the_display(self):
        self.record("physical_braille", source="user-confirmation")
        self.evidence["context"]["braille_model"] = ""
        with self.assertRaisesRegex(ValueError, "display model"):
            report.validate(self.evidence)

    def test_simulated_layers_never_create_a_general_acceptance_claim(self):
        for layer_id in list(report.LAYERS)[:-1]:
            self.record(layer_id, source="isolated-test")
        result = report.summary(self.evidence)
        self.assertEqual(result["counts"]["pass"], 4)
        self.assertFalse(result["physical_braille_user_confirmed"])
        self.assertNotIn("live_accepted", result)
        self.assertNotIn("physical_braille_verified", result)
        self.assertIn("interaction only", result["scope"])

    def test_braille_gesture_can_leave_keyboard_not_tested(self):
        self.evidence["layers"][0]["status"] = "not-tested"
        self.evidence["layers"][0]["observed"] = "Physical routing gesture; no keyboard key was sent"
        self.record("physical_braille", source="user-confirmation")
        result = report.summary(self.evidence)
        self.assertEqual(result["counts"]["not-tested"], 1)
        self.assertTrue(result["physical_braille_user_confirmed"])

    def test_blank_evidence_or_missing_interaction_is_rejected(self):
        self.record("linux_focus", source="linux-atspi")
        self.evidence["layers"][1]["observed"] = " "
        with self.assertRaisesRegex(ValueError, "observation"):
            report.validate(self.evidence)
        self.evidence["layers"][1]["observed"] = "Caret event observed"
        self.evidence["context"]["gesture"] = ""
        with self.assertRaisesRegex(ValueError, "gesture"):
            report.validate(self.evidence)

    def test_reordered_layers_and_changed_metadata_rejected(self):
        self.evidence["layers"].reverse()
        with self.assertRaisesRegex(ValueError, "reordered"):
            report.validate(self.evidence)
        self.evidence["layers"].reverse()
        self.evidence["layers"][1]["expected"] = "An AT-SPI event proves physical output"
        with self.assertRaisesRegex(ValueError, "layer"):
            report.validate(self.evidence)

    def test_unbounded_notes_and_unknown_session_fields_rejected(self):
        self.evidence["context"]["application"] = "x" * 501
        with self.assertRaisesRegex(ValueError, "500"):
            report.validate(self.evidence)
        self.evidence["context"]["application"] = "Mousepad"
        self.evidence["session"]["relay_key"] = "must not be part of this report"
        with self.assertRaisesRegex(ValueError, "session"):
            report.validate(self.evidence)

    def test_report_remains_offline_and_does_not_change_session_states(self):
        self.evidence["session"].update(authorization_before_input="expired", transport="disconnected")
        result = report.summary(self.evidence)
        self.assertEqual(result["session"], self.evidence["session"])
        self.assertIn("grants no input permission", result["limitations"][-1])

    def test_session_cli_round_trip_and_legacy_schema_remain_separate(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(legacy.main(["session-template"]), 0)
        self.assertEqual(json.loads(output.getvalue()), report.template())
        self.record("linux_focus", source="linux-atspi")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(self.evidence), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(legacy.main(["session-summary", "--file", str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue())["counts"]["pass"], 1)
        self.assertEqual(legacy.template()["schema_version"], 1)
        with self.assertRaisesRegex(ValueError, "schema"):
            report.validate(legacy.template())
        with self.assertRaisesRegex(ValueError, "case list"):
            legacy.validate(report.template())
