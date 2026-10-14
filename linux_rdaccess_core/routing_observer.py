"""Bounded read-only caret observation; no input, text capture or NVDA claims."""

from __future__ import annotations

import math
import time

APPLICATIONS = {
    "gtk-fixture": ("accessibility_smoke_app.py",),
    "firefox": ("firefox",),
    "mousepad": ("mousepad",),
    "terminal": ("gnome-terminal-server", "xfce4-terminal"),
}
EVENTS = ("object:state-changed:focused", "object:text-caret-moved")
MAX_EVENTS = 64


def caret_position(snapshot) -> int | None:
    """Read only the numeric caret; do not query password providers or text."""
    if snapshot is None or snapshot["role"] in ("password-text", "password text"):
        return None
    obj = snapshot["object"]
    try:
        iface = obj.get_text_iface()
        offset = iface.get_caret_offset() if iface is not None else None
        return offset if type(offset) is int and offset >= 0 else None
    except Exception:
        return None


class RoutingObservation:
    def __init__(self, before, *, clock=time.monotonic):
        self.before = before
        self.clock = clock
        self.started = clock()
        self.before_caret = caret_position(before)
        self.events = []
        self.focus_changed = False
        self.dropped_events = 0

    def event(self, event, *_args):
        try:
            kind = event.type
            if kind not in EVENTS:
                return
            same = event.source == self.before["object"]
            if kind == EVENTS[0]:
                if not event.detail1 or same:
                    return
                self.focus_changed = True
                record = {"type": "focus-changed", "same_initial_focus": False}
            else:
                # Never interpret caret events from a new or unrelated object.
                if not same or self.focus_changed or self.before_caret is None:
                    return
                offset = event.detail1
                if type(offset) is not int or offset < 0:
                    return
                record = {"type": "caret-moved", "same_initial_focus": True, "caret_offset": offset}
            if len(self.events) >= MAX_EVENTS:
                self.dropped_events += 1
                return
            record["elapsed_ms"] = round((self.clock() - self.started) * 1000, 1)
            self.events.append(record)
        except Exception:
            # Provider errors must never leak application text into diagnostics.
            return

    def finish(self, after) -> dict:
        try:
            same = after is not None and after["object"] == self.before["object"]
        except Exception:
            same = False
        after_caret = caret_position(after) if same and not self.focus_changed else None
        return {
            "kind": "linux-atspi-caret-observation",
            "source": "linux-atspi",
            "elapsed_ms": round((self.clock() - self.started) * 1000, 1),
            "role": self.before["role"],
            "before_caret": self.before_caret,
            "after_caret": after_caret,
            "same_initial_focus": same,
            "focus_changed_during_observation": self.focus_changed,
            "events": self.events,
            "dropped_events": self.dropped_events,
            "limitations": "Read-only Linux evidence; input origin, NVDA output and physical braille are unverified",
        }


def observe(focus, application: str, duration: float, emit) -> dict:
    """Reuse the existing focus probe in its selected graphical session."""
    if application not in APPLICATIONS or not math.isfinite(duration) or not 1 <= duration <= 60:
        raise ValueError("Invalid observer application or duration")
    before = focus.read()
    if before is None:
        raise ValueError("Linux focus unavailable")
    try:
        actual_app = before["object"].get_application().get_name().lower()
    except Exception:
        raise ValueError("Linux application unavailable") from None
    if actual_app not in APPLICATIONS[application]:
        raise ValueError("Focused application does not match requested observer target")
    observation = RoutingObservation(before)
    if observation.before_caret is None:
        raise ValueError("Focused object has no readable text caret")
    loop = focus.glib.MainLoop()
    listener = focus.atspi.EventListener.new(observation.event)
    registered = []
    timer = None
    try:
        for kind in EVENTS:
            if listener.register(kind) is False:
                raise ValueError("AT-SPI event registration unavailable")
            registered.append(kind)
        # A millisecond timer avoids GLib's coalesced seconds extending the window.
        timer = focus.glib.timeout_add(round(duration * 1000), lambda: (loop.quit(), False)[1])
        if not timer:
            raise ValueError("Observer timer unavailable")
        emit(
            {
                "observer": "ready",
                "source": "linux-atspi",
                "application": application,
                "duration_seconds": duration,
                "role": before["role"],
                "before_caret": observation.before_caret,
                "input_sent": False,
            }
        )
        loop.run()
    finally:
        # Do not remove a timeout that already ran and is no longer registered.
        if timer is not None and focus.glib.MainContext.default().find_source_by_id(timer) is not None:
            focus.glib.source_remove(timer)
        for kind in registered:
            listener.deregister(kind)
    result = observation.finish(focus.read())
    result["application"] = application
    emit(result)
    return result
