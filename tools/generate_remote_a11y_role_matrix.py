#!/usr/bin/env python3
"""Emit deterministic NVDA-A11Y messages for cross-repo role compatibility tests."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_model import build_focus_payload


class FakeAccessible:
    _next_hash = 2000

    def __init__(self, name, role, parent=None, description=""):
        self._name = name
        self._role = role
        self._parent = parent
        self._description = description
        self._hash = FakeAccessible._next_hash
        FakeAccessible._next_hash += 1

    def __hash__(self):
        return self._hash

    def get_name(self):
        return self._name

    def get_role_name(self):
        return self._role

    def get_description(self):
        return self._description

    def get_parent(self):
        return self._parent


CASES = [
    ("Save", "push button", "BUTTON"),
    ("Remember me", "check box", "CHECKBOX"),
    ("Color", "combo box", "COMBOBOX"),
    ("Username", "text", "EDITABLETEXT"),
    ("Documentation", "link", "LINK"),
    ("Account", "heading", "HEADING"),
    ("Results", "table", "TABLE"),
    ("Name", "table cell", "TABLECELL"),
    ("Folders", "tree", "TREEVIEW"),
    ("Documents", "tree item", "TREEVIEWITEM"),
    ("Choice A", "radio button", "RADIOBUTTON"),
    ("Progress", "progress bar", "PROGRESSBAR"),
    ("Volume", "slider", "SLIDER"),
    ("File", "menu item", "MENUITEM"),
    ("General", "page tab", "TAB"),
    ("Tabs", "page tab list", "TABCONTROL"),
    ("Terminal", "terminal", "TERMINAL"),
]

app = FakeAccessible("Test App", "application")
dialog = FakeAccessible("Controls", "dialog", app)

messages = []
for name, role, expected_nvda_role in CASES:
    target = FakeAccessible(name, role, dialog)
    payload = build_focus_payload("object:state-changed:focused", 1, target)
    assert payload is not None
    messages.append(
        {
            "expected_nvda_role": expected_nvda_role,
            "message": {"type": "a11y_focus", **payload},
        }
    )

print(json.dumps(messages, separators=(",", ":")))
