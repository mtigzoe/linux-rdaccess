#!/usr/bin/env python3
"""Correlate Tab key presses seen by X with AT-SPI focus events (is Tab reaching Linux? did focus move?).

Run inside the xrdp session, then press Tab in a Linux application over the Remote Desktop window.
For every Tab it prints one line:

    Tab #3 -> focus event after 0.04s: object:state-changed:focused (label redacted)
    Tab #4 -> NO AT-SPI focus event within 0.6s

Reading the result:
  * You pressed Tab but no "Tab #n" line appears: the key never reached the X session (the Windows
    client or something in front of the Remote Desktop window kept it).
  * "Tab #n" appears but "NO AT-SPI focus event": X got the key, but the application emitted nothing.
    Either focus did not move (the control swallows Tab: terminals, text editors) or the toolkit does
    not report focus for that widget (GTK3 combo boxes).

    DISPLAY=:10 python3 diagnostics/x11/tab_trace.py [--seconds 60] [--keycode 23] [--window 0.6]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Iterable, Iterator, Optional

# What counts as "AT-SPI told us focus moved": the event types the bridge announces for navigation.
FOCUS_EVENTS = ("object:state-changed:focused", "object:state-changed:selected")
ALWAYS_EVENTS = ("object:active-descendant-changed", "window:activate")


def parse_xi2_key_presses(lines: Iterable[str]) -> Iterator[int]:
    """Yield the keycode of each RawKeyPress in `xinput test-xi2 --root` output."""
    in_press = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("EVENT type"):
            in_press = "RawKeyPress" in stripped
        elif in_press and stripped.startswith("detail:"):
            in_press = False
            try:
                yield int(stripped.split(":", 1)[1])
            except ValueError:
                continue


def tab_keycodes_from_xmodmap(text: str) -> set[int]:
    """Keycodes whose first keysyms include Tab / ISO_Left_Tab (xmodmap -pke output)."""
    codes = set()
    for match in re.finditer(r"keycode\s+(\d+)\s*=\s*(.*)", text):
        if {"Tab", "ISO_Left_Tab"} & set(match.group(2).split()[:2]):
            codes.add(int(match.group(1)))
    return codes


class TabCorrelator:
    """Pure logic: match each Tab press to the first focus event that follows it."""

    def __init__(self, window: float = 0.6, clock: Callable[[], float] = time.monotonic):
        self.window = window
        self._clock = clock
        self._pending: list[tuple[int, float]] = []
        self.count = 0
        self.matched = 0
        self.unmatched = 0

    def tab_pressed(self) -> int:
        self.count += 1
        self._pending.append((self.count, self._clock()))
        return self.count

    def focus_event(self, description: str) -> Optional[str]:
        if not self._pending:
            return None
        number, pressed_at = self._pending.pop(0)
        self.matched += 1
        return f"Tab #{number} -> focus event after {self._clock() - pressed_at:.2f}s: {description}"

    def expire(self) -> list[str]:
        now = self._clock()
        lines = []
        while self._pending and now - self._pending[0][1] > self.window:
            number, _ = self._pending.pop(0)
            self.unmatched += 1
            lines.append(f"Tab #{number} -> NO AT-SPI focus event within {self.window:.1f}s")
        return lines

    def summary(self) -> str:
        return (
            f"{self.count} Tab press(es) reached X; {self.matched} produced an AT-SPI focus event, "
            f"{self.unmatched} did not."
        )


def _find_tab_keycodes(explicit: Optional[int]) -> set[int]:
    if explicit is not None:
        return {explicit}
    try:
        out = subprocess.run(["xmodmap", "-pke"], capture_output=True, text=True, timeout=5).stdout
        codes = tab_keycodes_from_xmodmap(out)
        if codes:
            return codes
    except (OSError, subprocess.SubprocessError):
        pass
    return {23}  # evdev/xorgxrdp default


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--keycode", type=int, help="X keycode of Tab (default: auto-detect, else 23)")
    parser.add_argument("--window", type=float, default=0.6, help="seconds to wait for a focus event")
    args = parser.parse_args()

    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, GLib

    tab_codes = _find_tab_keycodes(args.keycode)
    correlator = TabCorrelator(window=args.window)
    lock = threading.Lock()

    def reader(proc: subprocess.Popen) -> None:
        for code in parse_xi2_key_presses(proc.stdout):
            if code in tab_codes:
                with lock:
                    n = correlator.tab_pressed()
                print(f"[X] Tab key press #{n} reached the X session (keycode {code})", flush=True)

    try:
        proc = subprocess.Popen(
            ["xinput", "test-xi2", "--root"], stdout=subprocess.PIPE, text=True, bufsize=1
        )
    except OSError as exc:
        print("cannot run xinput; install the xinput package", file=sys.stderr)
        return 1
    threading.Thread(target=reader, args=(proc,), daemon=True).start()

    def on_event(event, _data=None):
        if event.type not in FOCUS_EVENTS + ALWAYS_EVENTS:
            return
        if event.type in FOCUS_EVENTS and not event.detail1:
            return
        try:
            target = event.source
            if event.type == "object:active-descendant-changed" and hasattr(event.any_data, "get_name"):
                target = event.any_data
            description = f"{event.type} (label redacted)"
        except GLib.Error as exc:
            description = f"{event.type} <source unavailable>"
        with lock:
            line = correlator.focus_event(description)
        if line:
            print(line, flush=True)

    listener = Atspi.EventListener.new(on_event)
    for event_type in ("object", "window"):
        print(f"register {event_type!r}: {listener.register(event_type)}", flush=True)

    def tick() -> bool:
        with lock:
            lines = correlator.expire()
        for line in lines:
            print(line, flush=True)
        return True

    loop = GLib.MainLoop()
    GLib.timeout_add(100, tick)
    GLib.timeout_add_seconds(args.seconds, lambda: (loop.quit(), False)[1])
    import signal

    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, lambda: (loop.quit(), False)[1])
    print(f"watching for {args.seconds}s; press Tab in a Linux application (Ctrl+C to stop)", flush=True)
    loop.run()

    proc.terminate()
    with lock:
        correlator.expire()
        print("\n" + correlator.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
