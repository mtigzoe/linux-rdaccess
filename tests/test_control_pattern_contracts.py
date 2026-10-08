"""Pre-live contracts for common Linux desktop accessibility control patterns."""

from __future__ import annotations

import unittest

from a11y_model import build_focus_payload, object_id
from announcer import (
    ACTIVE_DESCENDANT,
    FOCUS,
    NAME_CHANGED,
    SELECTED,
    Announcer,
)
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeAction, FakeText, FakeValue


class ControlPatternContractTests(unittest.TestCase):
    def focused_item(self, accessible):
        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            accessible,
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["focus_id"], object_id(accessible))
        return next(item for item in payload["objects"] if item["id"] == payload["focus_id"])

    def test_standard_control_matrix_preserves_name_role_state_value_and_actions(self):
        cases = (
            {
                "label": "button",
                "obj": FakeAccessible(
                    "Apply changes",
                    "push button",
                    states=("focusable", "enabled"),
                    action_iface=FakeAction(["click"]),
                ),
                "states": {"focusable", "enabled", "focused"},
                "actions": ["click"],
            },
            {
                "label": "checkbox",
                "obj": FakeAccessible(
                    "Enable notifications",
                    "check box",
                    states=("focusable", "enabled", "checked"),
                    action_iface=FakeAction(["toggle"]),
                ),
                "states": {"focusable", "enabled", "checked", "focused"},
                "actions": ["toggle"],
            },
            {
                "label": "radio",
                "obj": FakeAccessible(
                    "Choice alpha",
                    "radio button",
                    states=("focusable", "enabled", "checked", "selected"),
                    action_iface=FakeAction(["click"]),
                ),
                "states": {"focusable", "enabled", "checked", "selected", "focused"},
                "actions": ["click"],
            },
            {
                "label": "combo",
                "obj": FakeAccessible(
                    "Display mode",
                    "combo box",
                    states=("focusable", "enabled", "collapsed"),
                    value_iface=FakeValue(text="Automatic"),
                    action_iface=FakeAction(["press"]),
                ),
                "states": {"focusable", "enabled", "collapsed", "focused"},
                "value": "Automatic",
                "actions": ["press"],
            },
            {
                "label": "slider",
                "obj": FakeAccessible(
                    "Volume",
                    "slider",
                    states=("focusable", "enabled"),
                    value_iface=FakeValue(current=65.0, text="65 percent"),
                ),
                "states": {"focusable", "enabled", "focused"},
                "value": "65 percent",
            },
            {
                "label": "list item",
                "obj": FakeAccessible(
                    "Document.txt",
                    "list item",
                    states=("focusable", "enabled", "selected"),
                    action_iface=FakeAction(["activate"]),
                ),
                "states": {"focusable", "enabled", "selected", "focused"},
                "actions": ["activate"],
            },
            {
                "label": "tree item",
                "obj": FakeAccessible(
                    "Pictures",
                    "tree item",
                    states=("focusable", "enabled", "expandable", "expanded", "selected"),
                    action_iface=FakeAction(["activate", "expand or contract"]),
                ),
                "states": {
                    "focusable", "enabled", "expandable", "expanded", "selected", "focused"
                },
                "actions": ["activate", "expand or contract"],
            },
            {
                "label": "table cell",
                "obj": FakeAccessible(
                    "R2 B",
                    "table cell",
                    states=("focusable", "enabled", "selected"),
                ),
                "states": {"focusable", "enabled", "selected", "focused"},
            },
            {
                "label": "tab",
                "obj": FakeAccessible(
                    "Editor",
                    "page tab",
                    states=("focusable", "enabled", "selected"),
                    action_iface=FakeAction(["activate"]),
                ),
                "states": {"focusable", "enabled", "selected", "focused"},
                "actions": ["activate"],
            },
            {
                "label": "menu item",
                "obj": FakeAccessible(
                    "Close",
                    "menu item",
                    states=("focusable", "enabled"),
                    action_iface=FakeAction(["click"]),
                ),
                "states": {"focusable", "enabled", "focused"},
                "actions": ["click"],
            },
            {
                "label": "progress",
                "obj": FakeAccessible(
                    "Update progress",
                    "progress bar",
                    value_iface=FakeValue(current=42.0, text="42 percent"),
                ),
                "states": {"focused"},
                "value": "42 percent",
            },
            {
                "label": "calendar cell",
                "obj": FakeAccessible(
                    "October 7",
                    "table cell",
                    states=("focusable", "enabled", "selected"),
                ),
                "states": {"focusable", "enabled", "selected", "focused"},
            },
        )

        for case in cases:
            with self.subTest(pattern=case["label"]):
                item = self.focused_item(case["obj"])
                self.assertEqual(item["name"], case["obj"].get_name())
                self.assertEqual(item["role"], case["obj"].get_role_name())
                self.assertEqual(set(item["states"]), case["states"])
                self.assertEqual(item["value"], case.get("value", ""))
                self.assertEqual(item["actions"], case.get("actions", []))

    def test_single_line_entry_preserves_text_caret_and_selection(self):
        entry = FakeAccessible(
            "Account name",
            "entry",
            states=("focusable", "enabled", "editable"),
            text_iface=FakeText("sample-user", caret=6, selection=(0, 6)),
        )
        item = self.focused_item(entry)
        self.assertTrue(item["text_supported"])
        self.assertEqual(item["text"], "sample-user")
        self.assertEqual(item["caret_offset"], 6)
        self.assertEqual((item["selection_start"], item["selection_end"]), (0, 6))
        self.assertIn("editable", item["states"])

    def test_multiline_editor_preserves_newlines_and_caret(self):
        text = "Line one.\nLine two.\nLine three."
        editor = FakeAccessible(
            "Notes",
            "text",
            states=("focusable", "enabled", "editable", "multi line"),
            text_iface=FakeText(text, caret=len("Line one.\n")),
        )
        item = self.focused_item(editor)
        self.assertEqual(item["text"], text)
        self.assertEqual(item["caret_offset"], len("Line one.\n"))
        self.assertIn("multi line", item["states"])

    def test_focus_chain_keeps_dialog_and_application_context(self):
        app = FakeAccessible("Smoke Test", "application")
        dialog = FakeAccessible("Sample confirmation", "dialog", app, states=("active",))
        button = FakeAccessible("OK", "push button", dialog, states=("focusable", "enabled"))
        payload = build_focus_payload("object:state-changed:focused", 1, button)
        by_id = {item["id"]: item for item in payload["objects"]}
        self.assertEqual(by_id[object_id(button)]["parent_id"], object_id(dialog))
        self.assertEqual(by_id[object_id(dialog)]["parent_id"], object_id(app))
        self.assertIsNone(by_id[object_id(app)]["parent_id"])

    def test_active_descendant_announces_list_and_table_children(self):
        announcer = Announcer()
        for role, child_role in (("list", "list item"), ("tree", "tree item"), ("table", "table cell")):
            with self.subTest(role=role):
                container = FakeAccessible("Items", role)
                child = FakeAccessible("Selected row", child_role)
                result = announcer.handle(ACTIVE_DESCENDANT, 0, container, child)
                self.assertIsNotNone(result)
                self.assertEqual(result.text, f"Selected row, {child_role}")
                self.assertTrue(result.interrupt)

    def test_selection_is_announced_with_selected_suffix(self):
        announcer = Announcer()
        row = FakeAccessible("Document.txt", "list item")
        result = announcer.handle(SELECTED, 1, row)
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Document.txt, list item, selected")
        self.assertTrue(result.interrupt)

    def test_focus_return_after_dialog_is_not_deduped(self):
        now = [0.0]
        announcer = Announcer(clock=lambda: now[0])
        entry = FakeAccessible("Account name", "entry")
        first = announcer.handle(FOCUS, 1, entry)
        self.assertIsNotNone(first)
        now[0] = 0.1
        self.assertIsNone(announcer.handle(FOCUS, 0, entry))
        now[0] = 0.2
        second = announcer.handle(FOCUS, 1, entry)
        self.assertIsNotNone(second)
        self.assertEqual(second.text, "Account name, entry")

    def test_two_controls_with_same_name_are_not_merged(self):
        announcer = Announcer()
        first = FakeAccessible("Browse", "push button")
        second = FakeAccessible("Browse", "push button")
        self.assertIsNotNone(announcer.handle(FOCUS, 1, first))
        self.assertIsNotNone(announcer.handle(FOCUS, 1, second))

    def test_focused_dynamic_name_change_is_announced_without_interrupt(self):
        focused = FakeAccessible("Ready", "label")
        announcer = Announcer(is_focused=lambda obj: obj is focused)
        result = announcer.handle(NAME_CHANGED, 0, focused)
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "Ready, label")
        self.assertFalse(result.interrupt)


if __name__ == "__main__":
    unittest.main()
