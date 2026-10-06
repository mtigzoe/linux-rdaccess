#!/usr/bin/env python3
"""Watch AT-SPI events and summarise which types arrive (for tuning the bridge's filter).

Registers broad listeners, like the bridge does, and reports whether each registration
succeeded. Noisy geometry events are counted but not printed unless --all is given.

    python3 diagnostics/atspi_event_probe.py                 # 12 seconds, object + window
    python3 diagnostics/atspi_event_probe.py --seconds 30 --all
    python3 diagnostics/atspi_event_probe.py --types object:state-changed:focused window:activate
"""

import argparse
import collections
import signal

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

NOISY = ("object:bounds-changed", "object:text-changed", "object:text-caret-moved")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument("--types", nargs="+", default=["object", "window"])
    parser.add_argument("--all", action="store_true", help="also print noisy events")
    args = parser.parse_args()

    counts: collections.Counter = collections.Counter()

    def on_event(event, _data=None):
        counts[event.type] += 1
        if not args.all and event.type.startswith(NOISY):
            return
        try:
            src = event.source
            print(f"{event.type} detail1={event.detail1} (label redacted)", flush=True)
        except GLib.Error as exc:  # application went away
            print(f"{event.type} <source unavailable>", flush=True)

    listener = Atspi.EventListener.new(on_event)
    for event_type in args.types:
        print(f"register {event_type!r}: {listener.register(event_type)}", flush=True)

    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(args.seconds, lambda: (loop.quit(), False)[1])
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, lambda: (loop.quit(), False)[1])
    print(f"watching for {args.seconds}s (Ctrl+C to stop early)", flush=True)
    loop.run()

    for event_type in args.types:
        listener.deregister(event_type)
    print("\nevent counts:")
    for event_type, n in counts.most_common():
        print(f"{n:6d}  {event_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
