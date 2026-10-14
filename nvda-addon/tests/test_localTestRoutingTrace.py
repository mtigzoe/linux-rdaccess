"""Privacy, consent, wire compatibility and bounded routing diagnostics."""

from __future__ import annotations

import copy
import importlib
import json
import secrets
import unittest

from . import test_localTestIpc as ipcTests

PACKAGE = ipcTests.PACKAGE

trace = importlib.import_module(f"{PACKAGE}.localTestRoutingTrace")
transport = importlib.import_module(f"{PACKAGE}.localTestTransport")


def fields():
	return {
		"buffer": "message",
		"linux_owned": True,
		"control": True,
		"capture": False,
		"semantic_input": True,
		"index": 7,
		"offset": None,
		"same_focus": True,
	}


class RoutingTraceTests(unittest.TestCase):
	def setUp(self):
		self.allowed = True
		self.now = 10.0
		self.recorder = trace.RoutingTraceRecorder(lambda: self.allowed, clock=lambda: self.now)

	def test_default_and_unchecked_consent_collect_nothing(self):
		for start in (False, True):
			if start:
				self.recorder.start(enabled=False)
			self.recorder.record("route_received", **fields())
			self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())

	def test_opt_in_captures_only_typed_metadata_and_returns_detached_copies(self):
		self.recorder.start(enabled=True)
		self.now += 0.125
		self.recorder.record("route_received", **fields())
		snapshot = self.recorder.snapshot()
		self.assertEqual(snapshot["events"][0]["elapsed_ms"], 125)
		self.assertEqual(snapshot["events"][0]["index"], 7)
		snapshot["events"][0]["index"] = 99
		self.assertEqual(self.recorder.snapshot()["events"][0]["index"], 7)

	def test_expiry_revocation_and_new_consent_drop_previous_metadata(self):
		self.recorder.start(enabled=True)
		self.recorder.record("route_received", **fields())
		self.allowed = False
		self.recorder.record("caret_sent", **{**fields(), "offset": 9})
		self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())
		self.allowed = True
		self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())
		self.recorder.start(enabled=True)
		self.assertEqual(self.recorder.snapshot()["events"], [])
		self.recorder.clear()
		self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())

	def test_unknown_strings_text_and_boolean_positions_are_never_retained(self):
		self.recorder.start(enabled=True)
		for event, values in (
			("PRIVATE TEXT", fields()),
			("route_received", {**fields(), "buffer": "PRIVATE TEXT"}),
			("route_received", {**fields(), "index": "PRIVATE TEXT"}),
			("route_received", {**fields(), "offset": True}),
			("route_received", {**fields(), "text": "PRIVATE TEXT"}),
		):
			self.recorder.record(event, **values)
		self.assertEqual(self.recorder.snapshot()["events"], [])
		self.assertEqual(self.recorder.snapshot()["dropped"], 5)
		self.assertNotIn("PRIVATE TEXT", json.dumps(self.recorder.snapshot()))

	def test_expiry_during_event_collection_cannot_append_or_return_metadata(self):
		self.recorder.start(enabled=True)

		def expires():
			self.allowed = False
			return self.now

		self.recorder._clock = expires
		self.recorder.record("route_received", **fields())
		self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())

	def test_expiry_during_snapshot_cannot_export_previously_collected_metadata(self):
		self.recorder.start(enabled=True)
		self.recorder.record("route_received", **fields())

		def expires():
			self.allowed = False
			return self.now

		self.recorder._clock = expires
		self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())

	def test_failed_authorization_check_discards_history_and_clock_errors_disclose_drops(self):
		self.recorder.start(enabled=True)
		self.recorder._clock = lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE TEXT"))
		self.recorder.record("route_received", **fields())
		self.recorder._clock = lambda: self.now
		self.assertEqual(self.recorder.snapshot()["dropped"], 1)
		self.recorder._authorized = lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE TEXT"))
		self.assertEqual(self.recorder.snapshot(), trace.emptyTrace())

	def test_record_limit_discloses_drops_and_keeps_first_events(self):
		self.recorder.start(enabled=True)
		for index in range(trace.TRACE_LIMIT + 3):
			self.now += 0.01
			self.recorder.record("route_received", **{**fields(), "index": index})
		snapshot = self.recorder.snapshot()
		self.assertEqual(len(snapshot["events"]), trace.TRACE_LIMIT)
		self.assertEqual(snapshot["dropped"], 3)
		self.assertEqual(snapshot["events"][-1]["seq"], trace.TRACE_LIMIT)

	def test_serializer_rejects_extra_fields_bad_enums_and_inactive_history(self):
		self.recorder.start(enabled=True)
		self.recorder.record("route_received", **fields())
		snapshot = self.recorder.snapshot()
		for location, key, value in (
			("root", "secret", "PRIVATE TEXT"),
			("root", "available", False),
			("root", "dropped", True),
			("root", "snapshot_ms", True),
			("event", "text", "PRIVATE TEXT"),
			("event", "event", "PRIVATE TEXT"),
			("event", "linux_owned", 1),
			("event", "seq", True),
			("event", "index", -1),
			("event", "offset", 8193),
			("event", "elapsed_ms", 300001),
		):
			invalid = copy.deepcopy(snapshot)
			target = invalid if location == "root" else invalid["events"][0]
			target[key] = value
			with self.subTest(key=key), self.assertRaises(ValueError) as error:
				trace.sanitizeRoutingTrace(invalid)
			self.assertNotIn("PRIVATE TEXT", str(error.exception))

	def test_trace_has_a_separate_argument_free_version_two_operation(self):
		self.assertEqual(
			transport.validateOperation({"version": 2, "action": "braille_trace"}), "braille_trace"
		)
		for request in (
			{"version": 1, "action": "braille_trace"},
			{"version": 2, "action": "status"},
			{"version": 2, "action": "connect"},
			{"version": 2, "action": "braille_trace", "enable": True},
		):
			with self.subTest(request=request), self.assertRaises(ValueError):
				transport.validateOperation(request)

	def test_version_one_replies_remain_exact_and_trace_reply_fits_authenticated_limit(self):
		self.recorder.start(enabled=True)
		self.now += 299.0
		for _ in range(trace.TRACE_LIMIT):
			self.recorder.record("remote_dismiss_returned", **{**fields(), "index": 1023, "offset": 8192})
		base = {"result": "connected", "status": ipcTests.LocalIpcTests.valid_status()}
		reply = {**base, "braille_trace": self.recorder.snapshot()}
		self.assertEqual(transport.sanitizeReply(base), base)
		with self.assertRaises(ValueError):
			transport.sanitizeReply(reply)
		self.assertEqual(transport.sanitizeTraceReply(reply), reply)
		wire = transport.sign(
			secrets.token_bytes(32),
			{"challenge": "a" * 64, "nonce": "b" * 64, "response": reply},
			direction=b"response:",
		)
		self.assertLessEqual(len(wire), 4096)
