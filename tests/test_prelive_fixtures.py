"""Static contracts for deterministic pre-live browser and GTK fixtures."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
BROWSER_FIXTURE = ROOT / "tests" / "fixtures" / "browser-control-patterns.html"
SMOKE_APP = ROOT / "tests" / "apps" / "accessibility_smoke_app.py"


class _FixtureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.ids = set()
        self.roles = []
        self.landmarks = []
        self.inputs = []
        self.aria_live = []
        self.headings = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        role = attrs.get("role")
        if role:
            self.roles.append(role)
        if tag in {"main", "nav", "aside", "header", "footer"}:
            self.landmarks.append(tag)
        if tag == "input":
            self.inputs.append(attrs.get("type", "text"))
        if attrs.get("aria-live"):
            self.aria_live.append(attrs["aria-live"])
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(tag)
        if role == "heading" and attrs.get("aria-level"):
            self.headings.append(f"aria-{attrs['aria-level']}")


class BrowserFixtureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = BROWSER_FIXTURE.read_text(encoding="utf-8")
        cls.parser = _FixtureParser()
        cls.parser.feed(cls.text)

    def test_fixture_contains_core_form_controls(self):
        self.assertTrue({"text", "checkbox", "radio", "range"} <= set(self.parser.inputs))
        for tag in ("textarea", "select", "button", "progress", "dialog"):
            self.assertIn(tag, self.parser.tags)

    def test_fixture_contains_composite_control_patterns(self):
        roles = set(self.parser.roles)
        for role in (
            "tablist",
            "tab",
            "tabpanel",
            "tree",
            "treeitem",
            "grid",
            "status",
        ):
            with self.subTest(role=role):
                self.assertIn(role, roles)

    def test_fixture_contains_browse_navigation_targets(self):
        self.assertIn("h1", self.parser.headings)
        self.assertIn("h2", self.parser.headings)
        self.assertIn("h3", self.parser.headings)
        for level in ("aria-7", "aria-8", "aria-9"):
            self.assertIn(level, self.parser.headings)
        self.assertTrue({"main", "nav", "aside"} <= set(self.parser.landmarks))
        self.assertIn("a", self.parser.tags)

    def test_fixture_contains_dynamic_lifetime_reproduction_controls(self):
        for element_id in (
            "dynamic-link",
            "replace-link",
            "remove-link",
            "dynamic-region",
            "live-region",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(element_id, self.parser.ids)
        self.assertIn("replaceChildren", self.text)
        self.assertIn("innerHTML", self.text)

    def test_fixture_contains_dialog_focus_and_live_region_targets(self):
        for element_id in ("open-dialog", "dialog", "dialog-ok", "dialog-cancel", "status"):
            self.assertIn(element_id, self.parser.ids)
        self.assertIn("polite", self.parser.aria_live)


class GtkSmokeAppContractTests(unittest.TestCase):
    def list_controls(self):
        result = subprocess.run(
            [sys.executable, str(SMOKE_APP), "--list-controls"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_smoke_app_declares_required_control_patterns_without_gtk(self):
        controls = self.list_controls()
        patterns = {item["pattern"] for item in controls}
        required = {
            "button",
            "checkbox",
            "radio",
            "combobox",
            "slider",
            "entry",
            "multiline-text",
            "list-tree",
            "tabs",
            "menu",
            "progress",
            "calendar",
            "dialog",
            "status",
        }
        self.assertEqual(patterns, required)

    def test_smoke_app_control_ids_are_unique_and_described(self):
        controls = self.list_controls()
        ids = [item["id"] for item in controls]
        self.assertEqual(len(ids), len(set(ids)))
        for item in controls:
            with self.subTest(control=item["id"]):
                self.assertTrue(item["label"].strip())
                self.assertTrue(item["expected_role"].strip())

    def test_smoke_app_source_compiles_without_importing_gtk(self):
        source = SMOKE_APP.read_text(encoding="utf-8")
        compile(source, str(SMOKE_APP), "exec")
        self.assertIn("def build_window", source)
        self.assertIn("Gtk.Application", source)


if __name__ == "__main__":
    unittest.main()
