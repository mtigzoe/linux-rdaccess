# License: GNU General Public License version 2 or later.
from __future__ import annotations

import ast
import importlib
import json
import types
import weakref
from unittest import mock

import braille
import inputCore
import queueHandler

from tests import NVDA_SOURCE
from tests._objects import HostObject
from tests.test_remoteAccessSemanticBraille import FakeBrailleHandler, SemanticBrailleBridgeTestCase


class Buffer:
	def __init__(self):
		self.regions = []
		self.window = 0

	def clear(self):
		self.regions.clear()

	def update(self):
		pass

	def routeTo(self, index):
		pass

	def scrollBack(self):
		self.window = max(0, self.window - 1)

	def scrollForward(self):
		self.window += 1


class TextRegion:
	def __init__(self, text):
		self.text = text

	def update(self):
		pass


class Timer:
	def __init__(self, timeout, callback):
		self.timeout = timeout
		self.callback = callback
		self.stopped = False
		self.restarts = 0

	def Restart(self, timeout):
		self.timeout = timeout
		self.restarts += 1

	def Stop(self):
		self.stopped = True


def coreMessageMethods():
	path = NVDA_SOURCE / "braille" / "brailleHandler.py"
	if not path.exists():
		path = NVDA_SOURCE / "braille.py"
	tree = ast.parse(path.read_text(encoding="utf-8"))
	cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BrailleHandler")
	names = {"message", "_resetMessageTimer", "_dismissMessage", "routeTo", "scrollBack", "scrollForward"}
	methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
	if {node.name for node in methods} != names:
		raise AssertionError("NVDA message API changed")
	from extensionPoints import Action

	config = types.SimpleNamespace(
		conf={"braille": {"showMessages": 1, "mode": "followCursors", "messageTimeout": 4}}
	)
	namespace = {
		"config": config,
		"ShowMessages": types.SimpleNamespace(DISABLED=0, SHOW_INDEFINITELY=2),
		"BrailleMode": types.SimpleNamespace(SPEECH_OUTPUT=types.SimpleNamespace(value="speechOutput")),
		"_decide_disabledIncludesMessages": types.SimpleNamespace(decide=lambda: True),
		"_pre_showBrailleMessage": Action(),
		"_post_dismissBrailleMessage": Action(),
		"TextRegion": TextRegion,
		"keyboardHandler": types.SimpleNamespace(keyCounter=1),
		"wx": types.SimpleNamespace(CallLater=Timer),
	}
	module = ast.Module(
		body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods],
		type_ignores=[],
	)
	exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
	return {name: namespace[name] for name in names}, namespace


def coreRouteScript():
	path = NVDA_SOURCE / "globalCommands.py"
	tree = ast.parse(path.read_text(encoding="utf-8"))
	cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GlobalCommands")
	method = next(
		node
		for node in cls.body
		if isinstance(node, ast.FunctionDef) and node.name == "script_braille_routeTo"
	)
	method.decorator_list = []
	module = ast.Module(
		body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method],
		type_ignores=[],
	)
	namespace = {"braille": braille}
	exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
	return namespace[method.name]


def coreLocalMessageMethods():
	path = NVDA_SOURCE / "_remoteClient" / "localMachine.py"
	tree = ast.parse(path.read_text(encoding="utf-8"))
	cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LocalMachine")
	names = {"_handleShowBrailleMessage", "_handleDismissBrailleMessage", "_dismissLocalBrailleMessage"}
	methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
	if {node.name for node in methods} != names:
		raise AssertionError("NVDA Remote message API changed")
	namespace = {"braille": braille}
	module = ast.Module(
		body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods],
		type_ignores=[],
	)
	exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
	return {name: namespace[name] for name in names}


def coreQueuedGestureMethods():
	"""Use NVDA's real gesture execution entry and queued script callback."""
	namespace = {
		"scriptHandler": types.SimpleNamespace(executeScript=lambda script, gesture: script(gesture)),
		"_numScriptsQueued": 1,
		"_numIncompleteInterceptedCommandScripts": 0,
		"_isInterceptedCommandScript": lambda script: False,
	}
	for filename, className, methodName in (
		("inputCore.py", "InputGesture", "executeScript"),
		("scriptHandler.py", None, "_queueScriptCallback"),
	):
		path = NVDA_SOURCE / filename
		tree = ast.parse(path.read_text(encoding="utf-8"))
		body = tree.body
		if className:
			body = next(
				node for node in body if isinstance(node, ast.ClassDef) and node.name == className
			).body
		method = next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == methodName)
		module = ast.Module(body=[method], type_ignores=[])
		exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
	return namespace["executeScript"], namespace["_queueScriptCallback"]


def coreInputManagerExecute():
	path = NVDA_SOURCE / "inputCore.py"
	tree = ast.parse(path.read_text(encoding="utf-8"))
	cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "InputManager")
	method = next(
		node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "executeGesture"
	)
	_, queued = coreQueuedGestureMethods()

	def queue(eventQueue, function, *args, **kwargs):
		kwargs.pop("_immediate", None)
		queueHandler.queueFunction(eventQueue, function, *args, **kwargs)

	namespace = {
		"watchdog": types.SimpleNamespace(isAttemptingRecovery=False),
		"decide_executeGesture": types.SimpleNamespace(decide=lambda **kwargs: True),
		"api": types.SimpleNamespace(getFocusObject=lambda: types.SimpleNamespace(sleepMode=0, SLEEP_FULL=2)),
		"sayAll": types.SimpleNamespace(SayAllHandler=types.SimpleNamespace(isRunning=lambda: False)),
		"speech": types.SimpleNamespace(cancelSpeech=mock.Mock()),
		"queueHandler": types.SimpleNamespace(queueFunction=queue, eventQueue=queueHandler.eventQueue),
		"systemUtils": types.SimpleNamespace(preventSystemIdle=mock.Mock()),
		"log": types.SimpleNamespace(isEnabledFor=lambda level: False, IO=1),
		"config": types.SimpleNamespace(conf={"keyboard": {"speakCommandKeys": False}}),
		"scriptHandler": types.SimpleNamespace(
			_numIncompleteInterceptedCommandScripts=0,
			queueScript=lambda script, gesture: queue(queueHandler.eventQueue, queued, script, gesture),
		),
	}
	exec(
		compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"),
		namespace,
	)
	return namespace["executeGesture"], namespace


class MessageRestorationTests(SemanticBrailleBridgeTestCase):
	def setUp(self):
		super().setUp()
		methods, self.core = coreMessageMethods()

		class Handler(FakeBrailleHandler):
			enabled = True

			def __init__(self):
				super().__init__()
				self.mainBuffer = Buffer()
				self.messageBuffer = Buffer()
				self.buffer = self.mainBuffer
				self._messageCallLater = None
				self._autoScrollCallLater = None
				self.visibleRegions = []

			def handleGainFocus(self, obj):
				self.focused.append(obj)
				self.mainBuffer.regions = [types.SimpleNamespace(obj=obj)]
				if self.buffer is self.mainBuffer:
					self.update()

			def autoScroll(self, enable):
				pass

			def update(self):
				self.visibleRegions = list(self.buffer.regions)

			message = methods["message"]
			_resetMessageTimer = methods["_resetMessageTimer"]
			_dismissMessage = methods["_dismissMessage"]
			routeTo = methods["routeTo"]
			scrollBack = methods["scrollBack"]
			scrollForward = methods["scrollForward"]

		self.brailleHandler = Handler()
		braille.handler = self.brailleHandler
		self.bridge.terminate()
		for name in ("_pre_showBrailleMessage", "_post_dismissBrailleMessage"):
			patcher = mock.patch.object(braille, name, self.core[name], create=True)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.bridge = self.module.RemoteAccessSemanticBrailleBridge(self.transport)
		self.negotiate()
		self.sendFocus(text="abcdef", caret=6)

	def _sendMessage(self):
		self.transport.callback_manager.callbacks["msg_lrd_a11y_message"](version=1, text="Focus mode")
		queueHandler.pumpAll()

	def _startRoutingTrace(self):
		module = importlib.import_module(f"{self.module.__package__}.localTestRoutingTrace")
		self.routingTrace = module.RoutingTraceRecorder(lambda: True)
		self.routingTrace.start(enabled=True)
		self.bridge._routingTrace = self.routingTrace

	def test_routing_trace_distinguishes_guarded_dismissal_from_a_caret_request(self):
		self._startRoutingTrace()
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		queueHandler.pumpAll()
		events = self.routingTrace.snapshot()["events"]
		self.assertIn("route_guarded", [event["event"] for event in events])
		self.assertIn("message_dismissed", [event["event"] for event in events])
		self.assertNotIn("caret_sent", [event["event"] for event in events])
		route = next(event for event in events if event["event"] == "route_received")
		self.assertEqual(route["buffer"], "message")
		self.assertTrue(route["linux_owned"])
		encoded = json.dumps(self.routingTrace.snapshot())
		self.assertNotIn("Alpha Barlio Charlie", encoded)
		self.assertNotIn("Focus mode", encoded)

	def test_routing_trace_reports_expired_guard_as_discarded_without_a_caret_request(self):
		self._startRoutingTrace()
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		self.brailleHandler._messageCallLater.callback()
		queueHandler.pumpAll()
		events = [event["event"] for event in self.routingTrace.snapshot()["events"]]
		self.assertIn("route_discarded", events)
		self.assertNotIn("caret_sent", events)

	def test_routing_trace_reports_a_fresh_native_route_after_message_expiry(self):
		self._startRoutingTrace()
		self._prepareRouteableFocus()
		self._sendMessage()
		self.brailleHandler._messageCallLater.callback()
		self._queueRouteGesture()
		queueHandler.pumpAll()
		events = self.routingTrace.snapshot()["events"]
		self.assertIn("route_native", [event["event"] for event in events])
		caret = next(event for event in events if event["event"] == "caret_sent")
		self.assertEqual(caret["offset"], 13)

	def test_broken_diagnostics_cannot_change_native_message_routing(self):
		self.bridge._routingTrace = mock.Mock()
		self.bridge._routingTrace.active.side_effect = RuntimeError("PRIVATE diagnostic failure")
		self._prepareRouteableFocus()
		self._sendMessage()
		before = list(self.transport.sent)
		self._queueRouteGesture()
		queueHandler.pumpAll()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.mainBuffer)
		self.assertEqual(self.transport.sent, before)

	def _observeNativeRemoteDismissal(self):
		machine = type("Machine", (), coreLocalMessageMethods())()
		machine.receivingBraille = False
		machine._showingLocalUiMessage = False
		machine._lastCells = []
		machine.display = mock.Mock()
		for name, callback in (
			("_pre_showBrailleMessage", machine._handleShowBrailleMessage),
			("_post_dismissBrailleMessage", machine._handleDismissBrailleMessage),
		):
			self.core[name].register(callback)
			self.addCleanup(self.core[name].unregister, callback)
		client = types.SimpleNamespace(
			leaderTransport=self.transport,
			localMachine=machine,
			sendingKeys=True,
			setReceivingBraille=mock.Mock(),
			leaderSession=None,
		)
		original = machine._dismissLocalBrailleMessage
		with mock.patch.object(self.module, "_builtinRemoteState", return_value=(client, self.transport)):
			self.bridge._installBuiltInBrailleOwnership()
		return machine, original

	def test_trace_identifies_native_remote_dismissal_before_an_unguarded_route(self):
		machine, original = self._observeNativeRemoteDismissal()
		self._prepareRouteableFocus()
		self._startRoutingTrace()
		self._sendMessage()
		machine._dismissLocalBrailleMessage()
		self._queueRouteGesture(index=9)
		queueHandler.pumpAll()
		events = self.routingTrace.snapshot()["events"]
		names = [event["event"] for event in events]
		self.assertLess(names.index("remote_dismiss_called"), names.index("route_received"))
		before = next(event for event in events if event["event"] == "remote_dismiss_called")
		self.assertEqual(before["buffer"], "message")
		self.assertTrue(before["linux_owned"])
		self.assertIn("route_native", names)
		self.assertEqual(next(event for event in events if event["event"] == "caret_sent")["offset"], 9)
		self.bridge.terminate()
		self.assertIs(machine._dismissLocalBrailleMessage.__func__, original.__func__)
		self.assertIs(machine._dismissLocalBrailleMessage.__self__, original.__self__)

	def test_ending_observation_preserves_a_later_remote_message_wrapper(self):
		machine, _original = self._observeNativeRemoteDismissal()
		later = mock.Mock()
		machine._dismissLocalBrailleMessage = later
		self.bridge.terminate()
		self.assertIs(machine._dismissLocalBrailleMessage, later)

	def test_message_timeout_restores_linux_when_windows_replaced_main_buffer(self):
		self.brailleHandler.handleGainFocus(HostObject(4242))
		self._sendMessage()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
		timer = self.brailleHandler._messageCallLater
		self.assertIsNotNone(timer)
		timer.callback()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.mainBuffer)
		self.assertIsInstance(self.brailleHandler.visibleRegions[-1].obj, self.module.RemoteA11yObject)
		self.assertEqual(self.brailleHandler.visibleRegions[-1].obj._node.text, "abcdef")
		self.assertTrue(timer.stopped)

	def _replaceMainWithWindows(self):
		obj = HostObject(4242)
		self.brailleHandler.handleGainFocus(obj)
		return obj

	def test_intact_linux_region_and_pan_window_are_preserved(self):
		region = self.brailleHandler.mainBuffer.regions[-1]
		self.brailleHandler.mainBuffer.window = 4
		self._sendMessage()
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1], region)
		self.assertEqual(self.brailleHandler.mainBuffer.window, 4)
		self.assertEqual(len(self.brailleHandler.focused), 1)

	def test_routing_dismisses_message_without_remote_caret_or_action(self):
		self._sendMessage()
		self._replaceMainWithWindows()
		before = list(self.transport.sent)
		self.brailleHandler.routeTo(2)
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.mainBuffer)
		self.assertIsInstance(self.brailleHandler.visibleRegions[-1].obj, self.module.RemoteA11yObject)
		self.assertEqual(self.transport.sent, before)

	def _prepareRouteableFocus(self):
		self.sendFocus(text="Alpha Barlio Charlie", caret=6)

		def route(index):
			obj = self.brailleHandler.mainBuffer.regions[-1].obj
			obj.TextInfo(obj)._setCaretOffset(index)

		self.brailleHandler.mainBuffer.routeTo = mock.Mock(side_effect=route)
		self.brailleHandler.messageBuffer.routeTo = mock.Mock()

	def _queueRouteGesture(self, index=13, *, queueScript=True, legacy=False, cellIndexes=None):
		class Commands:
			def __getattr__(self, name):
				return object()

			script_braille_routeTo = coreRouteScript()

		commands = Commands()
		module = types.ModuleType("globalCommands")
		module.commands = commands
		gesture = types.SimpleNamespace(
			script=commands.script_braille_routeTo,
			cellIndexes=[index] if cellIndexes is None else cellIndexes,
			routingIndex=index,
		)
		execute, queued = coreQueuedGestureMethods()
		gesture.executeScript = types.MethodType(execute, gesture)
		self.routeGesture, self.routeOriginalScript = gesture, gesture.script
		if legacy:
			del gesture.cellIndexes
		with mock.patch.dict("sys.modules", {"globalCommands": module}):
			allowed = self.bridge._handleSemanticBrailleGesture(gesture)
			if allowed and queueScript:
				queueHandler.queueFunction(queueHandler.eventQueue, queued, gesture.script, gesture)
		return allowed

	def test_queued_main_route_still_routes_unchanged_focus(self):
		self._prepareRouteableFocus()
		self.assertTrue(self._queueRouteGesture(index=9))
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_called_once_with(9)
		self.assertEqual(self.transport.sent[-1]["offset"], 9)

	def test_queued_main_route_does_not_route_a_replacement_focus(self):
		self._prepareRouteableFocus()
		objects = self._objects(text="replacement text", caret=1)
		objects[0]["id"] = "replacement"
		objects[1]["child_ids"] = ["replacement"]
		self.bridge._onFocus(version=1, focus_id="replacement", objects=objects)
		before = list(self.transport.sent)
		self.assertTrue(self._queueRouteGesture(index=9))
		queueHandler.pumpAll()
		self.assertEqual(self.bridge._focusId, "replacement")
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		self.assertEqual(self.transport.sent, before)
		self._queueRouteGesture(index=2)
		queueHandler.pumpAll()
		self.assertEqual(self.transport.sent[-1]["object_id"], "replacement")
		self.assertEqual(self.transport.sent[-1]["offset"], 2)

	def test_queued_main_route_does_not_reinterpret_new_same_id_text(self):
		self._prepareRouteableFocus()
		self.bridge._onFocus(version=1, focus_id="save", objects=self._objects(text="new text", caret=1))
		before = list(self.transport.sent)
		self._queueRouteGesture(index=4)
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		self.assertEqual(self.transport.sent, before)

	def test_queued_main_route_expires_on_control_handoff(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9)
		self.bridge._controlGeneration += 1
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_queued_main_route_does_not_touch_a_replacement_handler(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9)
		other = type(self.brailleHandler)()
		other.mainBuffer.routeTo = mock.Mock()
		braille.handler = other
		queueHandler.pumpAll()
		other.mainBuffer.routeTo.assert_not_called()
		self.assertEqual(other.focused, [])

	def test_queued_main_route_does_not_dismiss_a_later_message(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9)
		self.brailleHandler.message("Later Windows status")
		queueHandler.pumpAll()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_queued_main_route_expires_on_disconnect(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9)
		self.transport.connected = False
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_queued_main_route_expires_on_new_session(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9)
		self.bridge._onHello(version=1)
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_queued_main_route_expires_on_termination(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9)
		self.bridge.terminate()
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_native_input_pipeline_preserves_capture_and_speech_effects(self):
		self._prepareRouteableFocus()
		self._queueRouteGesture(index=9, queueScript=False)
		gesture = self.routeGesture
		self.assertIs(gesture.script, self.routeOriginalScript)
		gesture.isModifier = False
		gesture.speechEffectWhenExecuted = gesture.SPEECHEFFECT_CANCEL = 1
		gesture.SPEECHEFFECT_PAUSE, gesture.SPEECHEFFECT_RESUME = 2, 3
		gesture.shouldPreventSystemIdle = True
		gesture.shouldReportAsCommand = False
		gesture.reportExtra = mock.Mock()
		self.brailleHandler.suppressClearBrailleRegions = lambda script: lambda callback: callback
		execute, namespace = coreInputManagerExecute()
		manager = types.SimpleNamespace(
			lastModifierWasInSayAll=False, _captureFunc=mock.Mock(return_value=False)
		)
		execute(manager, gesture)
		queueHandler.pumpAll()
		manager._captureFunc.assert_called_once_with(gesture)
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		namespace["speech"].cancelSpeech.assert_called_once_with()
		namespace["systemUtils"].preventSystemIdle.assert_called_once_with()
		# When capture permits execution, the same original native script and
		# queue callback still enter the guarded gesture execution hook.
		manager._captureFunc.return_value = True
		execute(manager, gesture)
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_called_once_with(9)
		self.assertIs(gesture.script, self.routeOriginalScript)

	def test_message_timeout_before_queued_routing_never_routes_underlying_linux_text(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		before = list(self.transport.sent)
		self._queueRouteGesture()
		# wx can deliver the timeout after the input-thread decision but before
		# the queued script. The physical press belonged to the visible message.
		self.brailleHandler._messageCallLater.callback()
		queueHandler.pumpAll()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		self.assertEqual(self.transport.sent, before)

	def test_visible_owned_message_route_uses_native_dismissal_without_remote_input(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		timer = self.brailleHandler._messageCallLater
		before = list(self.transport.sent)
		self.assertFalse(self._queueRouteGesture())
		queueHandler.pumpAll()
		self.brailleHandler.messageBuffer.routeTo.assert_called_once_with(13)
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.mainBuffer)
		self.assertTrue(timer.stopped)
		self.assertEqual(self.transport.sent, before)

	def test_two_presses_on_visible_message_do_not_route_after_first_dismissal(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		before = list(self.transport.sent)
		self._queueRouteGesture()
		self._queueRouteGesture()
		queueHandler.pumpAll()
		self.brailleHandler.messageBuffer.routeTo.assert_called_once_with(13)
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		self.assertEqual(self.transport.sent, before)

	def test_route_pressed_after_timeout_still_routes_current_linux_text(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self.brailleHandler._messageCallLater.callback()
		self.assertTrue(self._queueRouteGesture())
		queueHandler.pumpAll()
		self.assertEqual(
			self.transport.sent[-1],
			{"type": "lrd_a11y_caret", "version": 1, "object_id": "save", "offset": 13},
		)

	def test_later_linux_message_is_not_dismissed_by_queued_old_message_route(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		self.bridge._presentMessageOnMainThread(
			self.bridge._session, self.bridge._controlGeneration, "New message"
		)
		queueHandler.pumpAll()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
		self.assertEqual(self.brailleHandler.messageBuffer.regions[0].text, "New message")
		self.brailleHandler.messageBuffer.routeTo.assert_not_called()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_later_windows_message_is_not_dismissed_by_queued_linux_message_route(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		self.brailleHandler.message("Windows status")
		queueHandler.pumpAll()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
		self.assertEqual(self.brailleHandler.messageBuffer.regions[0].text, "Windows status")
		self.brailleHandler.messageBuffer.routeTo.assert_not_called()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_region_replacement_without_hooks_expires_queued_route_without_retaining_text(self):
		self.bridge._removeMessageHooks()
		self._prepareRouteableFocus()
		self._sendMessage()
		oldRegion = weakref.ref(self.brailleHandler.messageBuffer.regions[0])
		self._queueRouteGesture()
		self.brailleHandler.message("Windows status")
		self.assertIsNone(oldRegion(), "Queued routing must not keep expired message content alive")
		queueHandler.pumpAll()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
		self.brailleHandler.messageBuffer.routeTo.assert_not_called()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_empty_cell_indexes_keeps_native_api_behavior(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self.assertTrue(self._queueRouteGesture(cellIndexes=[]))
		queueHandler.pumpAll()
		if "cellIndexes" in coreRouteScript().__code__.co_names:
			self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
			self.brailleHandler.messageBuffer.routeTo.assert_not_called()
		else:
			# NVDA 2026.2's native script uses routingIndex and does not read
			# cellIndexes. Preserve that API rather than imposing a newer no-op.
			self.assertIs(self.brailleHandler.buffer, self.brailleHandler.mainBuffer)
			self.brailleHandler.messageBuffer.routeTo.assert_called_once_with(13)
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_legacy_routing_index_dismisses_owned_message(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self.assertFalse(self._queueRouteGesture(legacy=True, queueScript=False))
		queueHandler.pumpAll()
		self.brailleHandler.messageBuffer.routeTo.assert_called_once_with(13)
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def test_nvda_input_help_or_gesture_capture_keeps_native_execution(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		manager = types.SimpleNamespace(_captureFunc=object())
		with mock.patch.object(inputCore, "manager", manager, create=True):
			self.assertTrue(self._queueRouteGesture(queueScript=False))
			queueHandler.pumpAll()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)
		self.brailleHandler.messageBuffer.routeTo.assert_not_called()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()

	def _assertQueuedMessageRouteExpires(self, transition):
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		transition()
		before = list(self.transport.sent)
		with mock.patch.object(self.brailleHandler, "routeTo", wraps=self.brailleHandler.routeTo) as route:
			queueHandler.pumpAll()
		route.assert_not_called()
		self.brailleHandler.mainBuffer.routeTo.assert_not_called()
		self.assertEqual(self.transport.sent, before)

	def test_queued_message_route_expires_on_control_handoff(self):
		self._assertQueuedMessageRouteExpires(lambda: setattr(self.bridge, "_controlGeneration", 1))

	def test_queued_message_route_expires_on_local_control(self):
		client = types.SimpleNamespace(leaderTransport=self.transport, sendingKeys=False)
		self._assertQueuedMessageRouteExpires(lambda: setattr(self.bridge, "_client", client))

	def test_queued_message_route_expires_on_new_session(self):
		self._assertQueuedMessageRouteExpires(lambda: self.bridge._onHello(version=1))

	def test_queued_message_route_expires_on_fallback(self):
		self._assertQueuedMessageRouteExpires(lambda: self.bridge._onFallback(version=1))

	def test_queued_message_route_expires_on_disconnect(self):
		self._assertQueuedMessageRouteExpires(lambda: setattr(self.transport, "connected", False))

	def test_queued_message_route_expires_on_transport_replacement(self):
		client = types.SimpleNamespace(leaderTransport=object(), sendingKeys=True)
		self._assertQueuedMessageRouteExpires(lambda: setattr(self.bridge, "_client", client))

	def test_queued_message_route_expires_on_handler_replacement(self):
		self._assertQueuedMessageRouteExpires(
			lambda: setattr(braille, "handler", type(self.brailleHandler)())
		)

	def test_queued_message_route_expires_on_termination(self):
		self._assertQueuedMessageRouteExpires(self.bridge.terminate)

	def test_message_panning_resets_timer_without_moving_linux_window(self):
		self.brailleHandler.mainBuffer.window = 4
		self._sendMessage()
		timer = self.brailleHandler._messageCallLater
		self.brailleHandler.scrollForward()
		self.brailleHandler.scrollBack()
		self.assertEqual(timer.restarts, 2)
		self.assertEqual(self.brailleHandler.mainBuffer.window, 4)
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.messageBuffer)

	def test_disabled_messages_do_not_replace_windows_focus(self):
		windows = self._replaceMainWithWindows()
		self.core["config"].conf["braille"]["showMessages"] = 0
		self._sendMessage()
		self.assertIs(self.brailleHandler.buffer, self.brailleHandler.mainBuffer)
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)
		self.assertIsNone(self.bridge._messageOwner)
		self.assertIsNone(self.brailleHandler._messageCallLater)

	def test_speech_only_braille_mode_does_not_recover_focus_for_hidden_message(self):
		windows = self._replaceMainWithWindows()
		self.core["config"].conf["braille"]["mode"] = "speechOutput"
		self._sendMessage()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)
		self.assertIsNone(self.bridge._messageOwner)

	def test_disabled_new_message_does_not_claim_existing_windows_message(self):
		self.brailleHandler.message("Windows status")
		windows = self._replaceMainWithWindows()
		self.core["config"].conf["braille"]["showMessages"] = 0
		self._sendMessage()
		self.assertIsNone(self.bridge._messageOwner)
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_later_windows_message_clears_linux_message_ownership(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		self.brailleHandler.message("Windows status")
		self.assertIsNone(self.bridge._messageOwner)
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_return_to_local_control_prevents_linux_restoration(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		client = types.SimpleNamespace(leaderTransport=self.transport, sendingKeys=False)
		with mock.patch.object(self.bridge, "_client", client):
			self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)
		self.assertIsNone(self.bridge._messageOwner)

	def test_stale_control_generation_prevents_linux_restoration(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		self.bridge._controlGeneration += 1
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_disconnect_prevents_linux_restoration(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		self.transport.connected = False
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_fallback_clears_message_ownership(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		self.bridge._onFallback(version=1)
		self.assertIsNone(self.bridge._messageOwner)
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_new_session_clears_message_ownership(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		self.bridge._onHello(version=1)
		self.assertIsNone(self.bridge._messageOwner)
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_termination_unregisters_hooks_and_preserves_windows_focus(self):
		self._sendMessage()
		windows = self._replaceMainWithWindows()
		self.bridge.terminate()
		self.assertEqual(self.bridge._messageHooks, [])
		self.assertNotIn(self.bridge._onMessageShown, list(self.core["_pre_showBrailleMessage"].handlers))
		self.assertNotIn(
			self.bridge._onMessageDismissed, list(self.core["_post_dismissBrailleMessage"].handlers)
		)
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_control_change_during_message_does_not_repair_local_focus(self):
		windows = self._replaceMainWithWindows()
		client = types.SimpleNamespace(leaderTransport=self.transport, sendingKeys=True)

		def changeControl():
			client.sendingKeys = False

		with mock.patch.object(self.bridge, "_client", client):
			self.core["_pre_showBrailleMessage"].register(changeControl)
			self._sendMessage()
		self.assertIs(self.brailleHandler.mainBuffer.regions[-1].obj, windows)
		self.assertIsNone(self.bridge._messageOwner)

	def test_handler_replacement_prevents_restoration_into_new_handler(self):
		self._sendMessage()
		other = type(self.brailleHandler)()
		windows = HostObject(4242)
		other.handleGainFocus(windows)
		braille.handler = other
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(other.visibleRegions[-1].obj, windows)
		self.assertEqual(len(other.focused), 1)

	def test_absent_message_hooks_keep_pre_message_repair_without_registering(self):
		self.bridge._removeMessageHooks()
		with mock.patch.object(braille, "_post_dismissBrailleMessage", None):
			self.bridge._installMessageHooks()
			self.assertEqual(self.bridge._messageHooks, [])
			self._replaceMainWithWindows()
			self._sendMessage()
			self.brailleHandler._messageCallLater.callback()
		self.assertIsInstance(self.brailleHandler.visibleRegions[-1].obj, self.module.RemoteA11yObject)

	def test_message_without_cached_focus_does_not_restore_old_linux_object(self):
		self.bridge._clearFocus()
		windows = self._replaceMainWithWindows()
		self._sendMessage()
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, windows)

	def test_message_timeout_restores_linux_when_windows_replaces_buffer_while_visible(self):
		self._sendMessage()
		self.brailleHandler.handleGainFocus(HostObject(4242))
		self.brailleHandler._messageCallLater.callback()
		self.assertIsInstance(self.brailleHandler.visibleRegions[-1].obj, self.module.RemoteA11yObject)

	def test_dismissal_replaces_retained_same_id_region_with_current_snapshot(self):
		oldObj = self.brailleHandler.mainBuffer.regions[-1].obj
		self.sendFocus(text="abcdef!", caret=7)
		self._sendMessage()
		self.brailleHandler.mainBuffer.regions = [types.SimpleNamespace(obj=oldObj)]
		self.brailleHandler._messageCallLater.callback()
		self.assertIs(self.brailleHandler.visibleRegions[-1].obj, self.bridge._objects["save"])
		self.assertEqual(self.brailleHandler.visibleRegions[-1].obj._node.text, "abcdef!")
