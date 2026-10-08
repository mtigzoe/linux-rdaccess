#!/usr/bin/env python3
"""Emit deterministic NVDA-A11Y messages for cross-repo state/value tests."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_model import build_focus_payload


class FakeState:
    def __init__(self, value_nick):
        self.value_nick = value_nick


class FakeStateSet:
    def __init__(self, states):
        self._states = [FakeState(state) for state in states]

    def get_states(self):
        return self._states


class FakeValue:
    def __init__(self, *, current=None, text=""):
        self._current = current
        self._text = text

    def get_text(self):
        return self._text

    def get_current_value(self):
        return self._current


class FakeAccessible:
    _next_hash = 3000

    def __init__(
        self,
        name,
        role,
        parent=None,
        *,
        states=(),
        value_iface=None,
    ):
        self._name = name
        self._role = role
        self._parent = parent
        self._states = states
        self._value_iface = value_iface
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

    def get_state_set(self):
        return FakeStateSet(self._states)

    def get_value_iface(self):
        return self._value_iface


app = FakeAccessible("Test App", "application")
dialog = FakeAccessible("Controls", "dialog", app)

cases = [
    {
        "target": FakeAccessible(
            "Remember me",
            "check box",
            dialog,
            states=("checked", "focusable"),
        ),
        "expected_nvda_states": ["CHECKED", "FOCUSABLE", "FOCUSED"],
        "expected_value": "",
    },
    {
        "target": FakeAccessible(
            "Documents",
            "tree item",
            dialog,
            states=("expanded", "selected"),
        ),
        "expected_nvda_states": ["EXPANDED", "FOCUSED", "SELECTED"],
        "expected_value": "",
    },
    {
        "target": FakeAccessible(
            "Read only field",
            "text",
            dialog,
            states=("read-only", "focusable"),
        ),
        "expected_nvda_states": ["FOCUSABLE", "FOCUSED", "READONLY"],
        "expected_value": "",
    },
    {
        "target": FakeAccessible(
            "Volume",
            "slider",
            dialog,
            states=("focusable",),
            value_iface=FakeValue(current=75.0, text="75 percent"),
        ),
        "expected_nvda_states": ["FOCUSABLE", "FOCUSED"],
        "expected_value": "75 percent",
    },
    {
        "target": FakeAccessible(
            "Color",
            "combo box",
            dialog,
            states=("focusable", "expanded"),
            value_iface=FakeValue(text="Green"),
        ),
        "expected_nvda_states": ["EXPANDED", "FOCUSABLE", "FOCUSED"],
        "expected_value": "Green",
    },
]

messages = []
for case in cases:
    payload = build_focus_payload(
        "object:state-changed:focused",
        1,
        case["target"],
    )
    assert payload is not None
    messages.append(
        {
            "expected_nvda_states": case["expected_nvda_states"],
            "expected_value": case["expected_value"],
            "message": {"type": "a11y_focus", **payload},
        }
    )

print(json.dumps(messages, separators=(",", ":")))
