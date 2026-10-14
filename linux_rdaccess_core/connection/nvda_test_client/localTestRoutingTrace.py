# License: GNU General Public License version 2 or later.
"""Opt-in, in-memory routing metadata; no text, identifiers, files or input."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

TRACE_LIMIT = 12
_MAX_COUNT = 2**31 - 1
_EVENTS = frozenset(
	{
		"message_shown",
		"message_dismissed",
		"remote_dismiss_called",
		"remote_dismiss_returned",
		"route_received",
		"route_guarded",
		"route_native",
		"route_delegated",
		"route_discarded",
		"caret_sent",
		"caret_received",
		"control_changed",
	}
)
_BUFFERS = frozenset({"main", "message", "other", "unavailable"})
_FIELDS = frozenset(
	{
		"seq",
		"elapsed_ms",
		"event",
		"buffer",
		"linux_owned",
		"control",
		"capture",
		"semantic_input",
		"index",
		"offset",
		"same_focus",
	}
)


def emptyTrace() -> dict[str, Any]:
	return {
		"schema_version": 1,
		"available": False,
		"snapshot_ms": None,
		"limit": TRACE_LIMIT,
		"dropped": 0,
		"events": [],
	}


def sanitizeRoutingTrace(value: Any) -> dict[str, Any]:
	"""Reject unknown fields and strings before authenticated serialization."""
	if type(value) is not dict or set(value) != {
		"schema_version",
		"available",
		"snapshot_ms",
		"limit",
		"dropped",
		"events",
	}:
		raise ValueError("Invalid routing trace schema")
	if (
		type(value["schema_version"]) is not int
		or value["schema_version"] != 1
		or type(value["available"]) is not bool
		or type(value["limit"]) is not int
		or value["limit"] != TRACE_LIMIT
		or type(value["dropped"]) is not int
		or not 0 <= value["dropped"] <= _MAX_COUNT
		or type(value["events"]) is not list
		or len(value["events"]) > TRACE_LIMIT
	):
		raise ValueError("Invalid routing trace fields")
	if not value["available"] and (value["events"] or value["dropped"]):
		raise ValueError("Inactive routing trace cannot expose events")
	if value["available"]:
		if type(value["snapshot_ms"]) is not int or not 0 <= value["snapshot_ms"] <= 300_000:
			raise ValueError("Invalid routing snapshot time")
	elif value["snapshot_ms"] is not None:
		raise ValueError("Inactive routing trace cannot expose timing")
	events = []
	previousTime = 0
	for seq, event in enumerate(value["events"], 1):
		if type(event) is not dict or set(event) != _FIELDS:
			raise ValueError("Invalid routing event schema")
		if (
			type(event["seq"]) is not int
			or event["seq"] != seq
			or type(event["elapsed_ms"]) is not int
			or not previousTime <= event["elapsed_ms"] <= value["snapshot_ms"]
			or type(event["event"]) is not str
			or event["event"] not in _EVENTS
			or type(event["buffer"]) is not str
			or event["buffer"] not in _BUFFERS
		):
			raise ValueError("Invalid routing event fields")
		for field in ("linux_owned", "control", "capture", "semantic_input"):
			if type(event[field]) is not bool:
				raise ValueError("Invalid routing state")
		if event["same_focus"] is not None and type(event["same_focus"]) is not bool:
			raise ValueError("Invalid routing focus comparison")
		for field, maximum in (("index", 1023), ("offset", 8192)):
			if event[field] is not None and (
				type(event[field]) is not int or not 0 <= event[field] <= maximum
			):
				raise ValueError("Invalid routing position")
		previousTime = event["elapsed_ms"]
		events.append(dict(event))
	return {**value, "events": events}


class RoutingTraceRecorder:
	"""Collect at most twelve events during separately selected, active consent."""

	def __init__(self, authorized: Callable[[], bool], *, clock: Callable[[], float] = time.monotonic):
		self._authorized = authorized
		self._clock = clock
		self._lock = threading.RLock()
		self._enabled = False
		self._started = 0.0
		self._events: list[dict[str, Any]] = []
		self._dropped = 0

	def clear(self) -> None:
		with self._lock:
			self._enabled = False
			self._events.clear()
			self._dropped = 0

	def start(self, *, enabled: bool) -> None:
		with self._lock:
			self.clear()
			if enabled is not True:
				return
			try:
				self._started = self._clock()
			except Exception:
				return
			self._enabled = True

	def active(self) -> bool:
		with self._lock:
			try:
				live = self._enabled and self._authorized() is True
			except Exception:
				live = False
			if not live:
				self.clear()
			return live

	def record(self, event: str, **fields: Any) -> None:
		with self._lock:
			if not self.active():
				return
			if len(self._events) >= TRACE_LIMIT:
				self.noteDropped()
				return
			try:
				elapsed = round((self._clock() - self._started) * 1000)
				candidate = {
					"seq": len(self._events) + 1,
					"elapsed_ms": elapsed,
					"event": event,
					**fields,
				}
				snapshot = {
					"schema_version": 1,
					"available": True,
					"snapshot_ms": elapsed,
					"limit": TRACE_LIMIT,
					"dropped": self._dropped,
					"events": [*self._events, candidate],
				}
				sanitizeRoutingTrace(snapshot)
			except Exception:
				self.noteDropped()
				return
			if self.active():
				self._events.append(candidate)

	def noteDropped(self) -> None:
		"""Disclose overflow or an unrecordable event without retaining exception data."""
		with self._lock:
			if self.active():
				self._dropped = min(self._dropped + 1, _MAX_COUNT)

	def snapshot(self) -> dict[str, Any]:
		with self._lock:
			if not self.active():
				return emptyTrace()
			try:
				elapsed = round((self._clock() - self._started) * 1000)
				if not 0 <= elapsed <= 300_000:
					raise ValueError("Invalid routing snapshot time")
			except Exception:
				self.clear()
				return emptyTrace()
			if not self.active():
				return emptyTrace()
			return sanitizeRoutingTrace(
				{
					"schema_version": 1,
					"available": True,
					"snapshot_ms": elapsed,
					"limit": TRACE_LIMIT,
					"dropped": self._dropped,
					"events": self._events,
				}
			)
