"""Persistent rdAccess dynamic channel for semantic accessibility objects."""

from __future__ import annotations

import logging
import time
from typing import Callable

from .rdaccess_dvc import PROTOCOL_VERSION, Receiver, send_json

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
        on_ready: Callable[[], None] | None = None,
    ):
        self._open_channel = open_channel
        # Called once per completed handshake, before cached state is replayed.
        # The owner uses it to re-read the live AT-SPI focus and hand the result
        # back through refresh_focus()/clear_focus().
        self._on_ready = on_ready
        self.channel_name = channel_name
        self._retry_interval = retry_interval
        self._clock = clock
        self._channel = None
        self._rx = Receiver()
        self._seen_xon_count = 0
        self._next_open_at = 0.0
        self._pending_focus: tuple[str, list[dict]] | None = None
        self._pending_text: dict | None = None
        # Newest semantic state, kept after it has been delivered so that a new
        # channel session (reconnect, XOFF->XON flap, heartbeat reopen) can be
        # brought up to date without waiting for another AT-SPI event.
        self._last_focus: tuple[str, list[dict]] | None = None
        self._last_text: dict | None = None
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

    @property
    def last_focus_id(self) -> str | None:
        """ID of the newest focus snapshot's target, delivered or not."""
        return self._last_focus[0] if self._last_focus is not None else None

    def poll(self) -> None:
        if self._channel is None:
            self._try_open()
            return
        channel, receiver = self._channel, self._rx
        try:
            for _ in range(16):
                data = self._channel.read(0)
                if not data:
                    break
                self._rx.feed(data)
        except (ConnectionError, OSError) as exc:
            self._drop(f"read failed: {exc}")
            return
        # Establish a new XON session before accepting any messages from
        # the same read batch. Otherwise an a11y_action adjacent to the first
        # XON can execute before protocol-v2 has been announced.
        if self._rx.xon_count != self._seen_xon_count:
            self._seen_xon_count = self._rx.xon_count
            if self._rx.xon:
                self._handshake()
                if self._channel is not channel or self._rx is not receiver:
                    return
        for msg in self._rx.drain_current_session():
            if msg.get("type") != "ping":
                log.debug("received an A11Y protocol message")
            pong_nonce = decode_pong(msg)
            if pong_nonce is not None:
                if pong_nonce == self._awaiting_pong_nonce:
                    self._awaiting_pong_nonce = None
                    self._awaiting_pong_since = 0.0
                    self._next_ping_at = self._clock() + self._heartbeat_interval
                continue
            if msg.get("type") == "a11y_action":
                self._handle_action_message(msg)
                if self._channel is not channel or self._rx is not receiver:
                    return
        self._poll_heartbeat()

    def send_focus(self, *, focus_id: str, objects: list[dict]) -> bool:
        # Keep the newest semantic focus snapshot even while the DVC is still
        # negotiating.  Focus often arrives before rdAccess has opened its
        # named pipe, and losing that first snapshot leaves NVDA stuck on the
        # RDP Input Capture Window until the user moves focus again.
        self._pending_focus = (focus_id, objects)
        self._last_focus = self._pending_focus
        # A new focus target supersedes any text state held for the old one.
        self._last_text = None
        self._pending_text = None
        if not self.ready:
            return False
        return self._send_pending_focus()

    def refresh_focus(self, *, focus_id: str, objects: list[dict]) -> None:
        """Replace the remembered focus with a freshly read snapshot.

        Intended for the on_ready callback: the snapshot is delivered by the
        handshake that invoked it, never sent from here, so a reconnect cannot
        produce two focus messages.  Text held for the previous snapshot is
        dropped because the fresh snapshot already carries the focused
        object's text, caret and selection.
        """
        self._pending_focus = self._last_focus = (focus_id, objects)
        self._pending_text = self._last_text = None

    def clear_focus(self) -> None:
        """Forget remembered focus because AT-SPI reports nothing focused.

        Stale object IDs from before a reconnect must not be replayed.
        """
        self._pending_focus = self._last_focus = None
        self._pending_text = self._last_text = None

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
            log.error("failed to handle remote A11Y action")

    def send_text_update(
        self,
        *,
        object_id: str,
        event: str,
        text_supported: bool,
        text: str,
        text_truncated: bool,
        caret_offset: int | None,
        selection_start: int | None,
        selection_end: int | None,
    ) -> bool:
        self._pending_text = self._last_text = {
            "object_id": object_id,
            "event": event,
            "text_supported": text_supported,
            "text": text,
            "text_truncated": text_truncated,
            "caret_offset": caret_offset,
            "selection_start": selection_start,
            "selection_end": selection_end,
        }
        if not self.ready:
            return False
        return self._send_pending_text()

    def close(self) -> None:
        self._drop("closing", quiet=True)

    def _try_open(self) -> None:
        if self._clock() < self._next_open_at:
            return
        try:
            self._channel = self._open_channel()
        except RuntimeError as exc:
            self._next_open_at = self._clock() + self._retry_interval
            log.debug("A11Y channel open failed (retry in %.0fs)", self._retry_interval)
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
        # Every new channel session starts with an empty remote object tree, so
        # the newest known focus (and text for that same object) is queued
        # again even if an earlier session already delivered it.
        if self._pending_focus is None:
            self._pending_focus = self._last_focus
        if self._pending_text is None:
            self._pending_text = self._replayable_text()
        if self._on_ready is not None:
            try:
                self._on_ready()
            except Exception:
                log.error("a11y on_ready callback failed; replaying cached state")
        self._send_pending_focus()
        # _send_pending_focus() can drop the channel; text must follow its focus.
        self._send_pending_text()

    def _replayable_text(self) -> dict | None:
        if self._last_focus is None or self._last_text is None:
            return None
        if self._last_text.get("object_id") != self._last_focus[0]:
            return None
        return self._last_text

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

    def _send_pending_text(self) -> bool:
        if not self.ready or self._pending_text is None:
            return False
        payload = self._pending_text
        try:
            send_json(
                self._channel,
                "a11y_text",
                **payload,
            )
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"text write failed: {exc}")
            return False
        self._pending_text = None
        return True

    def _drop(self, reason: str, quiet: bool = False) -> None:
        if self._channel is not None:
            if not quiet:
                log.warning("a11y channel lost; will reopen")
            try:
                self._channel.close()
            except Exception:
                pass
        self._channel = None
        self._awaiting_pong_nonce = None
        self._awaiting_pong_since = 0.0
        self._next_ping_at = 0.0
        self._next_open_at = self._clock() + self._retry_interval
