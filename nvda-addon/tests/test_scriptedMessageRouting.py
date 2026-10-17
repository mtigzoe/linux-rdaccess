"""Scripted routing enters the native message guard, never the underlying text."""

import importlib
import types
import unittest
from unittest import mock

import braille
import inputCore
import queueHandler

from . import test_semanticBrailleMessageRestoration as messages


class ScriptedMessageRoutingTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		messages.MessageRestorationTests.setUpClass()

	def setUp(self):
		self.fixture = messages.MessageRestorationTests(
			"test_routing_dismisses_message_without_remote_caret_or_action"
		)
		self.fixture.setUp()
		self.addCleanup(self.fixture.doCleanups)
		self.addCleanup(self.fixture.tearDown)
		self.fixture._startRoutingTrace()
		self.fixture._prepareRouteableFocus()
		self.fixture._sendMessage()
		self.bridge = self.fixture.bridge
		self.bridge._client = types.SimpleNamespace(leaderTransport=self.fixture.transport, sendingKeys=True)
		self.bridge._semanticBrailleInputInstalled = True
		self.permitted = True
		self.manager = types.SimpleNamespace(_captureFunc=None, isInputHelpActive=False)
		patch = mock.patch.object(inputCore, "manager", self.manager, create=True)
		patch.start()
		self.addCleanup(patch.stop)
		regionPatch = mock.patch.object(braille, "TextRegion", messages.TextRegion, create=True)
		regionPatch.start()
		self.addCleanup(regionPatch.stop)
		self.module = importlib.import_module(
			f"{self.bridge.__module__.rsplit('.', 1)[0]}.scriptedMessageRouting"
		)

	def route(self):
		return self.module.queueMessageRoute(self.bridge, lambda: self.permitted)

	def test_native_dismissal_and_restoration_without_remote_caret_or_action(self):
		before = list(self.fixture.transport.sent)
		self.assertEqual(self.route(), "queued")
		queueHandler.pumpAll()
		self.assertIs(self.fixture.brailleHandler.buffer, self.fixture.brailleHandler.mainBuffer)
		self.assertEqual(self.fixture.transport.sent, before)
		events = [event["event"] for event in self.fixture.routingTrace.snapshotOutcomes()["events"]]
		self.assertIn("message_dismissed", events)
		self.assertNotIn("caret_attempted", events)

	def test_expiry_after_queue_cannot_dismiss_or_route(self):
		before = list(self.fixture.transport.sent)
		self.assertEqual(self.route(), "queued")
		self.permitted = False
		queueHandler.pumpAll()
		self.assertIs(self.fixture.brailleHandler.buffer, self.fixture.brailleHandler.messageBuffer)
		self.assertEqual(self.fixture.transport.sent, before)

	def test_timeout_before_execution_cannot_route_the_main_buffer(self):
		before = list(self.fixture.transport.sent)
		self.assertEqual(self.route(), "queued")
		self.fixture.brailleHandler._messageCallLater.callback()
		queueHandler.pumpAll()
		self.assertEqual(self.fixture.transport.sent, before)

	def test_later_message_is_not_dismissed_by_old_simulation(self):
		self.assertEqual(self.route(), "queued")
		self.bridge._presentMessageOnMainThread(
			self.bridge._session, self.bridge._controlGeneration, "Focus mode"
		)
		queueHandler.pumpAll()
		self.assertIs(self.fixture.brailleHandler.buffer, self.fixture.brailleHandler.messageBuffer)

	def test_missing_message_does_not_fall_back_to_document_routing(self):
		self.fixture.brailleHandler._messageCallLater.callback()
		before = list(self.fixture.transport.sent)
		self.assertEqual(self.route(), "refused")
		queueHandler.pumpAll()
		self.assertEqual(self.fixture.transport.sent, before)

	def test_local_control_capture_help_and_disabled_diagnostics_are_refused(self):
		for attribute, value, target in (
			("sendingKeys", False, self.bridge._client),
			("_captureFunc", lambda gesture: True, self.manager),
			("isInputHelpActive", True, self.manager),
			("_semanticBrailleInputInstalled", False, self.bridge),
		):
			with self.subTest(attribute=attribute), mock.patch.object(target, attribute, value):
				self.assertEqual(self.route(), "refused")
		self.fixture.routingTrace.clear()
		self.assertEqual(self.route(), "refused")

	def test_no_legacy_client_or_no_consent_is_refused(self):
		self.permitted = False
		self.assertEqual(self.route(), "refused")
		self.permitted = True
		self.bridge._client = None
		self.assertEqual(self.route(), "refused")

	def test_custom_message_region_is_not_activated(self):
		class CustomRegion:
			pass

		region = CustomRegion()
		region.routeTo = mock.Mock()
		self.fixture.brailleHandler.messageBuffer.regions = [region]
		self.assertEqual(self.route(), "refused")
		queueHandler.pumpAll()
		region.routeTo.assert_not_called()
