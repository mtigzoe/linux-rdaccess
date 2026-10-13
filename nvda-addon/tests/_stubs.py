# Derived from RDAccess tests/_stubs.py, Copyright 2026 Leonard de Ruijter.
# Extracted and reduced for linux-rdaccess on 2026-10-12. GPL-2.0-or-later.
"""Stub leaf runtime modules; use the real NVDA extensionPoints implementation."""

from __future__ import annotations

import gettext
import sys
import types
from unittest import mock


def install():
	gettext.NullTranslations().install()
	log = types.ModuleType("logHandler")
	log.log = mock.Mock()
	sys.modules["logHandler"] = log
	config = types.ModuleType("config")
	config.conf = {}
	sys.modules["config"] = config
	state = types.ModuleType("NVDAState")
	state._allowDeprecatedAPI = lambda: False
	sys.modules["NVDAState"] = state
	garbage = types.ModuleType("garbageHandler")
	garbage.TrackedObject = type("TrackedObject", (), {})
	sys.modules["garbageHandler"] = garbage
	addon = types.ModuleType("addonHandler")
	addon.initTranslation = lambda: None
	sys.modules["addonHandler"] = addon
	queue = types.ModuleType("queueHandler")
	queue.eventQueue = object()
	queue.queuedFunctions = []

	def queueFunction(eventQueue, function, *args, **kwargs):
		queue.queuedFunctions.append((eventQueue, function, args, kwargs))

	def pumpAll():
		while queue.queuedFunctions:
			_eventQueue, function, args, kwargs = queue.queuedFunctions.pop(0)
			function(*args, **kwargs)

	queue.queueFunction = queueFunction
	queue.pumpAll = pumpAll
	sys.modules["queueHandler"] = queue
	braille = types.ModuleType("braille")
	braille.handler = None
	sys.modules["braille"] = braille
	sys.modules["inputCore"] = types.ModuleType("inputCore")
