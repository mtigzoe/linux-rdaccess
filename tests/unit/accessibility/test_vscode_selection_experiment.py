"""Regression for extracting pinned bundled methods without cutting at calls."""

import unittest

from tools.diagnostics import vscode_selection_experiment as experiment


class BundledMethodTests(unittest.TestCase):
    def test_unicode_metrics_distinguish_codepoints_from_utf16_units(self):
        value = experiment.CASES["unicode"]
        metrics = experiment.unicode_length_metrics(value, value)
        self.assertEqual(metrics["expected_codepoints"], 13)
        self.assertEqual(metrics["expected_utf16_units"], 14)
        self.assertEqual(metrics["observed_utf16_units"], 14)
        self.assertTrue(metrics["observed_equals_fixture"])

    def test_unicode_metrics_detect_missing_astral_character(self):
        value = experiment.CASES["unicode"]
        metrics = experiment.unicode_length_metrics(value, value.replace("🙂", ""))
        self.assertEqual(metrics["observed_codepoints"], 12)
        self.assertEqual(metrics["observed_utf16_units"], 12)
        self.assertFalse(metrics["observed_equals_fixture"])

    def test_neighbor_method_call_is_not_a_declaration_boundary(self):
        source = (
            "prefix;var K0e=class extends Base{"
            "updateScreenReaderContent(e){this.work(e)}updateScrollTop(e){}"
            "onFocusChange(e){this._setSelectionChangeListener()}onConfigurationChanged(e){}"
            'onWillCut(){this._setIgnoreSelectionChangeTime("cut")}'
            'onWillPaste(){this._setIgnoreSelectionChangeTime("paste")}'
            "_setIgnoreSelectionChangeTime(e){this.time=1}"
            "_setSelectionChangeListener(){return this.listen()}"
            "_getScreenReaderContentState(e){}};suffix"
        )
        methods = {
            name: name + "(){/* reviewed replacement */}"
            for name in experiment.BOUNDARIES
        }
        result = experiment.patch_methods(source, methods)
        self.assertNotIn('"paste"', result)
        self.assertNotIn('"cut"', result)
        self.assertIn("_setIgnoreSelectionChangeTime(e){this.time=1}", result)
        self.assertTrue(result.startswith("prefix;var K0e="))
        self.assertTrue(result.endswith("};suffix"))
        self.assertIn("onFocusChange(){/* reviewed replacement */}", result)


if __name__ == "__main__":
    unittest.main()
