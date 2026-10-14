# License: GNU General Public License version 2 or later.
"""Transparent observation of native routing; never execute or retry a route."""

from __future__ import annotations

import contextlib
from contextvars import ContextVar

import braille


def _noop():
	pass


def _replace(target, name, installed):
	"""Restore only our own wrapper, including the original absence of a shadow."""
	original = getattr(target, name)
	hadOwn = name in getattr(target, "__dict__", {})
	setattr(target, name, installed)

	def restore():
		with contextlib.suppress(Exception):
			if getattr(target, name) is installed:
				if hadOwn:
					setattr(target, name, original)
				else:
					delattr(target, name)

	return restore


class NativeRoutingObserver:
	def __init__(self, active, emit):
		self._active = active
		self._emit = emit
		self._context = ContextVar("linuxRdAccessRoutingObservation", default=None)
		self._handler = None
		self._restore = None

	def index(self):
		context = self._context.get()
		return context["index"] if context is not None else None

	def mark(self, event):
		context = self._context.get()
		if context is not None and event != "native_delegated":
			context["observed"] = True

	def inRoute(self):
		return self._context.get() is not None

	def close(self):
		if self._restore is not None:
			self._restore()
		self._restore = self._handler = None

	def install(self, handler):
		try:
			if not self._active():
				return
			if handler is self._handler:
				return
			self.close()
			original = handler.routeTo

			def observe(index, *args, **kwargs):
				try:
					active = self._active()
				except Exception:
					active = False
				if not active:
					return original(index, *args, **kwargs)
				context = {"index": index, "observed": False}
				token = self._context.set(context)
				restore = _noop
				with contextlib.suppress(Exception):
					restore = self._observeBuffer(getattr(handler, "buffer", None))
				try:
					return original(index, *args, **kwargs)
				finally:
					with contextlib.suppress(Exception):
						restore()
					if not context["observed"]:
						self._notify("outcome_unknown")
					with contextlib.suppress(Exception):
						self._context.reset(token)

			self._restore = _replace(handler, "routeTo", observe)
			self._handler = handler
		except Exception:
			self._notify("outcome_unknown")

	def _notify(self, event):
		with contextlib.suppress(Exception):
			self.mark(event)
			self._emit(event, index=self.index())

	def _observeBuffer(self, buffer):
		# Inspect the result of the actual conversion, never call it a second time.
		# Only stock buffers establish the NVDA 2026.2/pinned-reference branch;
		# custom implementations remain unknown unless another effect is observed.
		try:
			cls = getattr(braille, "BrailleBuffer", None)
			if type(buffer) is not cls or getattr(buffer.routeTo, "__func__", None) is not cls.routeTo:
				return lambda: None
			if cls.routeTo.__module__ not in ("braille", "braille.buffers"):
				return lambda: None
			original = buffer.windowPosToBufferPos
			if getattr(original, "__func__", None) is not cls.windowPosToBufferPos:
				return lambda: None
			if cls.windowPosToBufferPos.__module__ not in ("braille", "braille.buffers"):
				return lambda: None

			def convert(*args, **kwargs):
				position = original(*args, **kwargs)
				try:
					if position >= buffer.windowEndPos:
						self._notify("outside_buffer")
				except Exception:
					pass
				return position

			return _replace(buffer, "windowPosToBufferPos", convert)
		except Exception:
			return lambda: None
