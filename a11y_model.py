"""Pure-Python AT-SPI object snapshot model for the remote NVDA object channel."""

from __future__ import annotations

from typing import Any

A11Y_FOCUS_EVENTS = frozenset({
    "object:state-changed:focused",
    "object:active-descendant-changed",
    "window:activate",
})


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def object_id(obj: object) -> str:
    """Return a stable ID for one live AT-SPI proxy within this bridge process."""
    try:
        value = hash(obj)
    except TypeError:
        value = id(obj)
    return f"{value & ((1 << 64) - 1):016x}"


def _parent(obj):
    try:
        return obj.get_parent()
    except Exception:
        return None


def _snapshot(obj, *, parent_id: str | None, focused: bool) -> dict[str, Any]:
    try:
        description = _clean(obj.get_description())
    except Exception:
        description = ""
    return {
        "id": object_id(obj),
        "parent_id": parent_id,
        "name": _clean(obj.get_name()),
        "role": _clean(obj.get_role_name()),
        "description": description,
        "value": "",
        "states": ["focused", "focusable"] if focused else [],
    }


def build_focus_payload(event_type: str, detail1: int, source, any_data=None, *, max_depth: int = 24):
    """Build a focused object + ancestor snapshot, or None for a non-focus event."""
    if event_type not in A11Y_FOCUS_EVENTS:
        return None
    if event_type == "object:state-changed:focused" and not detail1:
        return None
    target = any_data if event_type == "object:active-descendant-changed" and hasattr(any_data, "get_name") else source
    if target is None or not hasattr(target, "get_name"):
        return None

    chain = []
    current = target
    seen = set()
    for _ in range(max_depth):
        oid = object_id(current)
        if oid in seen:
            break
        seen.add(oid)
        parent = _parent(current)
        role = _clean(current.get_role_name())
        parent_id = None if parent is None or role == "application" else object_id(parent)
        chain.append((current, parent_id))
        if parent_id is None:
            break
        current = parent

    focus_id = object_id(target)
    return {
        "focus_id": focus_id,
        "objects": [
            _snapshot(obj, parent_id=parent_id, focused=object_id(obj) == focus_id)
            for obj, parent_id in chain
        ],
    }
