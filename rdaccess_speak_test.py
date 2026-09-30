#!/usr/bin/env python3
"""Prototype: make NVDA on a Windows RDP client speak text sent from an xrdp session.

Run this INSIDE the xrdp session (same user, DISPLAY set), e.g. in a terminal.
Requires on the Windows client: NVDA with the rdAccess add-on, client side enabled
for RDP, and mstsc started after rdAccess registered rd_pipe.dll.

Usage:
    python3 rdaccess_speak_test.py "Hello from Linux"
    XRDPAPI_LIB=/path/to/libxrdpapi.so python3 rdaccess_speak_test.py --debug

Protocol facts this relies on (from rdAccess AGENTS.md and rd_pipe-rs source):
  * DVC name is NVDA-SPEECH (braille would be NVDA-BRAILLE).
  * rd_pipe writes a single XON byte (0x11) to the channel once NVDA has
    connected to the named pipe, and XOFF (0x13) on disconnect. Wait for XON.
  * Protocol v2 is JSON Lines: one UTF-8 JSON object per "\n", "type" required.
  * The client may still send legacy v1 binary frames until it sees JSON from
    us. Those are [driverType:1][command:1][len:2 LE][payload], and the payload
    can be a pickle. We skip them and NEVER unpickle.
"""

from __future__ import annotations

import argparse
import ctypes
import glob
import json
import os
import sys
import time

CHANNEL = "NVDA-SPEECH"
PROTOCOL_VERSION = 2
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_CHANNEL_OPTION_DYNAMIC = 0x00000001
XON = 0x11
XOFF = 0x13
LEGACY_DRIVER_TYPES = (ord("S"), ord("B"))


# --------------------------------------------------------------------------
# libxrdpapi binding
# --------------------------------------------------------------------------
def load_xrdpapi() -> ctypes.CDLL:
    candidates = [os.environ.get("XRDPAPI_LIB")]
    candidates += ["libxrdpapi.so.0", "libxrdpapi.so"]
    for pattern in (
        "/usr/lib/xrdp/libxrdpapi.so*",
        "/usr/local/lib/xrdp/libxrdpapi.so*",
        "/usr/lib/*/xrdp/libxrdpapi.so*",
        "/usr/lib*/libxrdpapi.so*",
    ):
        candidates += sorted(glob.glob(pattern))
    errors = []
    for path in filter(None, candidates):
        try:
            lib = ctypes.CDLL(path)
        except OSError as e:
            errors.append(f"{path}: {e}")
            continue
        lib.WTSVirtualChannelOpenEx.restype = ctypes.c_void_p
        lib.WTSVirtualChannelOpenEx.argtypes = [ctypes.c_uint, ctypes.c_char_p, ctypes.c_uint]
        lib.WTSVirtualChannelWrite.restype = ctypes.c_int
        lib.WTSVirtualChannelWrite.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.WTSVirtualChannelRead.restype = ctypes.c_int
        lib.WTSVirtualChannelRead.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.WTSVirtualChannelClose.restype = ctypes.c_int
        lib.WTSVirtualChannelClose.argtypes = [ctypes.c_void_p]
        print(f"[info] loaded {path}")
        return lib
    sys.exit(
        "Could not load libxrdpapi. Find it with: find / -name 'libxrdpapi*' 2>/dev/null\n"
        "then set XRDPAPI_LIB=<path> (you may also need LD_LIBRARY_PATH=<its directory>).\n"
        + "\n".join(errors)
    )


class DvcChannel:
    def __init__(self, lib: ctypes.CDLL, name: str, attempts: int = 5):
        self._lib = lib
        self._h = None
        # xrdpapi waits only 500 ms for the client to accept the DVC, so retry.
        for i in range(1, attempts + 1):
            h = lib.WTSVirtualChannelOpenEx(
                WTS_CURRENT_SESSION, name.encode(), WTS_CHANNEL_OPTION_DYNAMIC
            )
            if h:
                self._h = h
                print(f"[info] opened dynamic channel {name!r} (attempt {i})")
                return
            print(f"[warn] open attempt {i}/{attempts} failed; is NVDA/rdAccess registered on the client?")
            time.sleep(1)
        raise RuntimeError(
            f"Could not open DVC {name!r}. Check the xrdp chansrv log "
            "(~/.local/share/xrdp/xrdp-chansrv.*.log) and that drdynvc is not disabled in xrdp.ini."
        )

    def read(self, timeout_ms: int = 200) -> bytes:
        buf = ctypes.create_string_buffer(65536)
        n = ctypes.c_uint(0)
        ok = self._lib.WTSVirtualChannelRead(self._h, timeout_ms, buf, len(buf), ctypes.byref(n))
        if not ok:
            raise ConnectionError("channel closed by chansrv")
        return buf.raw[: n.value]

    def write(self, data: bytes, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        view = memoryview(data)
        while view:
            n = ctypes.c_uint(0)
            ok = self._lib.WTSVirtualChannelWrite(self._h, bytes(view), len(view), ctypes.byref(n))
            if not ok:
                raise ConnectionError("write failed")
            view = view[n.value :]
            if view:
                if time.monotonic() > deadline:
                    raise TimeoutError("write timed out")
                time.sleep(0.01)

    def close(self) -> None:
        if self._h:
            self._lib.WTSVirtualChannelClose(self._h)
            self._h = None


# --------------------------------------------------------------------------
# Receive-side parser (raw stream, arbitrary fragmentation)
# --------------------------------------------------------------------------
class Receiver:
    def __init__(self, debug: bool = False):
        self.buf = bytearray()
        self.xon = False
        self.messages: list[dict] = []
        self.legacy_frames = 0
        self.junk_bytes = 0
        self.debug = debug

    def feed(self, data: bytes) -> None:
        if self.debug and data:
            print(f"[raw] {data[:80].hex(' ')}{' ...' if len(data) > 80 else ''}")
        self.buf += data
        while self.buf:
            b = self.buf[0]
            if b == XON:
                self.xon = True
                del self.buf[0]
            elif b == XOFF:
                self.xon = False
                del self.buf[0]
            elif b == 0x0A:
                del self.buf[0]
            elif b == ord("{"):
                end = self.buf.find(b"\n")
                if end < 0:
                    return  # wait for the rest of the line
                line = bytes(self.buf[:end])
                del self.buf[: end + 1]
                try:
                    obj = json.loads(line.decode("utf-8"))
                except ValueError:
                    self.junk_bytes += len(line)
                    continue
                if isinstance(obj, dict):
                    self.messages.append(obj)
            elif b in LEGACY_DRIVER_TYPES:
                if len(self.buf) < 4:
                    return
                length = int.from_bytes(self.buf[2:4], "little")
                if len(self.buf) < 4 + length:
                    return
                del self.buf[: 4 + length]  # skip; payload may be a pickle
                self.legacy_frames += 1
            else:
                del self.buf[0]
                self.junk_bytes += 1


def send_json(ch: DvcChannel, msg_type: str, **payload) -> None:
    payload["type"] = msg_type
    ch.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


def pump(ch: DvcChannel, rx: Receiver, seconds: float, until=lambda: False) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        rx.feed(ch.read(200))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="Hello from Linux over xrdp")
    ap.add_argument("--debug", action="store_true", help="hex-dump raw received bytes")
    ap.add_argument("--xon-timeout", type=float, default=15.0)
    args = ap.parse_args()

    if not os.environ.get("DISPLAY"):
        sys.exit("DISPLAY is not set. Run this inside the xrdp session.")

    lib = load_xrdpapi()
    ch = DvcChannel(lib, CHANNEL)
    rx = Receiver(debug=args.debug)
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
        print(f"[info] client sent {len(rx.messages)} JSON message(s), {rx.legacy_frames} legacy frame(s) skipped")
        for m in rx.messages:
            print(f"[rx] {m}")

        # 3. Speak.
        send_json(ch, "speak", sequence=[args.text])
        print(f"[tx] speak: {args.text!r}")

        # 4. NVDA sends {"type":"index","index":0} when it finishes speaking.
        seen = len(rx.messages)
        pump(ch, rx, 15.0, until=lambda: any(
            m.get("type") == "index" and m.get("index") == 0 for m in rx.messages[seen:]
        ))
        for m in rx.messages[seen:]:
            print(f"[rx] {m}")
        done = any(m.get("type") == "index" and m.get("index") == 0 for m in rx.messages[seen:])
        print("[ok] NVDA reported done speaking" if done else "[warn] no done-speaking index seen")
        return 0
    finally:
        ch.close()


if __name__ == "__main__":
    sys.exit(main())
