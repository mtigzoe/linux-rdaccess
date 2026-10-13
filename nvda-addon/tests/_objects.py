# Extracted for linux-rdaccess on 2026-10-12; original GPL-2.0-or-later license retained.
from __future__ import annotations

import enum
import importlib
import importlib.util
import sys
import types


class Role(enum.Enum):
	UNKNOWN = enum.auto()
	APPLICATION = enum.auto()
	CHECKBOX = enum.auto()
	COMBOBOX = enum.auto()
	DIALOG = enum.auto()
	HEADING = enum.auto()
	LABEL = enum.auto()
	LINK = enum.auto()
	LIST = enum.auto()
	LISTITEM = enum.auto()
	MENUITEM = enum.auto()
	TAB = enum.auto()
	TABCONTROL = enum.auto()
	PARAGRAPH = enum.auto()
	PROGRESSBAR = enum.auto()
	BUTTON = enum.auto()
	RADIOBUTTON = enum.auto()
	SLIDER = enum.auto()
	TABLE = enum.auto()
	TABLECELL = enum.auto()
	TERMINAL = enum.auto()
	EDITABLETEXT = enum.auto()
	TREEVIEW = enum.auto()
	TREEVIEWITEM = enum.auto()
	WINDOW = enum.auto()


class State(enum.Enum):
	CHECKED = enum.auto()
	COLLAPSED = enum.auto()
	EXPANDED = enum.auto()
	FOCUSABLE = enum.auto()
	FOCUSED = enum.auto()
	HALFCHECKED = enum.auto()
	READONLY = enum.auto()
	SELECTED = enum.auto()


class FakeNVDAObject:
	@classmethod
	def findBestAPIClass(cls, kwargs, relation=None):  # noqa: ARG003
		return cls

	def __init__(self, *args, **kwargs):
		pass

	def _isEqual(self, other):
		# Same default as NVDAObjects.NVDAObject._isEqual: NVDA's __eq__ treats two objects of the
		# same type as equal unless a subclass says otherwise.
		return True

	@property
	def processID(self):
		getter = getattr(self, "_get_processID", None)
		return getter() if getter else 0

	@property
	def name(self):
		getter = getattr(self, "_get_name", None)
		return getter() if getter else ""

	@property
	def description(self):
		getter = getattr(self, "_get_description", None)
		return getter() if getter else ""

	@property
	def value(self):
		getter = getattr(self, "_get_value", None)
		return getter() if getter else ""

	@property
	def role(self):
		getter = getattr(self, "_get_role", None)
		return getter() if getter else Role.UNKNOWN

	@property
	def roleText(self):
		getter = getattr(self, "_get_roleText", None)
		return getter() if getter else None

	@property
	def states(self):
		getter = getattr(self, "_get_states", None)
		return getter() if getter else set()

	@property
	def parent(self):
		getter = getattr(self, "_get_parent", None)
		return getter() if getter else None

	@property
	def firstChild(self):
		getter = getattr(self, "_get_firstChild", None)
		return getter() if getter else None

	@property
	def lastChild(self):
		getter = getattr(self, "_get_lastChild", None)
		return getter() if getter else None

	@property
	def previous(self):
		getter = getattr(self, "_get_previous", None)
		return getter() if getter else None

	@property
	def next(self):
		getter = getattr(self, "_get_next", None)
		return getter() if getter else None


class FakeNVDAObjectTextInfo:
	def __init__(self, obj, position=None):
		self.obj = obj
		self.position = position


class HostObject(FakeNVDAObject):
	def __init__(self, process_id):
		self._process_id = process_id

	def _get_processID(self):
		return self._process_id


def install_handler_runtime_stubs():
	control_types = types.ModuleType("controlTypes")
	control_types.Role = Role
	control_types.State = State
	sys.modules["controlTypes"] = control_types

	nvda_objects = types.ModuleType("NVDAObjects")
	nvda_objects.NVDAObject = FakeNVDAObject
	nvda_objects.NVDAObjectTextInfo = FakeNVDAObjectTextInfo
	sys.modules["NVDAObjects"] = nvda_objects

	api = types.ModuleType("api")
	api.focusObject = HostObject(4242)
	api.getFocusObject = lambda: api.focusObject
	sys.modules["api"] = api

	event_handler = types.ModuleType("eventHandler")
	event_handler.events = []

	def executeEvent(name, obj):
		event_handler.events.append((name, obj))
		api.focusObject = obj

	event_handler.executeEvent = executeEvent
	sys.modules["eventHandler"] = event_handler

	a11y = importlib.import_module("_linux_rdaccess_addon_tests.a11y")
	return api, event_handler, a11y


def load_handler_module():
	from tests import PLUGIN_ROOT

	name = "_linux_rdaccess_addon_tests.remoteA11yObject"
	spec = importlib.util.spec_from_file_location(name, PLUGIN_ROOT / "remoteA11yObject.py")
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module
