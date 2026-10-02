"""Persistent rdAccess dynamic channel for semantic accessibility objects."""

from __future__ import annotations

import logging
import time
from typing import Callable

from rdaccess_dvc import PROTOCOL_VERSION, Receiver, send_json

log = logging.getLogger("a11yLink")
A11Y_CHANNEL = "NVDA-A11Y"
MAX_ACTIONS = 32
MAX_OBJECT_ID_CHARS = 256
HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0


def decode_pong(msg: dict) -> int | None:
    if msg.get("type") != "a11y_pong":
        return None
    nonce = msg.get("nonce")
    if type(nonce) is not int or nonce < 0 or nonce > 0x7FFFFFFF:
        return None
    return nonce


def decode_action_request(msg: dict) -> tuple[str, int] | None:
    if msg.get("type") != "a11y_action":
        return None
    object_id = msg.get("object_id")
    action_index = msg.get("action_index")
    if not isinstance(object_id, str) or not object_id or len(object_id) > MAX_OBJECT_ID_CHARS:
        return None
    if type(action_index) is not int or action_index < 0 or action_index >= MAX_ACTIONS:
        return None
    return object_id, action_index


class NvdaA11yLink:
    def __init__(
        self,
        open_channel: Callable[[], object],
        *,
        channel_name: str = A11Y_CHANNEL,
        retry_interval: float = 3.0,
        clock=time.monotonic,
        on_action: Callable[[str, int], None] | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT,
    ):
        self._open_channel = open_channel
        self.channel_name = channel_name
        self._retry_interval = retry_interval
        self._clock = clock
        self._channel = None
        self._rx = Receiver()
        self._seen_xon_count = 0
        self._next_open_at = 0.0
        self._pending_focus: tuple[str, list[dict]] | None = None
        self._on_action = on_action
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._next_ping_at = 0.0
        self._awaiting_pong_nonce: int | None = None
        self._awaiting_pong_since = 0.0
        self._heartbeat_nonce = 0

    @property
    def ready(self) -> bool:
        return self._channel is not None and self._rx.xon

    def poll(self) -> None:
        if self._channel is None:
            self._try_open()
            return
        try:
            for _ in range(16):
                data = self._channel.read(0)
                if not data:
                    break
                self._rx.feed(data)
        except (ConnectionError, OSError) as exc:
            self._drop(f"read failed: {exc}")
            return
        for msg in self._rx.drain():
            if msg.get("type") != "ping":
                log.debug("a11y rx %s", msg)
            pong_nonce = decode_pong(msg)
            if pong_nonce is not None:
                if pong_nonce == self._awaiting_pong_nonce:
                    self._awaiting_pong_nonce = None
                    self._awaiting_pong_since = 0.0
                    self._next_ping_at = self._clock() + self._heartbeat_interval
                continue
            if msg.get("type") == "a11y_action":
                self._handle_action_message(msg)
        if self._rx.xon_count != self._seen_xon_count:
            self._seen_xon_count = self._rx.xon_count
            self._handshake()
        self._poll_heartbeat()

    def send_focus(self, *, focus_id: str, objects: list[dict]) -> bool:
        # Keep the newest semantic focus snapshot even while the DVC is still
        # negotiating.  Focus often arrives before rdAccess has opened its
        # named pipe, and losing that first snapshot leaves NVDA stuck on the
        # RDP Input Capture Window until the user moves focus again.
        self._pending_focus = (focus_id, objects)
        if not self.ready:
            return False
        return self._send_pending_focus()

    def _handle_action_message(self, msg: dict) -> None:
        if not self.ready or self._on_action is None:
            return
        decoded = decode_action_request(msg)
        if decoded is None:
            log.warning("ignoring invalid remote A11Y action request")
            return
        object_id, action_index = decoded
        try:
            self._on_action(object_id, action_index)
        except Exception:
            log.exception("failed to handle remote A11Y action for %s", object_id)

    def close(self) -> None:
        self._drop("closing", quiet=True)

    def _try_open(self) -> None:
        if self._clock() < self._next_open_at:
            return
        try:
            self._channel = self._open_channel()
        except RuntimeError as exc:
            self._next_open_at = self._clock() + self._retry_interval
            log.debug("%s (A11Y retry in %.0fs)", exc, self._retry_interval)
            return
        self._rx = Receiver()
        self._seen_xon_count = 0
        log.info("a11y channel open; waiting for XON")

    def _handshake(self) -> None:
        try:
            send_json(
                self._channel,
                "protocol_version",
                version=PROTOCOL_VERSION,
                channel=self.channel_name,
            )
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"handshake failed: {exc}")
            return
        log.info("a11y XON received; announced protocol v%d", PROTOCOL_VERSION)
        self._awaiting_pong_nonce = None
        self._awaiting_pong_since = 0.0
        self._next_ping_at = self._clock() + self._heartbeat_interval
        self._send_pending_focus()

    def _poll_heartbeat(self) -> None:
        if not self.ready:
            return
        now = self._clock()
        if self._awaiting_pong_nonce is not None:
            if now - self._awaiting_pong_since >= self._heartbeat_timeout:
                self._drop("heartbeat timed out")
            return
        if now < self._next_ping_at:
            return
        nonce = self._heartbeat_nonce
        self._heartbeat_nonce = (self._heartbeat_nonce + 1) & 0x7FFFFFFF
        try:
            send_json(self._channel, "a11y_ping", nonce=nonce)
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"heartbeat write failed: {exc}")
            return
        self._awaiting_pong_nonce = nonce
        self._awaiting_pong_since = now

    def _send_pending_focus(self) -> bool:
        if not self.ready or self._pending_focus is None:
            return False
        focus_id, objects = self._pending_focus
        try:
            send_json(
                self._channel,
                "a11y_focus",
                focus_id=focus_id,
                objects=objects,
            )
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"write failed: {exc}")
            return False
        self._pending_focus = None
        return True

    def _drop(self, reason: str, quiet: bool = False) -> None:
        if self._channel is not None:
            if not quiet:
                log.warning("a11y channel lost (%s); will reopen", reason)
            try:
                self._channel.close()
            except Exception:
                pass
        self._channel = None
        self._awaiting_pong_nonce = None
        self._awaiting_pong_since = 0.0
        self._next_ping_at = 0.0
        self._next_open_at = self._clock() + self._retry_interval
