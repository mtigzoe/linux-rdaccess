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


def _state_name(state: object) -> str:
    """Normalize a GI enum/state token into the wire-format spelling."""
    for attr in ("value_nick", "value_name", "name"):
        raw = getattr(state, attr, None)
        if raw:
            text = str(raw)
            break
    else:
        text = str(state)
    text = text.strip().lower()
    for prefix in ("atspi_state_", "state_"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.replace("-", " ").replace("_", " ")


def _states(obj, *, focused: bool) -> list[str]:
    states: set[str] = set()
    try:
        state_set = obj.get_state_set()
        raw_states = state_set.get_states()
    except Exception:
        raw_states = ()
    for state in raw_states or ():
        name = _state_name(state)
        if name and name != "invalid":
            states.add(name)
    # The event itself is authoritative for the focus target and covers
    # toolkits that lag when their state set is queried during notification.
    if focused:
        states.add("focused")
    return sorted(states)


def _value(obj) -> str:
    """Return the human-readable AT-SPI Value text/current value when exposed."""
    try:
        iface = obj.get_value_iface()
    except Exception:
        iface = None
    if iface is None:
        try:
            iface = obj.get_value()
        except Exception:
            return ""

    try:
        text = _clean(iface.get_text())
    except Exception:
        text = ""
    if text:
        return text

    try:
        current = iface.get_current_value()
    except Exception:
        return ""
    if current is None:
        return ""
    if isinstance(current, float) and current.is_integer():
        return str(int(current))
    return _clean(current)


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
        "value": _value(obj),
        "states": _states(obj, focused=focused),
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
