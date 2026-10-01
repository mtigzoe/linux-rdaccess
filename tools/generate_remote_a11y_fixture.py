#!/usr/bin/env python3
"""Emit one deterministic NVDA-A11Y focus message for cross-repo compatibility tests."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_model import build_focus_payload


class FakeAccessible:
    _next_hash = 1000

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


app = FakeAccessible("Test App", "application")
dialog = FakeAccessible("Settings", "dialog", app)
button = FakeAccessible("Save", "push button", dialog, "Save changes")

payload = build_focus_payload("object:state-changed:focused", 1, button)
assert payload is not None
print(json.dumps({"type": "a11y_focus", **payload}, separators=(",", ":")))
