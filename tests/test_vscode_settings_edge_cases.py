import json
import tempfile
import unittest
from pathlib import Path

import linux_rdaccess as cli


def effective(path: Path) -> dict:
    return json.loads(cli._strip_jsonc(path.read_text(encoding="utf-8")))


class VsCodeSettingsEdgeCaseTests(unittest.TestCase):
    def run_setup(self, text: str, *, raw: bytes | None = None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "settings.json"
        path.write_bytes(raw if raw is not None else text.encode("utf-8"))
        return path

    def test_commented_out_key_does_not_hide_the_setting(self):
        """Regression: the comment was edited instead, so the setting never took effect."""
        path = self.run_setup('{\n    // "editor.accessibilitySupport": "off",\n    "a": 1\n}\n')
        cli.configure_vscode_accessibility(path)
        self.assertEqual(effective(path)["editor.accessibilitySupport"], "on")
        self.assertIn('// "editor.accessibilitySupport": "off",', path.read_text())  # comment untouched

    def test_block_commented_key_is_ignored_too(self):
        path = self.run_setup('{\n    /* "editor.accessibilitySupport": "off" */\n    "a": 1\n}\n')
        cli.configure_vscode_accessibility(path)
        self.assertEqual(effective(path)["editor.accessibilitySupport"], "on")

    def test_brace_in_a_header_comment_is_not_the_object_start(self):
        """Regression: the new keys were inserted inside the comment, then a raw JSONDecodeError."""
        path = self.run_setup('// my settings {local}\n{\n    "a": 1\n}\n')
        cli.configure_vscode_accessibility(path)
        data = effective(path)
        self.assertEqual((data["a"], data["editor.accessibilitySupport"]), (1, "on"))

    def test_existing_non_string_value_is_replaced_not_shadowed(self):
        path = self.run_setup('{\n    "editor.accessibilitySupport": null,\n    "a": 1\n}\n')
        cli.configure_vscode_accessibility(path)
        self.assertEqual(effective(path)["editor.accessibilitySupport"], "on")

    def test_existing_value_replaced_in_place_and_other_settings_kept(self):
        path = self.run_setup('{\n    "editor.accessibilitySupport": "auto", // keep me\n    "a": 1\n}\n')
        cli.configure_vscode_accessibility(path)
        text = path.read_text()
        self.assertIn("// keep me", text)
        self.assertEqual(text.count("editor.accessibilitySupport"), 1)
        self.assertEqual(effective(path)["a"], 1)

    def test_utf8_bom_is_accepted_and_backup_keeps_the_original_bytes(self):
        raw = b"\xef\xbb\xbf{\n    \"a\": 1\n}\n"
        path = self.run_setup("", raw=raw)
        cli.configure_vscode_accessibility(path)
        self.assertEqual(effective(path)["editor.accessibilitySupport"], "on")
        self.assertEqual(path.with_name(path.name + ".linux-rdaccess-backup").read_bytes(), raw)

    def test_unsupported_value_shape_is_reported_without_touching_the_file(self):
        original = '{\n    "editor.accessibilitySupport": {"x": 1}\n}\n'
        path = self.run_setup(original)
        with self.assertRaisesRegex(ValueError, "cannot edit editor.accessibilitySupport"):
            cli.configure_vscode_accessibility(path)
        self.assertEqual(path.read_text(), original)

    def test_command_reports_invalid_settings_without_a_traceback(self):
        path = self.run_setup("{ not json")
        rc = cli.main(["vscode-setup", "--settings", str(path)])
        self.assertEqual(rc, 1)
        self.assertEqual(path.read_text(), "{ not json")


if __name__ == "__main__":
    unittest.main()
