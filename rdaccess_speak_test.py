#!/usr/bin/env python3
"""Smoke test: make NVDA on a Windows RDP client speak text sent from an xrdp session.

Run this INSIDE the xrdp session (same user, DISPLAY set), e.g. in a terminal.
Requires on the Windows client: NVDA with the rdAccess add-on, client side enabled
for RDP, and mstsc started after rdAccess registered rd_pipe.dll.

Usage:
    python3 rdaccess_speak_test.py "Hello from Linux"
    XRDPAPI_LIB=/path/to/libxrdpapi.so python3 rdaccess_speak_test.py --debug

The transport and protocol code lives in rdaccess_dvc.py (shared with the bridge).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from rdaccess_dvc import (
    CHANNEL,
    PROTOCOL_VERSION,
    DvcChannel,
    Receiver,
    load_xrdpapi,
    pump,
    send_json,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="Hello from Linux over xrdp")
    ap.add_argument("--debug", action="store_true", help="hex-dump raw received bytes")
    ap.add_argument("--xon-timeout", type=float, default=15.0)
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO, format="[%(levelname)s] %(message)s"
    )

    if not os.environ.get("DISPLAY"):
        sys.exit("DISPLAY is not set. Run this inside the xrdp session.")

    lib = load_xrdpapi()
    ch = DvcChannel(lib, CHANNEL)
    rx = Receiver()
    try:
        # 1. Wait for rd_pipe's XON (NVDA connected to the client-side pipe).
        pump(ch, rx, args.xon_timeout, until=lambda: rx.xon)
        if not rx.xon:
            print(
                "[fail] no XON received. The channel opened, but NVDA did not connect "
                "to the client pipe. Is rdAccess client mode enabled for RDP?"
            )
            return 2
        print("[ok] XON received: client is ready")

        # 2. Announce protocol v2 so the client switches to JSON Lines.
        send_json(ch, "protocol_version", version=PROTOCOL_VERSION, channel=CHANNEL)
        pump(ch, rx, 1.0)
        messages = rx.drain()
        print(f"[info] client sent {len(messages)} JSON message(s), {rx.legacy_frames} legacy frame(s) skipped")
        for m in messages:
            print(f"[rx] {m}")

        # 3. Speak.
        send_json(ch, "speak", sequence=[args.text])
        print(f"[tx] speak: {args.text!r}")

        # 4. NVDA sends {"type":"index","index":0} when it finishes speaking.
        def done_speaking() -> bool:
            return any(m.get("type") == "index" and m.get("index") == 0 for m in rx.messages)

        pump(ch, rx, 15.0, until=done_speaking)
        done = done_speaking()
        for m in rx.drain():
            print(f"[rx] {m}")
        print("[ok] NVDA reported done speaking" if done else "[warn] no done-speaking index seen")
        return 0
    finally:
        ch.close()


if __name__ == "__main__":
    sys.exit(main())
