#!/usr/bin/env python3
"""Emit a deterministic bounded A11Y navigation fixture."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_model import build_focus_payload


class FakeAccessible:
    _next_hash = 7000

    def __init__(self, name, role, parent=None):
        self._name = name
        self._role = role
        self._parent = parent
        self._children = []
        if parent is not None:
            parent._children.append(self)
        self._hash = FakeAccessible._next_hash
        FakeAccessible._next_hash += 1

    def __hash__(self):
        return self._hash

    def get_name(self):
        return self._name

    def get_role_name(self):
        return self._role

    def get_description(self):
        return ""

    def get_parent(self):
        return self._parent

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]


app = FakeAccessible("Test App", "application")
dialog = FakeAccessible("Settings", "dialog", app)
cancel = FakeAccessible("Cancel", "push button", dialog)
save = FakeAccessible("Save", "push button", dialog)
help_button = FakeAccessible("Help", "push button", dialog)
hint = FakeAccessible("Keyboard shortcut", "label", save)

payload = build_focus_payload("object:state-changed:focused", 1, save)
assert payload is not None

print(
    json.dumps(
        {
            "message": {"type": "a11y_focus", **payload},
            "expected": {
                "focus": "Save",
                "previous": "Cancel",
                "next": "Help",
                "first_child": "Keyboard shortcut",
                "parent": "Settings",
                "parent_first_child": "Cancel",
                "parent_last_child": "Help",
            },
        },
        separators=(",", ":"),
    )
)
