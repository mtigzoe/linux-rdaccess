#!/usr/bin/env python3
"""Receive opt-in NVDA speech-probe events over an SSH local-forward.

The receiver binds only to loopback and never writes speech to disk. Exact
speech text is hidden unless --show-text is explicitly requested.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import time

DEFAULT_PORT = 8765
MAX_LINE_BYTES = 32768
MAX_TEXT_CHARS = 8192
MAX_SEGMENTS = 512


class ProbeError(ValueError):
    """Fixed diagnostic error whose message never includes payload contents."""


def decode_event(raw: bytes) -> dict:
    """Validate one JSON-line event from the Windows NVDA probe."""
    if not raw or len(raw) > MAX_LINE_BYTES:
        raise ProbeError("invalid speech probe event size")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProbeError("invalid speech probe event") from None
    if not isinstance(value, dict) or value.get("type") != "speech":
        raise ProbeError("unsupported speech probe event")
    text = value.get("text")
    segments = value.get("segments")
    sequence = value.get("sequence")
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise ProbeError("invalid speech probe text")
    if isinstance(segments, bool) or not isinstance(segments, int) or not 0 <= segments <= MAX_SEGMENTS:
        raise ProbeError("invalid speech probe segment count")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ProbeError("invalid speech probe sequence")
    return {"type": "speech", "text": text, "segments": segments, "sequence": sequence}


def read_connection_event(connection: socket.socket, *, timeout: float = 1.0) -> dict | None:
    """Read one event without letting empty/tunnel-probe connections kill the listener."""
    connection.settimeout(timeout)
    try:
        with connection.makefile("rb") as stream:
            raw = stream.readline(MAX_LINE_BYTES + 1)
    except (socket.timeout, TimeoutError, OSError):
        return None
    if not raw:
        return None
    return decode_event(raw)


def public_event(event: dict, *, show_text: bool, received_at: float | None = None) -> dict:
    """Return terminal-safe output, revealing text only after explicit opt-in."""
    result = {
        "event": "speech",
        "sequence": event["sequence"],
        "segments": event["segments"],
        "characters": len(event["text"]),
    }
    if received_at is not None:
        result["received_monotonic"] = round(received_at, 6)
    if show_text:
        result["text"] = event["text"]
    return result


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve(*, host: str, port: int, show_text: bool, once: bool, timeout: float) -> int:
    if not _loopback(host):
        raise ProbeError("speech probe receiver must bind to loopback")
    if not 1024 <= port <= 65535:
        raise ProbeError("invalid speech probe port")
    if timeout < 0:
        raise ProbeError("invalid speech probe timeout")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(4)
        listener.settimeout(0.5)
        print(json.dumps({
            "status": "listening",
            "host": host,
            "port": port,
            "show_text": show_text,
            "transport": "ssh-local-forward",
        }), flush=True)
        started = time.monotonic()
        received = 0
        while True:
            if timeout and time.monotonic() - started >= timeout:
                return 0
            try:
                connection, address = listener.accept()
            except socket.timeout:
                continue
            with connection:
                if not ipaddress.ip_address(address[0]).is_loopback:
                    continue
                try:
                    event = read_connection_event(connection)
                except ProbeError as exc:
                    print(json.dumps({"error": str(exc)}), flush=True)
                    continue
                if event is None:
                    # VS Code/SSH port-forward probes may connect without sending data.
                    continue
                print(json.dumps(
                    public_event(event, show_text=show_text, received_at=time.monotonic()),
                    ensure_ascii=False,
                ), flush=True)
                received += 1
                if once and received:
                    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--show-text", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--timeout", type=float, default=0.0, help="Stop after N seconds; 0 waits indefinitely")
    args = parser.parse_args(argv)
    try:
        return serve(host=args.host, port=args.port, show_text=args.show_text, once=args.once, timeout=args.timeout)
    except (ProbeError, OSError) as exc:
        message = str(exc) if isinstance(exc, ProbeError) else "speech probe receiver unavailable"
        print(json.dumps({"error": message}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
