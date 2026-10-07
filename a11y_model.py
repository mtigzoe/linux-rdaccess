"""Pure-Python AT-SPI object snapshot model for the remote NVDA object channel."""

from __future__ import annotations

from typing import Any

A11Y_FOCUS_EVENTS = frozenset({
    "object:state-changed:focused",
    "object:active-descendant-changed",
    "window:activate",
})
A11Y_TEXT_EVENTS = frozenset({
    "object:text-caret-moved",
    "object:text-selection-changed",
    "object:text-changed:insert",
    "object:text-changed:delete",
})
DEFAULT_MAX_OBJECTS = 64
MAX_FOCUS_SEARCH_NODES = 4096
MAX_FOCUS_SEARCH_DEPTH = 32
MAX_ACTIONS = 32
MAX_FOCUS_TEXT_CHARS = 8192


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _invoke(obj, names: tuple[str, ...], *args):
    for name in names:
        method = getattr(obj, name, None)
        if not callable(method):
            continue
        try:
            return method(*args)
        except Exception:
            continue
    return None


def _looks_accessible(obj) -> bool:
    return obj is not None and (
        callable(getattr(obj, "get_name", None))
        or callable(getattr(obj, "getName", None))
        or hasattr(obj, "name")
    )


def _name(obj) -> str:
    value = _invoke(obj, ("get_name", "getName"))
    if value is None:
        value = getattr(obj, "name", "")
    return _clean(value)


def _role_name(obj) -> str:
    value = _invoke(obj, ("get_role_name", "getRoleName"))
    if value is None:
        value = getattr(obj, "roleName", "")
    return _clean(value)


def _description(obj) -> str:
    value = _invoke(obj, ("get_description", "getDescription"))
    if value is None:
        value = getattr(obj, "description", "")
    return _clean(value)


def object_id(obj: object) -> str:
    """Return a stable ID for one live AT-SPI proxy within this bridge process."""
    try:
        value = hash(obj)
    except TypeError:
        value = id(obj)
    return f"{value & ((1 << 64) - 1):016x}"


def _parent(obj):
    parent = _invoke(obj, ("get_parent", "getParent"))
    if parent is not None:
        return parent
    try:
        return getattr(obj, "parent", None)
    except Exception:
        return None


def _children(obj) -> list:
    count = _invoke(obj, ("get_child_count", "getChildCount"))
    if count is None:
        count = getattr(obj, "childCount", None)
    try:
        count = int(count)
    except (TypeError, ValueError):
        return []
    children = []
    for index in range(max(0, count)):
        child = _invoke(obj, ("get_child_at_index", "getChildAtIndex"), index)
        if _looks_accessible(child):
            children.append(child)
    return children


def _state_name(state: object) -> str:
    """Normalize GI or legacy pyatspi state tokens into wire-format spelling."""
    for attr in ("value_nick", "value_name", "name"):
        raw = getattr(state, attr, None)
        if raw:
            text = str(raw)
            break
    else:
        text = str(state)

    # Legacy pyatspi commonly exposes integer STATE_* constants. Resolve them
    # lazily so this pure-Python module still imports where pyatspi is absent.
    if text.strip().lstrip("-").isdigit():
        try:
            import pyatspi  # type: ignore
            for attr in dir(pyatspi):
                if attr.startswith("STATE_") and getattr(pyatspi, attr, object()) == state:
                    text = attr
                    break
        except Exception:
            pass

    text = text.strip().lower()
    for prefix in ("atspi_state_", "state_"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.replace("-", " ").replace("_", " ")


def _states(obj, *, focused: bool) -> list[str]:
    states: set[str] = set()
    state_set = _invoke(obj, ("get_state_set", "getState"))
    if state_set is None:
        raw_states = ()
    else:
        raw_states = _invoke(state_set, ("get_states", "getStates"))
        if raw_states is None:
            raw_states = getattr(state_set, "states", ())
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
    return _invoke(obj, ("get_action_iface", "get_action", "queryAction"))


def action_names(obj) -> list[str]:
    """Return the bounded ordered AT-SPI action names for an accessible object."""
    iface = _action_iface(obj)
    if iface is None:
        return []
    count = _invoke(iface, ("get_n_actions", "getNActions"))
    if count is None:
        count = getattr(iface, "nActions", None)
    try:
        count = min(MAX_ACTIONS, max(0, int(count)))
    except (TypeError, ValueError):
        return []
    names = []
    for index in range(count):
        try:
            name = _clean(_invoke(iface, ("get_action_name", "getName"), index))
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
    count = _invoke(iface, ("get_n_actions", "getNActions"))
    if count is None:
        count = getattr(iface, "nActions", None)
    try:
        count = int(count)
    except (TypeError, ValueError):
        return False
    if index >= count:
        return False
    for name in ("do_action", "doAction"):
        method = getattr(iface, name, None)
        if not callable(method):
            continue
        try:
            return method(index) is not False
        except Exception:
            continue
    return False


def _text_iface(obj):
    return _invoke(obj, ("get_text_iface", "queryText"))


def _selection_offsets(iface) -> tuple[int, int] | None:
    count = _invoke(iface, ("get_n_selections", "getNSelections"))
    if count is None:
        count = getattr(iface, "nSelections", None)
    try:
        if int(count) <= 0:
            return None
    except (TypeError, ValueError):
        return None
    selection = _invoke(iface, ("get_selection", "getSelection"), 0)
    if selection is None:
        return None

    start = getattr(selection, "start_offset", None)
    end = getattr(selection, "end_offset", None)
    if start is None or end is None:
        if isinstance(selection, tuple) and len(selection) >= 2:
            start, end = selection[-2], selection[-1]
        else:
            return None
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        return None
    if start < 0 or end < start:
        return None
    return start, end


def _text_snapshot(obj, *, focused: bool) -> dict[str, Any]:
    empty = {
        "text_supported": False,
        "text": "",
        "text_truncated": False,
        "caret_offset": None,
        "selection_start": None,
        "selection_end": None,
    }
    if not focused:
        return empty

    iface = _text_iface(obj)
    if iface is None:
        return empty
    character_count = _invoke(iface, ("get_character_count", "getCharacterCount"))
    if character_count is None:
        character_count = getattr(iface, "characterCount", None)
    try:
        character_count = max(0, int(character_count))
    except (TypeError, ValueError):
        return empty

    end = min(character_count, MAX_FOCUS_TEXT_CHARS)
    try:
        text = str(_invoke(iface, ("get_text", "getText"), 0, end) or "")
    except Exception:
        return empty
    # Guard against a broken provider returning more text than requested.
    text = text[:MAX_FOCUS_TEXT_CHARS]
    visible_length = len(text)

    try:
        raw_caret = _invoke(iface, ("get_caret_offset", "getCaretOffset"))
        if raw_caret is None:
            raw_caret = getattr(iface, "caretOffset", None)
        caret = int(raw_caret)
    except Exception:
        caret = None
    if caret is not None and not 0 <= caret <= visible_length:
        caret = None

    selection_start = selection_end = None
    selection = _selection_offsets(iface)
    if selection is not None:
        start, finish = selection
        if 0 <= start <= finish <= visible_length:
            selection_start, selection_end = start, finish

    return {
        "text_supported": True,
        "text": text,
        "text_truncated": character_count > visible_length,
        "caret_offset": caret,
        "selection_start": selection_start,
        "selection_end": selection_end,
    }


def _value(obj) -> str:
    """Return the human-readable GI or pyatspi Value text/current value."""
    iface = _invoke(obj, ("get_value_iface", "get_value", "queryValue"))
    if iface is None:
        return ""

    text = _clean(_invoke(iface, ("get_text", "getText")))
    if text:
        return text

    current = _invoke(iface, ("get_current_value", "getCurrentValue"))
    if current is None:
        current = getattr(iface, "currentValue", None)
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


def find_focused_object(
    desktop,
    *,
    max_nodes: int = MAX_FOCUS_SEARCH_NODES,
    max_depth: int = MAX_FOCUS_SEARCH_DEPTH,
):
    """Find the AT-SPI object that currently has keyboard focus.

    Used when no focus event is available to react to: the bridge started
    after the desktop took focus, or the NVDA-A11Y channel (re)connected later
    than the last focus change.  Windows in the "active" state are searched
    first; the walk is bounded in nodes and depth so a huge tree cannot stall
    the GLib main loop.
    """
    budget = [max(1, max_nodes)]

    def has_state(obj, wanted: str) -> bool:
        return wanted in _states(obj, focused=False)

    def search(obj, depth: int):
        if budget[0] <= 0 or depth > max_depth:
            return None
        budget[0] -= 1
        if has_state(obj, "focused"):
            return obj
        for child in _children(obj):
            found = search(child, depth + 1)
            if found is not None:
                return found
        return None

    windows = []
    for application in _children(desktop):
        windows.extend(_children(application))
    active = [window for window in windows if has_state(window, "active")]
    for window in active + [w for w in windows if w not in active]:
        found = search(window, 0)
        if found is not None:
            return found
    return None


def _snapshot(
    obj,
    *,
    parent_id: str | None,
    child_ids: list[str],
    focused: bool,
    coord_type=None,
) -> dict[str, Any]:
    description = _description(obj)
    text_snapshot = _text_snapshot(obj, focused=focused)
    return {
        "id": object_id(obj),
        "parent_id": parent_id,
        "child_ids": child_ids,
        "name": _name(obj),
        "role": _role_name(obj),
        "description": description,
        "value": _value(obj),
        "actions": action_names(obj),
        **text_snapshot,
        "states": _states(obj, focused=focused),
        "bounds": _bounds(obj, coord_type),
    }


def build_text_update(
    event_type: str,
    source,
    *,
    object_registry: dict[str, object],
):
    """Build a focused text/caret update for an object in the current snapshot."""
    if event_type not in A11Y_TEXT_EVENTS or not _looks_accessible(source):
        return None
    oid = object_id(source)
    if oid not in object_registry:
        return None
    snapshot = _text_snapshot(source, focused=True)
    if not snapshot["text_supported"]:
        return None
    return {
        "object_id": oid,
        "event": "caret" if event_type in {
            "object:text-caret-moved",
            "object:text-selection-changed",
        } else "textChange",
        **snapshot,
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
    target = any_data if event_type == "object:active-descendant-changed" and _looks_accessible(any_data) else source
    if not _looks_accessible(target):
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
        role = _role_name(current)
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
