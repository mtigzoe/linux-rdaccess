# License: GNU General Public License version 2 or later.
"""Native routing branches with opt-in diagnostics; no running NVDA or device."""

from __future__ import annotations

import ast
import sys
import types
from collections import namedtuple
from unittest import mock

import braille
import queueHandler

from tests import NVDA_SOURCE
from tests import test_semanticBrailleMessageRestoration as messages


def nativeClass(name, methods):
	path = NVDA_SOURCE / "braille.py"
	if not path.exists():
		path = (
			NVDA_SOURCE
			/ "braille"
			/ {"BrailleBuffer": "buffers.py", "TextInfoRegion": "regions/textInfo.py"}[name]
		)
	tree = ast.parse(path.read_text(encoding="utf-8"))
	cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
	cls.bases = []
	cls.decorator_list = []
	cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in methods]
	if {node.name for node in cls.body} != set(methods):
		raise AssertionError("Native routing reference changed")
	namespace = {"__name__": "braille", "_speakOnRouting": lambda info: None}
	module = ast.Module(
		body=[
			ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
			cls,
		],
		type_ignores=[],
	)
	exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
	return namespace[name]


class RoutingOutcomesTests(messages.MessageRestorationTests):
	"""Also rerun the existing message lifecycle contracts with diagnostics enabled."""

	def setUp(self):
		super().setUp()
		self._startRoutingTrace()

	def outcomes(self):
		return [event["event"] for event in self.routingTrace.snapshotOutcomes()["events"]]

	def nativeBuffer(self, route):
		cls = nativeClass("BrailleBuffer", {"routeTo", "windowPosToBufferPos"})
		patch = mock.patch.object(braille, "BrailleBuffer", cls, create=True)
		patch.start()
		self.addCleanup(patch.stop)
		buffer = cls()
		buffer.handler = types.SimpleNamespace(
			displaySize=40, displayDimensions=types.SimpleNamespace(numCols=40)
		)
		buffer._windowRowBufferOffsets = [namedtuple("Row", "start end")(0, 20)]
		buffer.windowEndPos = 20
		buffer.bufferPosToRegionPos = lambda index: (types.SimpleNamespace(routeTo=route), index)
		self.brailleHandler.mainBuffer = self.brailleHandler.buffer = buffer
		self.bridge._routingObserver.install(self.brailleHandler)
		return buffer

	def test_outside_native_buffer_has_no_caret_or_activation(self):
		route = mock.Mock()
		buffer = self.nativeBuffer(route)
		buffer._windowRowBufferOffsets = [namedtuple("Row", "start end")(0, 0)]
		buffer.windowEndPos = 0
		original = buffer.windowPosToBufferPos
		before = list(self.transport.sent)
		self.brailleHandler.routeTo(30)
		route.assert_not_called()
		self.assertEqual(self.transport.sent, before)
		self.assertIn("outside_buffer", self.outcomes())
		self.assertNotIn("caret_send_returned", self.outcomes())
		self.assertEqual(buffer.windowPosToBufferPos, original)
		self.assertNotIn("windowPosToBufferPos", buffer.__dict__)

	def test_padded_cell_clamping_is_not_reported_as_an_ignored_route(self):
		self._prepareRouteableFocus()
		obj = self.bridge._objects["save"]
		self.nativeBuffer(lambda index: obj.TextInfo(obj)._setCaretOffset(index))
		self.brailleHandler.routeTo(30)
		self.assertNotIn("outside_buffer", self.outcomes())
		self.assertIn("caret_send_returned", self.outcomes())
		self.assertEqual(self.transport.sent[-1]["offset"], 19)

	def test_native_window_lookup_error_is_preserved(self):
		self.nativeBuffer(mock.Mock())
		with self.assertRaises(ValueError):
			self.brailleHandler.routeTo(40)
		self.assertIn("outcome_unknown", self.outcomes())
		self.assertNotIn("outside_buffer", self.outcomes())

	def test_current_cursor_attempts_activation_without_caret_send(self):
		obj = self.bridge._objects["save"]
		info = obj.TextInfo(obj)
		info.compareEndPoints = lambda other, which: 0
		region = nativeClass("TextInfoRegion", {"_routeToTextInfo"})()
		region.brailleCursorPos = 6
		region.getTextInfoForBraillePos = lambda index: info
		region._getSelection = lambda: info
		region._setCursor = mock.Mock()
		self.nativeBuffer(lambda index: region._routeToTextInfo(info))
		with mock.patch.object(
			type(info).__mro__[1], "activate", side_effect=NotImplementedError, create=True
		):
			before = list(self.transport.sent)
			self.brailleHandler.routeTo(6)
		self.assertIn("activation_attempted", self.outcomes())
		self.assertNotIn("caret_send_returned", self.outcomes())
		region._setCursor.assert_not_called()
		self.assertEqual(self.transport.sent, before)

	def test_different_cell_observes_caret_attempt_and_send_return(self):
		obj = self.bridge._objects["save"]
		self.nativeBuffer(lambda index: obj.TextInfo(obj)._setCaretOffset(index))
		self.brailleHandler.routeTo(3)
		self.assertEqual(self.outcomes(), ["caret_attempted", "caret_send_returned"])
		self.assertEqual(self.transport.sent[-1]["offset"], 3)

	def test_object_region_activation_is_an_attempt_without_a_caret_request(self):
		obj = self.bridge._objects["save"]
		self.nativeBuffer(lambda index: obj.doAction())
		self.brailleHandler.routeTo(3)
		self.assertEqual(self.outcomes(), ["activation_attempted"])
		self.assertEqual(self.transport.sent[-1]["type"], "lrd_a11y_action")

	def test_send_exception_is_observed_without_retry_or_exception_text(self):
		obj = self.bridge._objects["save"]
		self.nativeBuffer(lambda index: obj.TextInfo(obj)._setCaretOffset(index))
		self.transport.send = mock.Mock(side_effect=RuntimeError("PRIVATE"))
		self.brailleHandler.routeTo(3)
		self.transport.send.assert_called_once()
		self.assertIn("caret_send_failed", self.outcomes())
		self.assertNotIn("PRIVATE", str(self.routingTrace.snapshotOutcomes()))

	def test_visible_message_reports_dismissal_without_caret(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		queueHandler.pumpAll()
		self.assertIn("message_dismissed", self.outcomes())
		self.assertNotIn("caret_attempted", self.outcomes())

	def test_expired_queued_message_reports_discard(self):
		self._prepareRouteableFocus()
		self._sendMessage()
		self._queueRouteGesture()
		self.brailleHandler._messageCallLater.callback()
		queueHandler.pumpAll()
		self.assertIn("route_discarded", self.outcomes())
		self.assertNotIn("caret_send_returned", self.outcomes())

	def test_custom_buffer_unknown_and_original_return_exception_preserved(self):
		self.brailleHandler.routeTo = mock.Mock(return_value=17)
		original = self.brailleHandler.routeTo
		self.bridge._routingObserver.install(self.brailleHandler)
		self.assertEqual(self.brailleHandler.routeTo(3), 17)
		self.assertIn("outcome_unknown", self.outcomes())
		original.side_effect = RuntimeError("PRIVATE")
		with self.assertRaises(RuntimeError):
			self.brailleHandler.routeTo(3)
		self.assertEqual(original.call_count, 2)
		self.bridge.terminate()
		self.assertIs(self.brailleHandler.routeTo, original)

	def test_disabled_or_faulty_sensor_preserves_native_calls(self):
		for enabled in (False, True):
			with self.subTest(enabled=enabled):
				self.routingTrace.start(enabled=enabled)
				self.brailleHandler.routeTo = original = mock.Mock(return_value=17)
				self.bridge._routingObserver.close()
				self.bridge._routingObserver.install(self.brailleHandler)
				self.bridge._routingObserver._emit = mock.Mock(side_effect=RuntimeError("PRIVATE"))
				self.assertEqual(self.brailleHandler.routeTo(3), 17)
				original.assert_called_once_with(3)

	def test_handoff_disconnect_and_reconnect_do_not_observe_inactive_calls(self):
		self.brailleHandler.routeTo = original = mock.Mock()
		self.bridge._routingObserver.install(self.brailleHandler)
		self.bridge._client = client = types.SimpleNamespace(
			leaderTransport=self.transport, sendingKeys=False
		)
		self.brailleHandler.routeTo(3)
		self.assertEqual(self.outcomes(), [])
		client.sendingKeys = True
		self.transport.connected = False
		self.brailleHandler.routeTo(3)
		self.assertEqual(self.outcomes(), [])
		self.transport.connected = True
		self.brailleHandler.routeTo(3)
		self.assertIn("outcome_unknown", self.outcomes())
		self.assertEqual(original.call_count, 3)
		self.bridge._client = None

	def test_missing_optional_observer_does_not_change_routing(self):
		name = self.module.__package__ + ".routingOutcomes"
		with mock.patch.dict(sys.modules, {name: None}):
			other = self.module.RemoteAccessSemanticBrailleBridge(self.transport)
		self.addCleanup(other.terminate)
		other._routingTrace = self.routingTrace
		other._negotiated = True
		self.brailleHandler.routeTo = original = mock.Mock(return_value=17)
		other._routingObserver.install(self.brailleHandler)
		self.assertEqual(self.brailleHandler.routeTo(3), 17)
		original.assert_called_once_with(3)
		self.assertIn("outcome_unknown", self.outcomes())

	def test_later_handler_wrapper_is_preserved_on_termination(self):
		self.bridge._routingObserver.install(self.brailleHandler)
		later = mock.Mock(return_value=17)
		self.brailleHandler.routeTo = later
		self.bridge.terminate()
		self.assertIs(self.brailleHandler.routeTo, later)

	def test_metadata_getter_failure_never_prevents_original_route(self):
		class Handler:
			@property
			def buffer(self):
				raise RuntimeError("PRIVATE")

		handler = Handler()
		handler.routeTo = original = mock.Mock(return_value=17)
		self.bridge._routingObserver.install(handler)
		self.assertEqual(handler.routeTo(3), 17)
		original.assert_called_once_with(3)
		self.assertIn("outcome_unknown", self.outcomes())
