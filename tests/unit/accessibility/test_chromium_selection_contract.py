"""Guard the source contract's pin and negative-control evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.diagnostics import chromium_selection_contract as contract


class ChromiumSelectionContractTests(unittest.TestCase):
    @staticmethod
    def case_records(original):
        records = []
        for name, expected in contract.CASE_EXTENTS.items():
            failed = original and name in contract.BASELINE_FAILURE_EXTENTS
            actual = contract.BASELINE_FAILURE_EXTENTS[name] if failed else expected
            records.append(
                {
                    "case": name,
                    "expected_start": expected[0],
                    "expected_end": expected[1],
                    "observed_start": actual[0],
                    "observed_end": actual[1],
                    "selected_text_equal": not failed,
                    "passed": not failed,
                }
            )
        return records

    def test_extraction_preserves_complete_method_and_rejects_ambiguity(self):
        source = "void AXPlatformNodeAuraLinux::Example() { if (true) { return; } }\n"
        self.assertEqual(contract.extract_method(source, "Example"), source.strip())
        for invalid in ("", source + source, source[:-3]):
            with self.subTest(source=invalid), self.assertRaises(ValueError):
                contract.extract_method(invalid, "Example")

    def test_source_mismatch_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cc"
            source.write_text("not the pinned provider", encoding="utf-8")
            output = root / "result"
            with self.assertRaisesRegex(ValueError, "Source SHA256 differs"):
                contract.run_contract(source, root / "patch.diff", output, "g++")
            self.assertFalse(output.exists())

    def test_both_baseline_failure_and_candidate_success_are_retained(self):
        result, output = self.run_mocked_contract(13, 12, 1, 25, 0, 0)
        self.assertTrue(result["expected_result"])
        self.assertEqual(result["kind"], "extracted_cpp_methods_with_test_dependencies")
        self.assertEqual(result["original"]["exit_code"], 1)
        self.assertIn('"failed": 12', output["original.jsonl"])
        self.assertIn('"failed": 0', output["candidate.jsonl"])
        self.assertEqual(json.loads(output["summary.json"]), result)

    def test_changed_negative_control_or_candidate_failure_is_not_success(self):
        for counts in ((25, 0, 0, 25, 0, 0), (13, 12, 1, 24, 1, 1)):
            with self.subTest(counts=counts):
                result, _ = self.run_mocked_contract(*counts)
                self.assertFalse(result["expected_result"])

    def test_same_totals_with_swapped_failure_identities_are_rejected(self):
        records = self.case_records(original=True)
        records[0]["passed"], records[1]["passed"] = (
            records[1]["passed"],
            records[0]["passed"],
        )
        self.assertEqual(13, sum(record["passed"] for record in records))
        self.assertFalse(contract.verify_case_evidence(records, original=True))

    def test_incomplete_duplicate_or_false_positive_candidate_is_rejected(self):
        good = self.case_records(original=False)
        self.assertTrue(contract.verify_case_evidence(good, original=False))
        duplicate = [*good[:-1], good[0]]
        false_positive = [dict(record) for record in good]
        false_positive[0]["observed_end"] -= 1
        bad_text = [dict(record) for record in good]
        bad_text[0]["selected_text_equal"] = False
        for records in (good[:-1], duplicate, false_positive, bad_text):
            with self.subTest(records=records):
                self.assertFalse(contract.verify_case_evidence(records, original=False))

    @classmethod
    def run_mocked_contract(
        cls, baseline_passed, baseline_failed, baseline_exit, passed, failed, exit_code
    ):
        source_text = (
            "void AXPlatformNodeAuraLinux::GetSelectionExtents(int*, int*) {}\n"
            "gchar* AXPlatformNodeAuraLinux::GetSelectionWithText(int*, int*) {}\n"
        )
        original = "\n".join(
            json.dumps(record)
            for record in [
                *cls.case_records(original=True),
                {"passed": baseline_passed, "failed": baseline_failed},
            ]
        )
        candidate = "\n".join(
            json.dumps(record)
            for record in [
                *cls.case_records(original=False),
                {"passed": passed, "failed": failed},
            ]
        )
        commands = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], baseline_exit, original + "\n", ""),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], exit_code, candidate + "\n", ""),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cc"
            source.write_text(source_text, encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with (
                patch.object(contract, "SOURCE_SHA256", digest),
                patch.object(contract.subprocess, "run", side_effect=commands),
            ):
                result = contract.run_contract(
                    source, root / "patch.diff", root / "result", "g++"
                )
            evidence = {
                name: (root / "result" / name).read_text(encoding="utf-8")
                for name in ("original.jsonl", "candidate.jsonl", "summary.json")
            }
            return result, evidence


if __name__ == "__main__":
    unittest.main()
