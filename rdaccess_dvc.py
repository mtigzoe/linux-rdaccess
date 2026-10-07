"""Transport and protocol v2 helpers for talking to NVDA's rdAccess add-on from xrdp.

Moved (not rewritten) from rdaccess_speak_test.py, which proved the approach.
Changes made for long-running use are marked "long-running fix" below.

Facts this relies on (rdAccess AGENTS.md, rd_pipe-rs source, xrdp xrdpapi.c):
  * The DVC is named NVDA-SPEECH (braille would be NVDA-BRAILLE).
  * rd_pipe writes one XON byte (0x11) once NVDA has connected to its named
    pipe, and XOFF (0x13) when NVDA disconnects. Both are outside any framing.
  * Protocol v2 is JSON Lines: one UTF-8 JSON object per "\\n", "type" required.
  * Until it sees JSON from us, the client may send legacy v1 binary frames:
    [driverType:1][command:1][len:2 LE][payload]. The payload can be a pickle.
    We skip those frames and never unpickle.
  * libxrdpapi's WTSVirtualChannelOpenEx waits only 500 ms for the client to
    accept a DVC, so opening is retried.

Everything here is single-threaded: call it from one thread (the GLib main loop).
"""

from __future__ import annotations

import ctypes
import glob
import json
import logging
import os
import sys
import time
from typing import Callable, Optional

log = logging.getLogger("rdaccess")

CHANNEL = "NVDA-SPEECH"
PROTOCOL_VERSION = 2
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_CHANNEL_OPTION_DYNAMIC = 0x00000001
XON = 0x11
XOFF = 0x13
LEGACY_DRIVER_TYPES = (ord("S"), ord("B"))
LEGACY_GENERIC_ATTRIBUTE = ord("@")
LEGACY_ATTRIBUTE_SEPARATOR = bytes((96,))

# long-running fix: bound the buffer so a peer that never sends "\n" cannot
# grow memory forever.
MAX_PENDING_BYTES = 1 << 20


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
        log.info("loaded %s", path)
        return lib
    sys.exit(
        "Could not load libxrdpapi. Find it with: find / -name 'libxrdpapi*' 2>/dev/null\n"
        "then set XRDPAPI_LIB=<path> (you may also need LD_LIBRARY_PATH=<its directory>).\n"
        + "\n".join(errors)
    )


class DvcChannel:
    def __init__(self, lib: ctypes.CDLL, name: str, attempts: int = 5, retry_delay: float = 1.0):
        self._lib = lib
        self._h = None
        # xrdpapi waits only 500 ms for the client to accept the DVC, so retry.
        for i in range(1, attempts + 1):
            h = lib.WTSVirtualChannelOpenEx(
                WTS_CURRENT_SESSION, name.encode(), WTS_CHANNEL_OPTION_DYNAMIC
            )
            if h:
                self._h = h
                log.info("opened dynamic channel %r (attempt %d)", name, i)
                return
            log.warning(
                "open attempt %d/%d failed; is NVDA/rdAccess registered on the client?", i, attempts
            )
            if i < attempts:
                time.sleep(retry_delay)
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
    def __init__(self):
        self.buf = bytearray()
        self.xon = False
        self.xon_count = 0  # how many XON bytes were seen; lets callers notice XOFF->XON flaps
        self.messages: list[dict] = []
        self.legacy_frames = 0
        self.junk_bytes = 0

    def drain(self) -> list[dict]:
        """Return and clear the parsed JSON messages.

        long-running fix: `messages` used to grow forever (NVDA sends an
        `index` message after every utterance). Long-running callers must drain.
        """
        out, self.messages = self.messages, []
        return out

    def feed(self, data: bytes) -> None:
        if data and log.isEnabledFor(logging.DEBUG):
            log.debug("received %d bytes", len(data))
        self.buf += data
        while self.buf:
            b = self.buf[0]
            if b == XON:
                self.xon = True
                self.xon_count += 1
                del self.buf[0]
            elif b == XOFF:
                self.xon = False
                del self.buf[0]
            elif b == 0x0A:
                del self.buf[0]
            elif b == ord("{"):
                end = self.buf.find(b"\n")
                # rd_pipe emits flow controls independently of the client's
                # records. A disconnect can therefore terminate a partial
                # JSON line. Raw XON/XOFF cannot occur in valid JSON (escaped
                # controls are ordinary ASCII bytes), so discard only the
                # interrupted prefix and let the outer loop process them.
                controls = [pos for pos in (self.buf.find(bytes((XON,))),
                                            self.buf.find(bytes((XOFF,))))
                            if pos >= 0 and (end < 0 or pos < end)]
                if controls:
                    interrupted = min(controls)
                    self.junk_bytes += interrupted
                    del self.buf[:interrupted]
                    continue
                if end < 0:
                    if len(self.buf) > MAX_PENDING_BYTES:
                        log.warning("dropping %d bytes of unterminated JSON", len(self.buf))
                        self.junk_bytes += len(self.buf)
                        self.buf.clear()
                    return  # wait for the rest of the line
                line = bytes(self.buf[:end])
                del self.buf[: end + 1]
                try:
                    obj = json.loads(line.decode("utf-8"))
                except (ValueError, RecursionError):
                    self.junk_bytes += len(line)
                    continue
                if isinstance(obj, dict):
                    self.messages.append(obj)
            elif b in LEGACY_DRIVER_TYPES:
                if len(self.buf) < 4:
                    return
                driver_type = b
                command = self.buf[1]
                length = int.from_bytes(self.buf[2:4], "little")
                if len(self.buf) < 4 + length:
                    return
                payload = bytes(self.buf[4 : 4 + length])
                del self.buf[: 4 + length]
                self.legacy_frames += 1
                # rdAccess can ask for focus-sensitive attributes before the
                # protocol-v2 handshake completes. Decode only the safe,
                # non-pickled legacy attribute envelope; all other legacy
                # payloads remain skipped and are never unpickled.
                if command == LEGACY_GENERIC_ATTRIBUTE and payload.startswith(
                    LEGACY_ATTRIBUTE_SEPARATOR
                ):
                    try:
                        attribute, raw_value = payload[1:].split(
                            LEGACY_ATTRIBUTE_SEPARATOR, 1
                        )
                        attribute_name = attribute.decode("ascii")
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not raw_value:
                        self.messages.append(
                            {
                                "type": "attribute_request",
                                "attribute": attribute_name,
                                "_legacy_driver_type": driver_type,
                            }
                        )
                    elif attribute_name == "timeSinceInput" and len(raw_value) == 4:
                        self.messages.append(
                            {
                                "type": "attribute_value",
                                "attribute": attribute_name,
                                "value": int.from_bytes(raw_value, "little"),
                                "_legacy_driver_type": driver_type,
                            }
                        )
            else:
                del self.buf[0]
                self.junk_bytes += 1


def send_json(ch, msg_type: str, **payload) -> None:
    payload["type"] = msg_type
    ch.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


def send_legacy_attribute_value(
    ch,
    driver_type: int,
    attribute: str,
    value: int,
) -> None:
    """Send a safe legacy integer attribute value without pickle."""
    widths = {
        "protocolVersion": 1,
        "timeSinceInput": 4,
    }
    try:
        width = widths[attribute]
    except KeyError:
        raise ValueError(f"unsupported legacy integer attribute: {attribute}") from None
    raw_value = int(value).to_bytes(width, "little", signed=False)
    payload = (
        LEGACY_ATTRIBUTE_SEPARATOR
        + attribute.encode("ascii")
        + LEGACY_ATTRIBUTE_SEPARATOR
        + raw_value
    )
    frame = bytes((driver_type, LEGACY_GENERIC_ATTRIBUTE))
    frame += len(payload).to_bytes(2, "little")
    ch.write(frame + payload)


def pump(ch, rx: Receiver, seconds: float, until=lambda: False) -> None:
    """Blocking read loop. Fine for startup and the smoke test; the bridge uses NvdaSpeechLink.poll()."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        rx.feed(ch.read(200))


# --------------------------------------------------------------------------
# Long-lived speech link
# --------------------------------------------------------------------------
class NvdaSpeechLink:
    """Keeps one NVDA-SPEECH channel healthy for the life of the process.

    Call poll() every ~50 ms from the main loop. It
      * drains whatever NVDA sent (XON/XOFF, index, legacy frames),
      * re-announces protocol v2 on every XON (a reconnecting client starts in
        legacy mode again),
      * reopens the channel with a delay if chansrv closed it.

    speak() only sends while the client has said XON; otherwise it drops the
    text, because stale speech is worse than none.
    """

    def __init__(
        self,
        open_channel: Callable[[], object],
        *,
        on_ready: Optional[Callable[[], None]] = None,
        retry_interval: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._open_channel = open_channel
        self._on_ready = on_ready
        self._retry_interval = retry_interval
        self._clock = clock
        self._channel = None
        self._rx = Receiver()
        self._seen_xon_count = 0
        self._next_open_at = 0.0

    @property
    def ready(self) -> bool:
        return self._channel is not None and self._rx.xon

    def poll(self) -> None:
        if self._channel is None:
            self._try_open()
            return
        try:
            for _ in range(16):  # bounded work per tick
                data = self._channel.read(0)
                if not data:
                    break
                self._rx.feed(data)
        except (ConnectionError, OSError) as exc:
            self._drop(f"read failed: {exc}")
            return
        for msg in self._rx.drain():
            if msg.get("type") not in ("index", "ping"):
                log.debug("received a protocol message")
        if self._rx.xon_count != self._seen_xon_count:
            self._seen_xon_count = self._rx.xon_count
            if self._rx.xon:
                self._handshake()

    def speak(self, text: str, interrupt: bool = False) -> bool:
        if not self.ready:
            log.debug("not ready; speech dropped")
            return False
        try:
            if interrupt:
                send_json(self._channel, "cancel")
            send_json(self._channel, "speak", sequence=[text])
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"write failed: {exc}")
            return False
        return True

    def close(self) -> None:
        self._drop("closing", quiet=True)

    # -- internals ---------------------------------------------------------
    def _try_open(self) -> None:
        if self._clock() < self._next_open_at:
            return
        try:
            self._channel = self._open_channel()
        except RuntimeError as exc:
            self._next_open_at = self._clock() + self._retry_interval
            log.warning("channel open failed (retrying every %.0fs)", self._retry_interval)
            return
        self._rx = Receiver()
        self._seen_xon_count = 0
        log.info("channel open; waiting for NVDA to connect (XON)")

    def _handshake(self) -> None:
        try:
            send_json(self._channel, "protocol_version", version=PROTOCOL_VERSION, channel=CHANNEL)
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"handshake failed: {exc}")
            return
        log.info("XON received; announced protocol v%d", PROTOCOL_VERSION)
        if self._on_ready is not None:
            try:
                self._on_ready()
            except Exception:
                log.error("speech on_ready callback failed")

    def _drop(self, reason: str, quiet: bool = False) -> None:
        if self._channel is not None:
            if not quiet:
                log.warning("channel lost; will reopen")
            try:
                self._channel.close()
            except Exception:  # closing a dead handle must never raise
                pass
        self._channel = None
        self._next_open_at = self._clock() + self._retry_interval
