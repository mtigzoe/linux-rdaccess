"""Regression for extracting pinned bundled methods without cutting at calls."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.diagnostics import vscode_selection_experiment as experiment


class BundledMethodTests(unittest.TestCase):
    def test_unicode_metrics_distinguish_codepoints_from_utf16_units(self):
        value = experiment.CASES["unicode"]
        metrics = experiment.unicode_length_metrics(value, value)
        self.assertEqual(metrics["expected_codepoints"], 13)
        self.assertEqual(metrics["expected_utf16_units"], 14)
        self.assertEqual(metrics["observed_utf16_units"], 14)
        self.assertTrue(metrics["observed_equals_fixture"])

    def test_bmp_unicode_fixture_has_no_utf16_length_difference(self):
        value = experiment.CASES["unicode_bmp"]
        metrics = experiment.unicode_length_metrics(value, value)
        self.assertIn("é", value)
        self.assertEqual(metrics["expected_codepoints"], metrics["expected_utf16_units"])
        self.assertTrue(metrics["observed_equals_fixture"])

    def test_unicode_metrics_detect_missing_astral_character(self):
        value = experiment.CASES["unicode"]
        metrics = experiment.unicode_length_metrics(value, value.replace("🙂", ""))
        self.assertEqual(metrics["observed_codepoints"], 12)
        self.assertEqual(metrics["observed_utf16_units"], 12)
        self.assertFalse(metrics["observed_equals_fixture"])

    def test_failure_stages_distinguish_edited_text_and_upstream_defects(self):
        expected = {
            "VS Code editor text": "fixture_entry",
            "VS Code editor caret": "fixture_entry",
            "VS Code editor left-arrow caret": "fixture_entry",
            "VS Code editor: semantic routing accepts provider caret setter": "caret_setter",
            "VS Code editor routed caret": "caret_readback",
            "VS Code editor: routed caret is confirmed by the provider": "caret_readback",
            "routed caret keyboard Right=2": "keyboard_continuation",
            "Routed caret: keyboard Left reaches 1": "keyboard_continuation",
            "VS Code editor semantic selection": "semantic_selection",
            "VS Code editor: semantic text snapshot tracks keyboard selection": "semantic_selection",
            "Code private cut/paste restore": "clipboard_integrity",
            "Code focus-return caret": "focus_return",
            "A private window title not in test labels": "other_stage",
        }
        for label, stage in expected.items():
            with self.subTest(label=label):
                self.assertEqual(experiment.failure_stage(label), stage)

    def test_failing_wait_records_only_stage_and_restores_smoke_hooks(self):
        class FakeSession:
            def wait(self, predicate, label, *, seconds=18):
                raise AssertionError("native Unicode selection failed")

            def check(self, label, condition=True):
                return None

            def text_edit(self, target, value, label, **kwargs):
                return None

            def close(self):
                return None

        original_methods = (
            FakeSession.wait, FakeSession.check, FakeSession.text_edit,
            FakeSession.close,
        )

        def fake_run_inner(_skips):
            return FakeSession().wait(
                lambda: False, "VS Code editor semantic selection"
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata.json").write_text(json.dumps({
                "original_root": str(root / "original"),
                "original_sha256": "pinned-sha",
                "private_binary": str(root / "copy" / "code"),
            }))
            original_code_binary = experiment.smoke.desktop_code_binary
            original_setter = experiment.smoke.set_caret_offset
            with (
                mock.patch.dict(os.environ, {"LRD_GUI_PRIVATE": directory}),
                mock.patch.object(experiment, "digest", return_value="pinned-sha"),
                mock.patch.object(experiment.smoke, "Session", FakeSession),
                mock.patch.object(experiment.smoke, "run_inner",
                                  side_effect=fake_run_inner),
            ):
                with self.assertRaisesRegex(AssertionError, "native Unicode"):
                    experiment.run_inner(
                        SimpleNamespace(output=root, case="unicode")
                    )
                result = json.loads((root / "selection-result.json").read_text())
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["failure_stage"], "semantic_selection")
                self.assertEqual(result["failure_class"], "AssertionError")
                self.assertNotIn("native Unicode selection failed", json.dumps(result))
                self.assertEqual(
                    (FakeSession.wait, FakeSession.check, FakeSession.text_edit,
                     FakeSession.close),
                    original_methods,
                )
                self.assertIs(experiment.smoke.set_caret_offset, original_setter)
                self.assertIs(experiment.smoke.desktop_code_binary, original_code_binary)

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
