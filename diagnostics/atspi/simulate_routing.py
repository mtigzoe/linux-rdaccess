#!/usr/bin/env python3
"""Preview or simulate one Linux caret route; bypasses NVDA and physical braille."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from linux_rdaccess_core.accessibility.a11y_model import MAX_FOCUS_TEXT_CHARS, set_caret_offset
from linux_rdaccess_core.routing_observer import APPLICATIONS, caret_position, observe

TARGETS = ("mousepad", "gtk-fixture")
LIMITATIONS = (
    "Direct shared Linux caret setter only; bypasses NVDA, Remote Access, Orca's "
    "controller and semantic object/session validation. Does not test temporary-message "
    "dismissal, cell translation or physical braille."
)


def inspect_target(focus, application):
    """Inspect the current editable target, without exporting its text or labels."""
    if application not in TARGETS:
        raise ValueError("Unsupported simulator application")
    snapshot = focus.read()
    if (snapshot is None or snapshot["role"] not in ("text", "entry")
            or not {"focused", "editable"}.issubset(snapshot["states"])):
        raise ValueError("Focus must be an editable non-password text field")
    obj = snapshot["object"]
    app = obj.get_application()
    if app.get_name().lower() not in APPLICATIONS[application]:
        raise ValueError("Focused application does not match the requested target")
    pid = app.get_process_id()
    text = obj.get_text_iface()
    count, selections = text.get_character_count(), text.get_n_selections()
    caret = caret_position(snapshot)
    if (type(pid) is not int or pid <= 0 or type(count) is not int or count < 0
            or type(selections) is not int or selections < 0
            or caret is None or caret > count):
        raise ValueError("Numeric target state is unavailable")
    return snapshot, {"process_id": pid, "character_count": count,
                      "caret": caret, "selection_count": selections}


def simulate(focus, application, offset, *, apply=False, expected_pid=None,
             expected_caret=None, expected_count=None, duration=2, emit=lambda _item: None):
    """One explicit write at most, with an observer and fresh target guards."""
    if type(offset) is not int or not 0 <= offset <= MAX_FOCUS_TEXT_CHARS:
        raise ValueError("Invalid character offset")
    if not math.isfinite(duration) or not 1 <= duration <= 10:
        raise ValueError("Observation duration must be 1-10 seconds")
    expected = {"process_id": expected_pid, "caret": expected_caret,
                "character_count": expected_count}
    if apply and any(type(value) is not int or value < (1 if key == "process_id" else 0)
                     for key, value in expected.items()):
        raise ValueError("Apply requires the preview's PID, caret and character count")
    before, state = inspect_target(focus, application)
    if offset > state["character_count"]:
        raise ValueError("Requested offset is outside the document")
    report = {
        "kind": "linux-atspi-routing-simulation", "source": "simulated-atspi",
        "operation": "apply" if apply else "preview", "application": application,
        "target": state, "requested_character_offset": offset,
        "caret_write_attempted": False, "keyboard_input_sent": False,
        "nvda_output": "unverified", "physical_braille": "unverified",
        "limitations": LIMITATIONS,
    }
    if not apply:
        return report
    if any(state[key] != value for key, value in expected.items()) or state["selection_count"]:
        raise ValueError("Preview state changed or text is selected; preview again")
    reasons = []

    def guard():
        current, now = inspect_target(focus, application)
        if current["object"] != before["object"] or now != state:
            raise ValueError("Target changed before the caret write")
        report["caret_write_attempted"] = True

    def record(item):
        if item.get("observer") != "ready":
            return
        # observe() has registered both listeners and its bounded timer already.
        emit(dict(item, stimulus="direct-atspi-simulation"))
        report["setter_returned"] = set_caret_offset(
            before["object"], offset, before_action=guard,
            diagnostic=lambda reason: reasons.append(reason.value),
        )

    observation = observe(focus, application, duration, record)
    report["setter_reasons"] = reasons
    report["observation"] = observation
    report["caret_readback_matches"] = bool(
        report.get("setter_returned") and observation["same_initial_focus"]
        and not observation["focus_changed_during_observation"]
        and observation["after_caret"] == offset
        and observation["dropped_events"] == 0
    )
    return report


def main(argv=None):
    from diagnostics.x11.live_x11 import Focus, PrivateParser
    from linux_rdaccess_core.cli import graphical_session_env

    try:
        parser = PrivateParser(description=__doc__)
        parser.add_argument("--application", choices=TARGETS, default="mousepad")
        parser.add_argument("--offset", type=int, required=True,
                            help="Zero-based character offset, not a braille cell")
        parser.add_argument("--apply", action="store_true", help="Move the caret once")
        parser.add_argument("--expect-pid", type=int)
        parser.add_argument("--expect-caret", type=int)
        parser.add_argument("--expect-count", type=int)
        parser.add_argument("--duration", type=float, default=2)
        args = parser.parse_args(argv)
        environment = graphical_session_env()
        if not environment.get("DISPLAY") or environment.get("XDG_SESSION_TYPE") == "wayland":
            raise ValueError("Existing X11 session unavailable")
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
                    "AT_SPI_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE"):
            if key not in environment:
                os.environ.pop(key, None)
        os.environ.update(environment)
        result = simulate(
            Focus(), args.application, args.offset, apply=args.apply,
            expected_pid=args.expect_pid, expected_caret=args.expect_caret,
            expected_count=args.expect_count, duration=args.duration,
            emit=lambda item: print(json.dumps(item), flush=True),
        )
        print(json.dumps(result), flush=True)
        return 0 if not args.apply or result["caret_readback_matches"] else 1
    except KeyboardInterrupt:
        # A write may already have happened. Do not claim input_sent=False.
        print(json.dumps({"simulator": "cancelled", "caret_write_outcome": "unknown"}))
        return 130
    except Exception:
        # Never serialize a provider exception, command line, object name or text.
        print(json.dumps({"simulator": "unavailable_or_refused",
                          "caret_write_outcome": "unknown",
                          "reason": "Check editable target, preview guards, offset and X11/AT-SPI"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
