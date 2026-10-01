"""Decide what (if anything) to say for an AT-SPI event.

Pure Python on purpose: it never imports gi, so it runs in unit tests. "Accessible"
objects are duck-typed: anything with get_name() / get_role_name() (and
get_description() for description changes) works, which is what Atspi.Accessible offers.

Rules:
  * Only the event types in HANDLED are considered. Everything else (bounds-changed,
    text-changed, ...) returns None before any accessible is touched, because every
    get_name() is a synchronous D-Bus round trip.
  * Focus and selection events speak "name, role" and interrupt current speech.
  * An unnamed object is spoken as its role alone on focus (silence after Tab is worse),
    and ignored for every other event.
  * Name and description changes are only spoken for the focused object, otherwise a
    clock label or a window title changing would talk constantly. They queue and do not
    interrupt.
  * Repeats are dropped if the same accessible (same object, name and role) was spoken less
    than `dedupe_seconds` ago. GTK often emits focus, selected and active-descendant for one
    keypress. Two different controls that merely share a label are never merged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

FOCUS = "object:state-changed:focused"
SELECTED = "object:state-changed:selected"
ACTIVE_DESCENDANT = "object:active-descendant-changed"
NAME_CHANGED = "object:property-change:accessible-name"
DESCRIPTION_CHANGED = "object:property-change:accessible-description"
WINDOW_ACTIVATE = "window:activate"

HANDLED = frozenset(
    {FOCUS, SELECTED, ACTIVE_DESCENDANT, NAME_CHANGED, DESCRIPTION_CHANGED, WINDOW_ACTIVATE}
)
FOCUS_IMPLIED_ROLES = frozenset({"combo box"})
_NEEDS_DETAIL1 = frozenset({FOCUS, SELECTED})  # detail1 == 0 means "lost", not "gained"


@dataclass(frozen=True)
class Announcement:
    text: str
    interrupt: bool


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def _identity(obj) -> object:
    """Stable key for "the same accessible".

    libatspi hands back the same GObject for the same accessible while it is alive, and
    hash() of the PyGObject wrapper follows that GObject (id() of the wrapper does not:
    it differs on every event). Keying the dedupe on name+role alone silently dropped the
    second of two identical controls ("Browse" next to "Browse", two unlabelled text fields)
    whenever they were tabbed through faster than the dedupe window.
    """
    try:
        return hash(obj)
    except TypeError:
        return id(obj)


class Announcer:
    def __init__(
        self,
        *,
        is_focused: Callable[[object], bool] = lambda obj: True,
        dedupe_seconds: float = 0.75,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._is_focused = is_focused
        self._dedupe_seconds = dedupe_seconds
        self._clock = clock
        self._recent: dict[tuple, float] = {}

    def handle(
        self, event_type: str, detail1: int, source, any_data=None
    ) -> Optional[Announcement]:
        if event_type not in HANDLED:
            return None
        if event_type in _NEEDS_DETAIL1 and not detail1:
            return None

        if event_type == ACTIVE_DESCENDANT:
            # source is the container; any_data is the newly active child.
            if not hasattr(any_data, "get_name"):
                return None  # cleared, or not an accessible: announcing the container would be wrong
            return self._describe(any_data, interrupt=True, allow_role_only=True)

        if event_type == FOCUS:
            return self._describe(source, interrupt=True, allow_role_only=True)
        if event_type == SELECTED:
            return self._describe(source, interrupt=True, suffix="selected")
        if event_type == WINDOW_ACTIVATE:
            return self._describe(source, interrupt=True)
        if event_type == NAME_CHANGED:
            if not self._counts_as_focused(source):
                return None
            return self._describe(source, interrupt=False)
        # DESCRIPTION_CHANGED
        if not self._counts_as_focused(source):
            return None
        description = any_data if isinstance(any_data, str) else source.get_description()
        description = _clean(description)
        if not description or self._is_repeat(("description", description)):
            return None
        return Announcement(description, interrupt=False)

    def _counts_as_focused(self, obj) -> bool:
        if self._is_focused(obj):
            return True
        # GTK3 keeps keyboard focus inside a combo box but never reports the FOCUSED state
        # for it, so its value changes (the Down arrow) were silent. Only the user changes a
        # combo box's value in practice, so treat it as focused.
        return _clean(obj.get_role_name()) in FOCUS_IMPLIED_ROLES

    def _describe(
        self, obj, *, interrupt: bool, allow_role_only: bool = False, suffix: str = ""
    ) -> Optional[Announcement]:
        name = _clean(obj.get_name())
        role = _clean(obj.get_role_name())
        if not name and not (allow_role_only and role):
            return None
        if self._is_repeat(("object", _identity(obj), name, role)):
            return None
        parts = [p for p in (name, role, suffix) if p]
        return Announcement(", ".join(parts), interrupt)

    def _is_repeat(self, key: tuple) -> bool:
        now = self._clock()
        last = self._recent.get(key)
        if last is not None and now - last < self._dedupe_seconds:
            return True  # keep the original timestamp so a steady stream still gets through
        self._recent[key] = now
        if len(self._recent) > 64:  # keep the table tiny
            cutoff = now - self._dedupe_seconds
            self._recent = {k: t for k, t in self._recent.items() if t >= cutoff}
        return False
