#!/usr/bin/env python3
"""Prototype Linux AT-SPI -> NVDA speech bridge for an xrdp session."""

from __future__ import annotations

import argparse
import signal
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

from rdaccess_speak_test import (
    CHANNEL,
    PROTOCOL_VERSION,
    DvcChannel,
    Receiver,
    load_xrdpapi,
    pump,
    send_json,
)


class AtspiSpeechBridge:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.channel = DvcChannel(load_xrdpapi(), CHANNEL)
        self.receiver = Receiver(debug=debug)
        self.last_utterance = ""
        self.last_spoken_at = 0.0
        self.listener = Atspi.EventListener.new(self._on_event)
    def connect(self) -> None:
        pump(self.channel, self.receiver, 15.0, until=lambda: self.receiver.xon)
        if not self.receiver.xon:
            raise RuntimeError("RDAccess client connected, but no XON was received")
        send_json(
            self.channel,
            "protocol_version",
            version=PROTOCOL_VERSION,
            channel=CHANNEL,
        )
        pump(self.channel, self.receiver, 0.5)
        print("[ok] NVDA speech channel ready")

    def _speak(self, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            return
        now = time.monotonic()
        if text == self.last_utterance and now - self.last_spoken_at < 0.75:
            return
        self.last_utterance = text
        self.last_spoken_at = now
        send_json(self.channel, "speak", sequence=[text])
        print(f"[speak] {text}")

    def _on_event(self, event: Atspi.Event, _user_data=None) -> None:
        interesting = {
            "object:state-changed:focused",
            "object:active-descendant-changed",
            "object:property-change:accessible-name",
            "object:property-change:accessible-description",
            "window:activate",
        }
        if event.type not in interesting:
            return
        if event.type == "object:state-changed:focused" and not event.detail1:
            return
        try:
            source = event.source
            if event.type == "object:active-descendant-changed":
                candidate = getattr(event, "any_data", None)
                if candidate is not None and hasattr(candidate, "get_name"):
                    source = candidate
            name = source.get_name() or ""
            role = source.get_role_name() or ""
            text = name if not role else f"{name}, {role}" if name else role
            if self.debug:
                print(f"[event] {event.type}: name={name!r} role={role!r}")
            self._speak(text)
        except Exception as exc:
            print(f"[warn] failed to handle AT-SPI event: {exc}", file=sys.stderr)

    def run(self) -> None:
        self.connect()
        self.listener.register("object")
        self.listener.register("window")
        self._speak("Linux accessibility bridge ready")
        print("[ok] listening for AT-SPI object and window events")
        Atspi.event_main()

    def close(self) -> None:
        try:
            self.listener.deregister("object")
            self.listener.deregister("window")
        finally:
            self.channel.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    bridge = AtspiSpeechBridge(debug=args.debug)

    def stop(_signum, _frame):
        Atspi.event_quit()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        bridge.run()
        return 0
    finally:
        bridge.close()


if __name__ == "__main__":
    raise SystemExit(main())
