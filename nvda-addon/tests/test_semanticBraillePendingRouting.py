# License: GNU General Public License version 2 or later.
from __future__ import annotations

import ast
import sys
import types
from unittest import mock

import braille
import queueHandler

from tests import NVDA_SOURCE
from tests.test_remoteAccessSemanticBraille import (
	FakeBrailleHandler,
	SemanticBrailleBridgeTestCase,
)
from tests.test_semanticBrailleMessageRestoration import coreQueuedGestureMethods


class PendingRegion:
	def __init__(self, obj, textInfoClass):
		self.obj = obj
		self.textInfoClass = textInfoClass
		self.pendingCaretUpdate = False
		self.update()

	def update(self):
		self.readingInfo = self.textInfoClass(self.obj)

	def routeTo(self, offset):
		# Stock TextInfoRegion._setCursor calls TextInfo.updateCaret, whose
		# offset implementation reaches this production remote caret setter.
		self.readingInfo._setCaretOffset(offset)


class PendingBuffer:
	def __init__(self):
		self.regions = []
		self.window = 4

	@property
	def visibleRegions(self):
		return self.regions

	def saveWindow(self):
		self.savedWindow = self.window

	def restoreWindow(self):
		self.window = self.savedWindow

	def update(self):
		pass


def corePendingMethods():
	"""Use NVDA's real deferred update methods, with presentation dependencies stubbed."""
	path = NVDA_SOURCE / "braille" / "brailleHandler.py"
	if not path.exists():
		path = NVDA_SOURCE / "braille.py"
	tree = ast.parse(path.read_text(encoding="utf-8"))
	cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BrailleHandler")
	names = {"handleUpdate", "handleCaretMove", "_handlePendingUpdate"}
	methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
	if {node.name for node in methods} != names:
		raise AssertionError("NVDA deferred braille update API changed")
	namespace = {
		"objectBelowLockScreenAndWindowsIsLocked": lambda _obj: False,
		"TextInfoRegion": PendingRegion,
		"config": types.SimpleNamespace(conf={"braille": {"mode": "followCursors"}}),
		"BrailleMode": types.SimpleNamespace(SPEECH_OUTPUT=types.SimpleNamespace(value="speechOutput")),
		"TetherTo": types.SimpleNamespace(
			FOCUS=types.SimpleNamespace(value="focus"), REVIEW=types.SimpleNamespace(value="review")
		),
	}
	module = ast.Module(
		body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods],
		type_ignores=[],
	)
	exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
	return {name: namespace[name] for name in names}


class PendingRoutingTests(SemanticBrailleBridgeTestCase):
	def setUp(self):
		super().setUp()
		textInfoClass = self.module.RemoteA11yObject.TextInfo
		methods = corePendingMethods()

		class PendingHandler(FakeBrailleHandler):
			enabled = True

			def __init__(self):
				super().__init__()
				self.mainBuffer = PendingBuffer()
				self.buffer = self.mainBuffer
				self._regionsPendingUpdate = set()
				self.flushes = 0
				self._tether = "focus"

			def handleGainFocus(self, obj):
				self.focused.append(obj)
				self.mainBuffer.regions = [PendingRegion(obj, textInfoClass)]

			def update(self):
				self.flushes += 1

			def setTether(self, tether, auto=False):
				self._tether = tether

			def scrollToCursorOrSelection(self, region):
				pass

			def _handlePendingUpdate(self):
				methods["_handlePendingUpdate"](self)

			handleUpdate = methods["handleUpdate"]
			handleCaretMove = methods["handleCaretMove"]

		self.brailleHandler = PendingHandler()
		braille.handler = self.brailleHandler
		interceptors = types.ModuleType("treeInterceptorHandler")
		interceptors.TreeInterceptor = type("TreeInterceptor", (), {})
		patcher = mock.patch.dict(sys.modules, {"treeInterceptorHandler": interceptors})
		patcher.start()
		self.addCleanup(patcher.stop)
		self.negotiate()
		self.sendFocus(text="alpha bravo charlie", caret=19)

	def _routeBeforeIdle(self, offset=6):
		handler = self.brailleHandler

		class Commands:
			def __getattr__(self, name):
				return object()

			def script_braille_routeTo(self, gesture):
				handler.mainBuffer.regions[-1].routeTo(gesture.routingIndex)

		commands = Commands()
		module = types.ModuleType("globalCommands")
		module.commands = commands
		gesture = types.SimpleNamespace(script=commands.script_braille_routeTo, routingIndex=offset)
		execute, queued = coreQueuedGestureMethods()
		gesture.executeScript = types.MethodType(execute, gesture)
		with mock.patch.dict(sys.modules, {"globalCommands": module}):
			self.assertTrue(self.bridge._handleSemanticBrailleGesture(gesture))
			queueHandler.queueFunction(queueHandler.eventQueue, queued, gesture.script, gesture)
			queueHandler.pumpAll()

	def test_routing_between_same_id_snapshot_and_idle_refresh_sends_current_caret(self):
		region = self.brailleHandler.mainBuffer.regions[-1]
		retainedInfo = region.readingInfo
		self.sendFocus(text="alpha bravo charlie", caret=19)
		self.assertIsNot(region.obj, retainedInfo.obj)
		self.assertIs(region.readingInfo, retainedInfo)
		self.assertIn(region, self.brailleHandler._regionsPendingUpdate)
		self._routeBeforeIdle()
		self.assertEqual(
			self.transport.sent[-1],
			{"type": "lrd_a11y_caret", "version": 1, "object_id": "save", "offset": 6},
		)
		self.assertEqual(self.brailleHandler.flushes, 1)
		self.assertEqual(self.brailleHandler.mainBuffer.window, 4)
		self.assertEqual(self.brailleHandler._regionsPendingUpdate, set())
		before = list(self.transport.sent)
		retainedInfo._setCaretOffset(7)
		self.assertEqual(self.transport.sent, before, "Retained old TextInfo must remain invalid")

	def test_routing_after_changed_caret_refreshes_before_idle(self):
		region = self.brailleHandler.mainBuffer.regions[-1]
		oldInfo = region.readingInfo
		self.sendFocus(text="alpha bravo charlie", caret=18)
		self.assertTrue(region.pendingCaretUpdate)
		self.assertIs(region.readingInfo, oldInfo)
		self._routeBeforeIdle()
		self.assertEqual(self.transport.sent[-1]["type"], "lrd_a11y_caret")
		self.assertEqual(self.transport.sent[-1]["offset"], 6)
		self.assertIs(region.readingInfo.obj, region.obj)
		self.assertFalse(region.pendingCaretUpdate)

	def test_message_buffer_does_not_flush_or_route_underlying_focus(self):
		self.sendFocus(text="alpha bravo charlie", caret=19)
		self.brailleHandler.buffer = object()
		before = list(self.transport.sent)
		self.bridge._recoverFocusBeforeGesture(self.bridge._session, self.bridge._controlGeneration)
		self.assertEqual(self.brailleHandler.flushes, 0)
		self.assertEqual(self.transport.sent, before)
		self.assertTrue(self.brailleHandler._regionsPendingUpdate)

	def test_stale_control_generation_does_not_flush(self):
		self.sendFocus(text="alpha bravo charlie", caret=19)
		generation = self.bridge._controlGeneration
		self.bridge._controlGeneration += 1
		self.bridge._recoverFocusBeforeGesture(self.bridge._session, generation)
		self.assertEqual(self.brailleHandler.flushes, 0)
		self.assertTrue(self.brailleHandler._regionsPendingUpdate)

	def test_return_to_local_control_does_not_flush(self):
		self.sendFocus(text="alpha bravo charlie", caret=19)
		self.bridge._client = types.SimpleNamespace(leaderTransport=self.transport, sendingKeys=False)
		self.bridge._recoverFocusBeforeGesture(self.bridge._session, self.bridge._controlGeneration)
		self.assertEqual(self.brailleHandler.flushes, 0)
		self.assertTrue(self.brailleHandler._regionsPendingUpdate)
		self.bridge._client = None

	def test_disconnected_transport_does_not_flush(self):
		self.sendFocus(text="alpha bravo charlie", caret=19)
		self.transport.connected = False
		self.bridge._recoverFocusBeforeGesture(self.bridge._session, self.bridge._controlGeneration)
		self.assertEqual(self.brailleHandler.flushes, 0)
		self.assertTrue(self.brailleHandler._regionsPendingUpdate)

	def test_stale_session_does_not_flush(self):
		self.sendFocus(text="alpha bravo charlie", caret=19)
		self.bridge._recoverFocusBeforeGesture(self.bridge._session - 1, self.bridge._controlGeneration)
		self.assertEqual(self.brailleHandler.flushes, 0)
		self.assertTrue(self.brailleHandler._regionsPendingUpdate)
