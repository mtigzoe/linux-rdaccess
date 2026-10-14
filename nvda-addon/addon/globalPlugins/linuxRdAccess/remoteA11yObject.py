# Extracted for linux-rdaccess on 2026-10-12; original GPL-2.0-or-later license retained.
# RDAccess: Remote Desktop Accessibility for NVDA
# Copyright 2026
# License: GNU General Public License version 2.0 or later

from __future__ import annotations

import typing

import braille
import controlTypes
import NVDAObjects

from . import a11y

_ROLE_MAP = {
	"application": controlTypes.Role.APPLICATION,
	"check box": controlTypes.Role.CHECKBOX,
	"combo box": controlTypes.Role.COMBOBOX,
	"dialog": controlTypes.Role.DIALOG,
	"heading": controlTypes.Role.HEADING,
	"label": controlTypes.Role.LABEL,
	"link": controlTypes.Role.LINK,
	"list": controlTypes.Role.LIST,
	"list item": controlTypes.Role.LISTITEM,
	"menu item": controlTypes.Role.MENUITEM,
	"page tab": controlTypes.Role.TAB,
	"page tab list": controlTypes.Role.TABCONTROL,
	"paragraph": controlTypes.Role.PARAGRAPH,
	"progress bar": controlTypes.Role.PROGRESSBAR,
	"push button": controlTypes.Role.BUTTON,
	"radio button": controlTypes.Role.RADIOBUTTON,
	"slider": controlTypes.Role.SLIDER,
	"table": controlTypes.Role.TABLE,
	"table cell": controlTypes.Role.TABLECELL,
	"terminal": controlTypes.Role.TERMINAL,
	"text": controlTypes.Role.EDITABLETEXT,
	"tree": controlTypes.Role.TREEVIEW,
	"tree item": controlTypes.Role.TREEVIEWITEM,
	"window": controlTypes.Role.WINDOW,
}

_STATE_MAP = {
	"checked": controlTypes.State.CHECKED,
	"collapsed": controlTypes.State.COLLAPSED,
	"expanded": controlTypes.State.EXPANDED,
	"focusable": controlTypes.State.FOCUSABLE,
	"focused": controlTypes.State.FOCUSED,
	"half checked": controlTypes.State.HALFCHECKED,
	"read only": controlTypes.State.READONLY,
	"selected": controlTypes.State.SELECTED,
}


class RemoteA11yTextInfo(NVDAObjects.NVDAObjectTextInfo):
	@property
	def _remoteObj(self) -> RemoteA11yObject:
		return typing.cast("RemoteA11yObject", self.obj)

	def _getStoryText(self) -> str:
		obj = self._remoteObj
		return obj._node.text if obj._node.textSupported else obj._get_basicText()

	def _getCaretOffset(self) -> int:
		obj = self._remoteObj
		offset = obj._node.caretOffset
		if not obj._node.textSupported or offset is None:
			raise NotImplementedError
		return offset

	def _getSelectionOffsets(self) -> tuple[int, int]:
		node = self._remoteObj._node
		if not node.textSupported:
			raise NotImplementedError
		if node.selectionStart is not None and node.selectionEnd is not None:
			return node.selectionStart, node.selectionEnd
		if node.caretOffset is not None:
			return node.caretOffset, node.caretOffset
		raise NotImplementedError

	def _setCaretOffset(self, offset: int) -> None:
		obj = self._remoteObj
		if (
			obj._caretSender is None
			or not obj._node.textSupported
			or type(offset) is not int
			or not 0 <= offset <= len(obj._node.text)
		):
			obj._observeRouting("caret_rejected")
			raise NotImplementedError
		obj._observeRouting("caret_attempted", offset=offset)
		obj._caretSender(obj._node.nodeId, offset)

	def activate(self):
		self._remoteObj._observeRouting("activation_attempted")
		return super().activate()

	def allowMoveToUnitOffsetPastEnd(self, unit: str) -> bool:  # noqa: ARG002
		return self._remoteObj._node.textSupported


class RemoteA11yObject(NVDAObjects.NVDAObject):
	TextInfo = RemoteA11yTextInfo

	@classmethod
	def findBestAPIClass(cls, kwargs, relation=None):  # noqa: ARG003
		return cls

	def __init__(
		self,
		*,
		processID: int,
		node: a11y.A11yNode,
		parentObject: NVDAObjects.NVDAObject | None,
		objectMap: dict[str, RemoteA11yObject],
		actionSender: typing.Callable[[str, int], None],
		caretSender: typing.Callable[[str, int], None] | None = None,
		routingObserver: typing.Callable[..., None] | None = None,
		session: int = 0,
	):
		super().__init__()
		self._session = session
		self._remoteProcessID = processID
		self._node = node
		self._parentObject = parentObject
		self._objectMap = objectMap
		self._actionSender = actionSender
		self._caretSender = caretSender
		self._routingObserver = routingObserver
		self.remoteBounds = node.bounds
		self.remoteTextTruncated = node.textTruncated

	def _observeRouting(self, event, **fields):
		try:
			if self._routingObserver is not None:
				self._routingObserver(event, **fields)
		except Exception:
			pass

	def _get_processID(self) -> int:
		return self._remoteProcessID

	def _isEqual(self, other: NVDAObjects.NVDAObject) -> bool:
		# NVDAObject.__eq__ treats any two objects of the same class as equal unless this says otherwise.
		# NVDA's api.setFocusObject() relies on == to work out which focus ancestors changed, so without
		# this every remote object would look identical to the previous one, and an object rebuilt after
		# a reconnect would be mistaken for the one from the dead session.
		return (
			isinstance(other, RemoteA11yObject)
			and self._session == other._session
			and self._remoteProcessID == other._remoteProcessID
			and self._node.nodeId == other._node.nodeId
		)

	def event_textChange(self) -> None:
		# Plain NVDAObjects do not refresh braille when their text changes.
		if braille.handler is not None:
			braille.handler.handleUpdate(self)

	def _get_basicText(self) -> str:
		if self._node.textSupported:
			return self._node.text
		return super()._get_basicText()

	def _get_name(self) -> str:
		return self._node.name

	def _get_description(self) -> str:
		return self._node.description

	def _get_value(self) -> str:
		return self._node.value

	def _get_role(self) -> controlTypes.Role:
		return _ROLE_MAP.get(self._node.role, controlTypes.Role.UNKNOWN)

	def _get_roleText(self) -> str | None:
		if self.role is controlTypes.Role.UNKNOWN and self._node.role:
			return self._node.role
		return None

	def _get_states(self) -> set[controlTypes.State]:
		return {_STATE_MAP[state] for state in self._node.states if state in _STATE_MAP}

	def _get_parent(self) -> NVDAObjects.NVDAObject | None:
		return self._parentObject

	def _get_firstChild(self) -> NVDAObjects.NVDAObject | None:
		if not self._node.childIds:
			return None
		return self._objectMap.get(self._node.childIds[0])

	def _get_lastChild(self) -> NVDAObjects.NVDAObject | None:
		if not self._node.childIds:
			return None
		return self._objectMap.get(self._node.childIds[-1])

	def _sibling(self, offset: int) -> NVDAObjects.NVDAObject | None:
		parent = self._parentObject
		if not isinstance(parent, RemoteA11yObject):
			return None
		try:
			index = parent._node.childIds.index(self._node.nodeId)
		except ValueError:
			return None
		targetIndex = index + offset
		if targetIndex < 0 or targetIndex >= len(parent._node.childIds):
			return None
		return self._objectMap.get(parent._node.childIds[targetIndex])

	def _get_previous(self) -> NVDAObjects.NVDAObject | None:
		return self._sibling(-1)

	def _get_next(self) -> NVDAObjects.NVDAObject | None:
		return self._sibling(1)

	# NVDA Simple Review Mode normally filters the object tree by
	# presentationType. Remote AT-SPI snapshots are already intentionally
	# bounded and should preserve their exact semantic relationships.
	def _get_simpleParent(self) -> NVDAObjects.NVDAObject | None:
		return self.parent

	def _get_simpleFirstChild(self) -> NVDAObjects.NVDAObject | None:
		return self.firstChild

	def _get_simpleLastChild(self) -> NVDAObjects.NVDAObject | None:
		return self.lastChild

	def _get_simplePrevious(self) -> NVDAObjects.NVDAObject | None:
		return self.previous

	def _get_simpleNext(self) -> NVDAObjects.NVDAObject | None:
		return self.next

	def _get_actionCount(self) -> int:
		return len(self._node.actionNames)

	def _normalizeActionIndex(self, index: int | None) -> int:
		if index is None:
			index = 0
		if type(index) is not int or index < 0 or index >= len(self._node.actionNames):
			raise IndexError("remote accessibility action index out of range")
		return index

	def getActionName(self, index=None):
		return self._node.actionNames[self._normalizeActionIndex(index)]

	def doAction(self, index=None):
		actionIndex = self._normalizeActionIndex(index)
		self._observeRouting("activation_attempted")
		self._actionSender(self._node.nodeId, actionIndex)

	def _get_location(self):
		# Linux screen coordinates are not Windows desktop coordinates.
		return None
