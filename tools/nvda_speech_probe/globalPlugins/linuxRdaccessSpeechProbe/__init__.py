# Linux RDAccess NVDA speech probe
# Opt-in live-test helper. Speech is sent only while explicitly enabled.
from __future__ import annotations

import json
import queue
import socket
import threading

import globalPluginHandler
import ui
from speech.extensions import pre_speechQueued

from .shared import build_event

PROBE_HOST = "127.0.0.1"
PROBE_PORT = 8765
_QUEUE_LIMIT = 64
_STOP = object()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""Opt-in diagnostic bridge from Windows NVDA speech to the Linux test harness."""

	scriptCategory = "Linux RDAccess diagnostics"
	__gestures = {
		"kb:NVDA+control+shift+f12": "toggleSpeechProbe",
	}

	def __init__(self):
		super().__init__()
		self._enabled = False
		self._suppressNext = False
		self._sequence = 0
		self._queue = queue.Queue(maxsize=_QUEUE_LIMIT)
		self._worker = threading.Thread(
			target=self._senderLoop,
			name="LinuxRDAccessSpeechProbe",
			daemon=True,
		)
		self._worker.start()
		pre_speechQueued.register(self._onSpeechQueued)

	def terminate(self):
		pre_speechQueued.unregister(self._onSpeechQueued)
		self._enabled = False
		self._discardQueuedSpeech()
		try:
			self._queue.put_nowait(_STOP)
		except queue.Full:
			pass
		super().terminate()

	def script_toggleSpeechProbe(self, gesture):  # noqa: ARG002
		"""Toggle forwarding queued NVDA speech to the Linux live-test receiver."""
		self._enabled = not self._enabled
		if self._enabled:
			# Do not report the probe's own confirmation announcement.
			self._suppressNext = True
			ui.message("Linux RDAccess speech probe enabled")
		else:
			self._suppressNext = False
			self._discardQueuedSpeech()
			ui.message("Linux RDAccess speech probe disabled")

	def _discardQueuedSpeech(self):
		while True:
			try:
				self._queue.get_nowait()
			except queue.Empty:
				return

	def _onSpeechQueued(self, speechSequence, priority=None, **kwargs):  # noqa: ARG002
		if not self._enabled:
			return
		if self._suppressNext:
			self._suppressNext = False
			return
		self._sequence += 1
		payload = build_event(speechSequence, self._sequence)
		if payload is None:
			return
		try:
			self._queue.put_nowait(payload)
		except queue.Full:
			# The probe must never block NVDA's speech path.
			return

	def _senderLoop(self):
		while True:
			item = self._queue.get()
			if item is _STOP:
				return
			if not isinstance(item, dict):
				continue
			try:
				data = (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
				with socket.create_connection((PROBE_HOST, PROBE_PORT), timeout=0.25) as connection:
					connection.settimeout(0.25)
					connection.sendall(data)
			except OSError:
				# Listener absent/tunnel closed: drop the diagnostic event silently.
				continue
