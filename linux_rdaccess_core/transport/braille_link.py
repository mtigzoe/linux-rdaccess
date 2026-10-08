"""Long-lived rdAccess NVDA-BRAILLE transport for xrdp."""

import logging
import time

from .rdaccess_dvc import (
    LEGACY_DRIVER_TYPES,
    PROTOCOL_VERSION,
    Receiver,
    send_json,
    send_legacy_attribute_value,
)

log = logging.getLogger("brailleLink")
MAX_BRAILLE_CELLS = 1024


class NvdaBrailleLink:
    CHANNEL = "NVDA-BRAILLE"
    DRIVER_TYPE = ord("B")

    def __init__(
        self,
        open_channel,
        *,
        retry_interval=3.0,
        clock=time.monotonic,
        default_cells=80,
        on_ready=None,
    ):
        self._open_channel = open_channel
        # Called when the JSON session becomes ready and again whenever the remote
        # display width changes, so the owner can re-render what braille should show.
        self._on_ready = on_ready
        # Newest content offered while the link was not ready.  Braille has no
        # AT-SPI event to repeat, so without this an announcement made before the
        # handshake finished (for example the bridge's ready text) is lost.
        self._pending_cells = None
        self._retry_interval = retry_interval
        self._clock = clock
        self._channel = None
        self._rx = Receiver()
        self._seen_xon = 0
        self._next_open = 0.0
        self._json_ready = False
        self._requested_cells = False
        self._default_cells = default_cells
        self.num_cells = default_cells

    @property
    def ready(self):
        return self._channel is not None and self._rx.xon and self._json_ready

    def poll(self):
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

        if self._rx.xon_count != self._seen_xon:
            self._seen_xon = self._rx.xon_count
            if self._rx.xon:
                self._start_handshake()
            if self._channel is None:
                return

        for message in self._rx.drain_current_session():
            self._handle(message)
            if self._channel is None:
                return

    def display(self, cells):
        if not self.ready:
            self._pending_cells = [int(cell) & 0xFF for cell in list(cells)[:MAX_BRAILLE_CELLS]]
            return False
        self._pending_cells = None
        width = max(1, self.num_cells)
        cells = [int(cell) & 0xFF for cell in cells[:width]]
        cells += [0] * (width - len(cells))
        try:
            send_json(self._channel, "display", cells=cells)
            return True
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"write failed: {exc}")
            return False

    def close(self):
        self._drop("closing", quiet=True)

    def _try_open(self):
        if self._clock() < self._next_open:
            return
        try:
            self._channel = self._open_channel()
        except RuntimeError as exc:
            self._next_open = self._clock() + self._retry_interval
            log.warning("braille channel open failed (retrying every %.0fs)", self._retry_interval)
            return
        self._rx = Receiver()
        self._seen_xon = 0
        self._json_ready = False
        self._requested_cells = False
        # numCells belongs to the current remote display/session. Do not carry
        # a previous client's width into a freshly opened channel while the
        # new attribute request is still negotiating.
        self.num_cells = self._default_cells
        log.info("braille channel open; waiting for XON")

    def _start_handshake(self):
        self._json_ready = False
        self._requested_cells = False
        # numCells is session-scoped even when rd_pipe reuses the same DVC
        # across an XOFF -> XON client reconnect. Do not expose the previous
        # display width while the replacement client is still negotiating.
        self.num_cells = self._default_cells
        try:
            send_legacy_attribute_value(
                self._channel, self.DRIVER_TYPE, "protocolVersion", PROTOCOL_VERSION
            )
        except (ConnectionError, TimeoutError, OSError) as exc:
            self._drop(f"handshake failed: {exc}")

    def _handle(self, message):
        kind = message.get("type")
        attribute = message.get("attribute")

        if kind == "protocol_version":
            try:
                version = int(message.get("version", 0))
            except (TypeError, ValueError, OverflowError):
                version = 0
            if version >= PROTOCOL_VERSION:
                try:
                    if not self._json_ready:
                        send_json(
                            self._channel,
                            "protocol_version",
                            version=PROTOCOL_VERSION,
                            channel=self.CHANNEL,
                        )
                    became_ready = not self._json_ready
                    self._json_ready = True
                    if not self._requested_cells:
                        send_json(self._channel, "attribute_request", attribute="numCells")
                        self._requested_cells = True
                except (ConnectionError, TimeoutError, OSError) as exc:
                    self._drop(f"protocol negotiation failed: {exc}")
                else:
                    if became_ready:
                        self._notify_ready()
            return

        if kind == "attribute_request" and attribute in ("timeSinceInput", "protocolVersion"):
            value = 0 if attribute == "timeSinceInput" else PROTOCOL_VERSION
            legacy_driver = message.get("_legacy_driver_type")
            if legacy_driver is not None and (
                type(legacy_driver) is not int or legacy_driver not in LEGACY_DRIVER_TYPES
            ):
                return
            try:
                if legacy_driver is not None:
                    send_legacy_attribute_value(
                        self._channel, legacy_driver, attribute, value
                    )
                else:
                    send_json(
                        self._channel, "attribute_value", attribute=attribute, value=value
                    )
            except (ConnectionError, TimeoutError, OSError) as exc:
                self._drop(f"attribute reply failed: {exc}")
            return

        if kind == "attribute_value" and attribute == "numCells":
            raw_value = message.get("value", 0)
            try:
                value = int(raw_value)
            except (TypeError, ValueError, OverflowError):
                value = 0
            if type(raw_value) is not bool and 0 < value <= MAX_BRAILLE_CELLS:
                changed = value != self.num_cells
                self.num_cells = value
                log.info("remote braille display has %d cells", value)
                if changed and self.ready:
                    self._notify_ready()

    def _notify_ready(self):
        """Let the owner render current content, then flush anything still queued."""
        if self._on_ready is not None:
            try:
                self._on_ready()
            except Exception as exc:
                log.error("braille on_ready callback failed (%s)", type(exc).__name__)
        if self._pending_cells is not None and self.ready:
            self.display(self._pending_cells)

    def _drop(self, reason, quiet=False):
        if self._channel is not None:
            if not quiet:
                log.warning("braille channel lost; will reopen")
            try:
                self._channel.close()
            except Exception:
                pass
        self._channel = None
        self._json_ready = False
        self._next_open = self._clock() + self._retry_interval
