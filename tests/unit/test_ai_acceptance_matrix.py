"""Offline acceptance tracker invariants."""
import unittest

import linux_rdaccess_acceptance as acceptance


class AcceptanceTests(unittest.TestCase):
    def test_new_report_is_entirely_unverified(self):
        report = acceptance.template()
        counts = acceptance.summary(report)
        self.assertEqual(counts["unverified"], len(acceptance.CASES))
        self.assertFalse(counts["live_accepted"])
        self.assertFalse(counts["physical_braille_verified"])

    def test_pass_requires_observation(self):
        report = acceptance.template()
        report["cases"][0]["status"] = "pass"
        with self.assertRaisesRegex(ValueError, "observation"):
            acceptance.summary(report)

    def test_reordered_cases_are_rejected(self):
        report = acceptance.template()
        report["cases"][0], report["cases"][1] = report["cases"][1], report["cases"][0]
        with self.assertRaisesRegex(ValueError, "reordered"):
            acceptance.summary(report)

    def test_all_pass_requires_individual_evidence(self):
        report = acceptance.template()
        for case in report["cases"]:
            case["status"] = "pass"
            case["observed"] = "Observed directly in authorized live NVDA session"
        result = acceptance.summary(report)
        self.assertTrue(result["live_accepted"])
        self.assertTrue(result["physical_braille_verified"])

    def test_non_braille_pass_does_not_certify_braille(self):
        report = acceptance.template()
        for case in report["cases"]:
            if case["issue"] not in (59, 72):
                case["status"] = "pass"
                case["observed"] = "Observed"
        self.assertFalse(acceptance.summary(report)["physical_braille_verified"])

    def test_unexpected_status_rejected(self):
        report = acceptance.template()
        report["cases"][0]["status"] = "automated_pass"
        with self.assertRaisesRegex(ValueError, "status"):
            acceptance.summary(report)


if __name__ == "__main__":
    unittest.main()
