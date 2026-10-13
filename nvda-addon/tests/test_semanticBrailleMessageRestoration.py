# License: GNU General Public License version 2 or later.
from __future__ import annotations

import ast
import types
from unittest import mock

import braille
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
