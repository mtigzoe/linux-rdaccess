#!/usr/bin/env python3
"""List the applications visible on the AT-SPI bus (is accessibility working in this session?).

    python3 diagnostics/atspi_probe.py            # all applications
    python3 diagnostics/atspi_probe.py --limit 5
"""

import argparse

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=0, help="show at most N applications (default: all)")
    args = parser.parse_args()

    desktop = Atspi.get_desktop(0)
    count = desktop.get_child_count()
    print(f"AT-SPI import OK; applications: {count}")
    for i in range(min(count, args.limit) if args.limit else count):
        try:
            print(i, desktop.get_child_at_index(i).get_name())
        except Exception as exc:  # an app can vanish between the count and the query
            print(i, "<error>", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
