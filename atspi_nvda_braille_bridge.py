#!/usr/bin/env python3
"""Prototype Linux AT-SPI -> NVDA speech bridge for an xrdp session.

Run inside the xrdp session. Needs NVDA + rdAccess on the Windows client.

    ./run_braille_bridge.sh            # speech + braille through NVDA
    ./run_braille_bridge.sh --debug    # also log handled events and DVC detail

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
import louis

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

from announcer import HANDLED, Announcer
from a11y_link import A11Y_CHANNEL, NvdaA11yLink
from a11y_model import A11Y_TEXT_EVENTS, build_focus_payload, build_text_update, perform_action
from braille_link import NvdaBrailleLink
from rdaccess_dvc import CHANNEL, DvcChannel, NvdaSpeechLink, load_xrdpapi

log = logging.getLogger("bridge")

POLL_MS = 50
READY_TEXT = "Linux accessibility bridge ready"
# Broad on purpose, same as atspi_nvda_bridge.py. Narrow per-event registrations were found to be
# unreliable in the xrdp session; _on_event() rejects everything outside HANDLED with a string
# compare, before any D-Bus call, so the extra callbacks are cheap.
LISTEN_TO = ("object", "window")
BRAILLE_CHANNEL = "NVDA-BRAILLE"
BRAILLE_TABLE = ["en-ueb-g2.ctb"]


class DryRunLink:
    """Stands in for NvdaSpeechLink so filtering can be tuned without NVDA."""

    ready = True

    def poll(self) -> None:
        pass

    def speak(self, text: str, interrupt: bool = False) -> bool:
        print(f"[speak{' !' if interrupt else ''}] {text}", flush=True)
        return True

    def close(self) -> None:
        pass


def is_focused(obj: Atspi.Accessible) -> bool:
    return obj.get_state_set().contains(Atspi.StateType.FOCUSED)


def text_to_braille_cells(text: str, width: int) -> list[int]:
    """Translate text to 8-dot cell bytes using the same UEB table as NVDA."""
    translated = louis.translateString(BRAILLE_TABLE, text, mode=louis.dotsIO)
    cells = [ord(ch) & 0xFF for ch in translated]
    width = max(1, int(width))
    return (cells[:width] + [0] * width)[:width]


class Bridge:
    def __init__(self, link, *, braille_link=None, a11y_link=None, interrupt: bool = True):
        self.link = link
        self.braille_link = braille_link
        self.a11y_link = a11y_link
        self.interrupt = interrupt
        self.announcer = Announcer(is_focused=is_focused)
        self.listener = Atspi.EventListener.new(self._on_event)
        self._registered: list[str] = []
        self._a11y_objects: dict[str, object] = {}

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
                log.debug("deregister %s: %s", event_type, exc)
        self._registered.clear()

    def _on_event(self, event: Atspi.Event, _user_data=None) -> None:
        # Semantic text updates are deliberately separate from the v1 announcer:
        # they refresh NVDA's remote object without speaking the whole control
        # again on every caret move or edit.
        is_text_event = event.type in A11Y_TEXT_EVENTS
        if event.type not in HANDLED and not is_text_event:
            return
        try:
            any_data = getattr(event, "any_data", None)
            if is_text_event:
                if self.a11y_link is not None and is_focused(event.source):
                    update = build_text_update(
                        event.type,
                        event.source,
                        object_registry=self._a11y_objects,
                    )
                    if update is not None:
                        self.a11y_link.send_text_update(**update)
                return

            if self.a11y_link is not None:
                payload = build_focus_payload(
                    event.type,
                    event.detail1,
                    event.source,
                    any_data,
                    coord_type=Atspi.CoordType.SCREEN,
                    object_registry=self._a11y_objects,
                )
                if payload is not None:
                    self.a11y_link.send_focus(**payload)
            announcement = self.announcer.handle(
                event.type, event.detail1, event.source, any_data
            )
        except GLib.Error as exc:
            # The application usually exited between the event and our query.
            log.debug("%s: source went away (%s)", event.type, exc)
            return
        except Exception:
            log.exception("failed to handle %s", event.type)
            return
        if announcement is None:
            return
        log.debug("%s -> %r", event.type, announcement.text)
        self.link.speak(announcement.text, interrupt=announcement.interrupt and self.interrupt)
        if self.braille_link is not None:
            cells = text_to_braille_cells(announcement.text, self.braille_link.num_cells)
            self.braille_link.display(cells)

    def perform_remote_action(self, object_id: str, action_index: int) -> None:
        obj = self._a11y_objects.get(object_id)
        if obj is None:
            log.warning("remote A11Y action target %s is not in the current snapshot", object_id)
            return
        if perform_action(obj, action_index):
            log.debug("performed remote A11Y action %d on %s", action_index, object_id)
        else:
            log.warning("remote A11Y action %d failed for %s", action_index, object_id)

    def say_ready(self) -> None:
        self.link.speak(READY_TEXT)
        if self.braille_link is not None:
            self.braille_link.display(
                text_to_braille_cells(READY_TEXT, self.braille_link.num_cells)
            )


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
    parser.add_argument("--dry-run", action="store_true", help="print speech instead of sending it to NVDA")
    parser.add_argument("--no-interrupt", action="store_true", help="never send 'cancel' before speech")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    bridge: Bridge  # assigned below; the on_ready lambda only runs later, from poll()
    braille_link = None
    a11y_link = None
    if args.dry_run:
        link = DryRunLink()
    else:
        lib = load_xrdpapi()
        link = NvdaSpeechLink(
            lambda: DvcChannel(lib, CHANNEL, attempts=1),
            on_ready=lambda: bridge.say_ready(),
        )
        braille_link = NvdaBrailleLink(
            lambda: DvcChannel(lib, BRAILLE_CHANNEL, attempts=1),
        )
        a11y_link = NvdaA11yLink(
            lambda: DvcChannel(lib, A11Y_CHANNEL, attempts=1),
            on_action=lambda object_id, action_index: bridge.perform_remote_action(
                object_id,
                action_index,
            ),
        )
    bridge = Bridge(
        link,
        braille_link=braille_link,
        a11y_link=a11y_link,
        interrupt=not args.no_interrupt,
    )

    loop = GLib.MainLoop()
    install_signal_handlers(loop)

    def tick() -> bool:
        link.poll()
        if braille_link is not None:
            braille_link.poll()
        if a11y_link is not None:
            a11y_link.poll()
        return GLib.SOURCE_CONTINUE

    try:
        bridge.start()
        if args.dry_run:
            bridge.say_ready()
        GLib.timeout_add(POLL_MS, tick)
        loop.run()
        return 0
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    finally:
        bridge.stop()
        link.close()
        if braille_link is not None:
            braille_link.close()
        if a11y_link is not None:
            a11y_link.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # Ctrl+C before the main loop started (e.g. while loading libxrdpapi)
        sys.exit(130)
