#!/usr/bin/env python3
"""Prototype Linux AT-SPI -> NVDA speech bridge for an xrdp session.

Run inside the xrdp session. Needs NVDA + rdAccess on the Windows client.

    python3 atspi_nvda_bridge.py            # speak through NVDA
    python3 atspi_nvda_bridge.py --dry-run  # no NVDA: print speech state only
    python3 atspi_nvda_bridge.py --debug    # log event state without text

Architecture: one GLib main loop does everything, on one thread.
  * AT-SPI events arrive as GLib callbacks (Atspi dispatches on the default context).
  * A 50 ms GLib timer calls NvdaSpeechLink.poll() to drain the DVC, honour
    XON/XOFF, re-handshake after a reconnect and reopen a lost channel.
  * SIGINT/SIGTERM use GLib.unix_signal_add so they also work while the loop is idle.
    (A Python signal.signal handler does not run inside Atspi.event_main(): the
    interpreter never regains control until some event callback happens to fire.)
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

from announcer import HANDLED, Announcer
from rdaccess_dvc import CHANNEL, DvcChannel, NvdaSpeechLink, load_xrdpapi

log = logging.getLogger("bridge")

POLL_MS = 50
READY_TEXT = "Linux accessibility bridge ready"
LISTEN_TO = ("object", "window")  # broad on purpose: narrow focus-only listeners were unreliable


class DryRunLink:
    """Stands in for NvdaSpeechLink so filtering can be tuned without NVDA."""

    ready = True

    def poll(self) -> None:
        pass

    def speak(self, text: str, interrupt: bool = False) -> bool:
        print(f"[speak{' !' if interrupt else ''}] text redacted", flush=True)
        return True

    def close(self) -> None:
        pass


def is_focused(obj: Atspi.Accessible) -> bool:
    return obj.get_state_set().contains(Atspi.StateType.FOCUSED)


class Bridge:
    def __init__(self, link, *, interrupt: bool = True):
        self.link = link
        self.interrupt = interrupt
        self.announcer = Announcer(is_focused=is_focused)
        self.listener = Atspi.EventListener.new(self._on_event)
        self._registered: list[str] = []

    def start(self) -> None:
        for event_type in LISTEN_TO:
            if not self.listener.register(event_type):
                raise RuntimeError(f"AT-SPI refused to register a listener for {event_type!r}")
            self._registered.append(event_type)
        log.info("listening for AT-SPI %s events", " and ".join(self._registered))

    def stop(self) -> None:
        for event_type in self._registered:
            try:
                self.listener.deregister(event_type)
            except GLib.Error as exc:
                log.debug("listener deregistration failed")
        self._registered.clear()

    def _on_event(self, event: Atspi.Event, _user_data=None) -> None:
        # Cheap string check first: anything not in HANDLED must cost no D-Bus calls.
        if event.type not in HANDLED:
            return
        try:
            announcement = self.announcer.handle(
                event.type, event.detail1, event.source, getattr(event, "any_data", None)
            )
        except GLib.Error as exc:
            # The application usually exited between the event and our query.
            log.debug("event source unavailable")
            return
        except Exception:
            log.error("failed to handle accessibility event")
            return
        if announcement is None:
            return
        log.debug("accessibility announcement handled")
        self.link.speak(announcement.text, interrupt=announcement.interrupt and self.interrupt)

    def say_ready(self) -> None:
        self.link.speak(READY_TEXT)


def install_signal_handlers(loop: GLib.MainLoop) -> None:
    """Quit `loop` on SIGINT/SIGTERM, even while the loop is idle."""

    def on_signal(signum: int) -> bool:
        log.info("received %s, shutting down", signal.Signals(signum).name)
        loop.quit()
        return GLib.SOURCE_REMOVE

    for signum in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, on_signal, signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--debug", action="store_true", help="log every handled event and DVC detail")
    parser.add_argument("--dry-run", action="store_true", help="print speech state without text instead of sending it to NVDA")
    parser.add_argument("--no-interrupt", action="store_true", help="never send 'cancel' before speech")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    bridge: Bridge  # assigned below; the on_ready lambda only runs later, from poll()
    if args.dry_run:
        link = DryRunLink()
    else:
        lib = load_xrdpapi()
        link = NvdaSpeechLink(
            lambda: DvcChannel(lib, CHANNEL, attempts=1),
            on_ready=lambda: bridge.say_ready(),
        )
    bridge = Bridge(link, interrupt=not args.no_interrupt)

    loop = GLib.MainLoop()
    install_signal_handlers(loop)

    def tick() -> bool:
        link.poll()
        return GLib.SOURCE_CONTINUE

    try:
        bridge.start()
        if args.dry_run:
            bridge.say_ready()
        GLib.timeout_add(POLL_MS, tick)
        loop.run()
        return 0
    except RuntimeError as exc:
        log.error("accessibility bridge failed")
        return 1
    finally:
        bridge.stop()
        link.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # Ctrl+C before the main loop started (e.g. while loading libxrdpapi)
        sys.exit(130)
