#!/usr/bin/env python3
"""Observe one existing Linux editor for 1-60 seconds; never send input."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    from diagnostics.x11.live_x11 import Focus, PrivateParser
    from linux_rdaccess_core.cli import graphical_session_env
    from linux_rdaccess_core.routing_observer import APPLICATIONS, observe

    parser = PrivateParser(description=__doc__)
    parser.add_argument("--application", choices=tuple(APPLICATIONS), required=True)
    parser.add_argument("--duration", type=float, default=30)
    try:
        args = parser.parse_args(argv)
        environment = graphical_session_env()
        if not environment.get("DISPLAY") or environment.get("XDG_SESSION_TYPE") == "wayland":
            raise ValueError("Existing X11 graphical session unavailable")
        for key in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "XAUTHORITY",
            "DBUS_SESSION_BUS_ADDRESS",
            "AT_SPI_BUS_ADDRESS",
            "XDG_RUNTIME_DIR",
            "XDG_SESSION_TYPE",
        ):
            if key not in environment:
                os.environ.pop(key, None)
        os.environ.update(environment)
        observe(
            Focus(), args.application, args.duration, lambda result: print(json.dumps(result), flush=True)
        )
    except KeyboardInterrupt:
        print(json.dumps({"observer": "cancelled", "input_sent": False}))
        return 130
    except Exception:
        print(
            json.dumps(
                {
                    "observer": "unavailable",
                    "input_sent": False,
                    "reason": "Check target editor focus, X11/AT-SPI availability and bounded duration",
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
