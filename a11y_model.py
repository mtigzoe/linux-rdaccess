"""Pure-Python AT-SPI object snapshot model for the remote NVDA object channel."""

from __future__ import annotations

from typing import Any

A11Y_FOCUS_EVENTS = frozenset({
    "object:state-changed:focused",
    "object:active-descendant-changed",
    "window:activate",
})
DEFAULT_MAX_OBJECTS = 64
MAX_ACTIONS = 32


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


def _children(obj) -> list:
    try:
        count = int(obj.get_child_count())
    except Exception:
        return []
    children = []
    for index in range(max(0, count)):
        try:
            child = obj.get_child_at_index(index)
        except Exception:
            continue
        if child is not None and hasattr(child, "get_name"):
            children.append(child)
    return children


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


def _action_iface(obj):
    try:
        iface = obj.get_action_iface()
    except Exception:
        iface = None
    if iface is not None:
        return iface
    try:
        return obj.get_action()
    except Exception:
        return None


def action_names(obj) -> list[str]:
    """Return the bounded ordered AT-SPI action names for an accessible object."""
    iface = _action_iface(obj)
    if iface is None:
        return []
    try:
        count = min(MAX_ACTIONS, max(0, int(iface.get_n_actions())))
    except Exception:
        return []
    names = []
    for index in range(count):
        try:
            name = _clean(iface.get_action_name(index))
        except Exception:
            name = ""
        names.append(name or f"action {index + 1}")
    return names


def perform_action(obj, index: int) -> bool:
    """Perform one bounded AT-SPI action by index."""
    if type(index) is not int or index < 0 or index >= MAX_ACTIONS:
        return False
    iface = _action_iface(obj)
    if iface is None:
        return False
    try:
        count = int(iface.get_n_actions())
    except Exception:
        return False
    if index >= count:
        return False
    try:
        result = iface.do_action(index)
    except Exception:
        return False
    return result is not False


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


def _bounds(obj, coord_type) -> list[int] | None:
    if coord_type is None:
        return None
    try:
        component = obj.get_component_iface()
    except Exception:
        component = None
    if component is None:
        try:
            component = obj.get_component()
        except Exception:
            return None
    try:
        rect = component.get_extents(coord_type)
        values = [int(rect.x), int(rect.y), int(rect.width), int(rect.height)]
    except Exception:
        return None
    if values[2] < 0 or values[3] < 0:
        return None
    return values


def _snapshot(
    obj,
    *,
    parent_id: str | None,
    child_ids: list[str],
    focused: bool,
    coord_type=None,
) -> dict[str, Any]:
    try:
        description = _clean(obj.get_description())
    except Exception:
        description = ""
    return {
        "id": object_id(obj),
        "parent_id": parent_id,
        "child_ids": child_ids,
        "name": _clean(obj.get_name()),
        "role": _clean(obj.get_role_name()),
        "description": description,
        "value": _value(obj),
        "actions": action_names(obj),
        "states": _states(obj, focused=focused),
        "bounds": _bounds(obj, coord_type),
    }


def build_focus_payload(
    event_type: str,
    detail1: int,
    source,
    any_data=None,
    *,
    max_depth: int = 24,
    max_objects: int = DEFAULT_MAX_OBJECTS,
    coord_type=None,
    object_registry: dict[str, object] | None = None,
):
    """Build a bounded focus-neighborhood snapshot.

    The focused object and its ancestor chain are highest priority. Remaining
    capacity is filled with the immediate children of each object on that path.
    This exposes the focused object's children and its siblings at each ancestor
    level without serializing an application's entire accessibility tree.
    """
    if event_type not in A11Y_FOCUS_EVENTS:
        return None
    if event_type == "object:state-changed:focused" and not detail1:
        return None
    target = any_data if event_type == "object:active-descendant-changed" and hasattr(any_data, "get_name") else source
    if target is None or not hasattr(target, "get_name"):
        return None
    if max_objects < 1:
        return None

    chain = []
    current = target
    seen = set()
    for _ in range(min(max_depth, max_objects)):
        oid = object_id(current)
        if oid in seen:
            break
        seen.add(oid)
        chain.append(current)
        parent = _parent(current)
        role = _clean(current.get_role_name())
        if parent is None or role == "application":
            break
        current = parent

    selected = list(chain)
    selected_ids = {object_id(obj) for obj in selected}
    children_cache: dict[str, list] = {}

    # Target first gives its direct children priority; then each ancestor gives
    # us the target's siblings and sibling groups higher in the hierarchy.
    for parent in chain:
        parent_oid = object_id(parent)
        children = _children(parent)
        children_cache[parent_oid] = children
        for child in children:
            if len(selected) >= max_objects:
                break
            child_oid = object_id(child)
            if child_oid in selected_ids:
                continue
            selected.append(child)
            selected_ids.add(child_oid)
        if len(selected) >= max_objects:
            break

    # Cache child order for any selected object not already visited above. This
    # is mainly useful for siblings that happen to be containers; references to
    # non-serialized children are filtered out below.
    for obj in selected:
        oid = object_id(obj)
        children_cache.setdefault(oid, _children(obj))

    focus_id = object_id(target)
    objects = []
    for obj in selected:
        oid = object_id(obj)
        parent = _parent(obj)
        role = _clean(obj.get_role_name())
        parent_oid = object_id(parent) if parent is not None else None
        parent_id = None if role == "application" or parent_oid not in selected_ids else parent_oid
        child_ids = [
            child_oid
            for child in children_cache[oid]
            if (child_oid := object_id(child)) in selected_ids
        ]
        objects.append(
            _snapshot(
                obj,
                parent_id=parent_id,
                child_ids=child_ids,
                focused=oid == focus_id,
                coord_type=coord_type,
            )
        )

    if object_registry is not None:
        object_registry.clear()
        object_registry.update({object_id(obj): obj for obj in selected})

    return {
        "focus_id": focus_id,
        "objects": objects,
    }
