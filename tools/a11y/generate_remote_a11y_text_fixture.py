#!/usr/bin/env python3
"""Emit one deterministic focused AT-SPI text snapshot."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_model import build_focus_payload


class FakeSelection:
    def __init__(self, start_offset, end_offset):
        self.start_offset = start_offset
        self.end_offset = end_offset


class FakeText:
    def __init__(self, text, caret, selection):
        self._text = text
        self._caret = caret
        self._selection = selection

    def get_character_count(self):
        return len(self._text)

    def get_text(self, start, end):
        return self._text[start:end]

    def get_caret_offset(self):
        return self._caret

    def get_n_selections(self):
        return 1

    def get_selection(self, index):
        if index != 0:
            raise IndexError(index)
        return FakeSelection(*self._selection)


class FakeAccessible:
    _next_hash = 11000

    def __init__(self, name, role, parent=None, *, text_iface=None):
        self._name = name
        self._role = role
        self._parent = parent
        self._children = []
        self._text_iface = text_iface
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

    def get_text_iface(self):
        return self._text_iface


app = FakeAccessible("Test App", "application")
dialog = FakeAccessible("Editor window", "dialog", app)
editor = FakeAccessible(
    "Document",
    "text",
    dialog,
    text_iface=FakeText("hello world", caret=5, selection=(1, 4)),
)

payload = build_focus_payload("object:state-changed:focused", 1, editor)
assert payload is not None

print(
    json.dumps(
        {
            "message": {"type": "a11y_focus", **payload},
            "expected": {
                "text": "hello world",
                "caret_offset": 5,
                "selection_start": 1,
                "selection_end": 4,
                "text_truncated": False,
            },
        },
        separators=(",", ":"),
    )
)
