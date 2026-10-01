#!/usr/bin/env python3
"""Emit one deterministic Linux accessibility object with AT-SPI actions."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_model import build_focus_payload


class FakeAction:
    def __init__(self, names):
        self._names = list(names)

    def get_n_actions(self):
        return len(self._names)

    def get_action_name(self, index):
        return self._names[index]


class FakeAccessible:
    _next_hash = 9000

    def __init__(self, name, role, parent=None, *, actions=()):
        self._name = name
        self._role = role
        self._parent = parent
        self._children = []
        self._actions = FakeAction(actions) if actions else None
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

    def get_action_iface(self):
        return self._actions


app = FakeAccessible("Test App", "application")
dialog = FakeAccessible("Settings", "dialog", app)
button = FakeAccessible(
    "More",
    "push button",
    dialog,
    actions=("click", "show menu"),
)

payload = build_focus_payload("object:state-changed:focused", 1, button)
assert payload is not None

print(
    json.dumps(
        {
            "message": {"type": "a11y_focus", **payload},
            "expected_actions": ["click", "show menu"],
        },
        separators=(",", ":"),
    )
)
