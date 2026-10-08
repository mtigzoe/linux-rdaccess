from __future__ import annotations

import ast
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]


def load_module(name: str, path: Path):
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


probe = load_module("nvda_speech_probe", ROOT / "diagnostics" / "nvda" / "nvda_speech_probe.py")
shared = load_module(
	"nvda_speech_probe_shared",
	ROOT / "tools" / "nvda" / "nvda_speech_probe" / "globalPlugins" / "linuxRdaccessSpeechProbe" / "shared.py",
)


class SpeechProbeProtocolTests(unittest.TestCase):
	def test_valid_event_round_trip(self):
		event = probe.decode_event(
			json.dumps({"type": "speech", "text": "hello", "segments": 1, "sequence": 7}).encode()
		)
		self.assertEqual(event["text"], "hello")
		self.assertEqual(event["sequence"], 7)

	def test_text_is_hidden_by_default(self):
		event = {"type": "speech", "text": "private words", "segments": 2, "sequence": 1}
		public = probe.public_event(event, show_text=False)
		self.assertNotIn("text", public)
		self.assertEqual(public["characters"], len("private words"))

	def test_text_requires_explicit_opt_in(self):
		event = {"type": "speech", "text": "expected announcement", "segments": 1, "sequence": 2}
		public = probe.public_event(event, show_text=True)
		self.assertEqual(public["text"], "expected announcement")

	def test_rejects_oversized_or_malformed_events(self):
		with self.assertRaises(probe.ProbeError):
			probe.decode_event(b"x" * (probe.MAX_LINE_BYTES + 1))
		with self.assertRaises(probe.ProbeError):
			probe.decode_event(b"not json")
		with self.assertRaises(probe.ProbeError):
			probe.decode_event(
				json.dumps({"type": "other", "text": "", "segments": 0, "sequence": 0}).encode()
			)

	def test_rejects_invalid_types(self):
		bad = [
			{"type": "speech", "text": 1, "segments": 1, "sequence": 1},
			{"type": "speech", "text": "x", "segments": True, "sequence": 1},
			{"type": "speech", "text": "x", "segments": 1, "sequence": True},
			{"type": "speech", "text": "x", "segments": -1, "sequence": 1},
			{"type": "speech", "text": "x", "segments": 1, "sequence": -1},
		]
		for value in bad:
			with self.subTest(value=value), self.assertRaises(probe.ProbeError):
				probe.decode_event(json.dumps(value).encode())

	def test_receiver_refuses_non_loopback_bind(self):
		self.assertTrue(probe._loopback("127.0.0.1"))
		self.assertTrue(probe._loopback("::1"))
		self.assertFalse(probe._loopback("0.0.0.0"))
		self.assertFalse(probe._loopback("192.168.1.50"))

	def test_empty_tunnel_probe_connection_is_ignored(self):
		server, client = probe.socket.socketpair()
		try:
			self.assertIsNone(probe.read_connection_event(server, timeout=0.01))
		finally:
			server.close()
			client.close()

	def test_valid_connection_event_is_decoded(self):
		server, client = probe.socket.socketpair()
		try:
			client.sendall(
				json.dumps({"type": "speech", "text": "hello", "segments": 1, "sequence": 9}).encode()
				+ b"\n"
			)
			event = probe.read_connection_event(server, timeout=0.1)
			self.assertIsNotNone(event)
			assert event is not None
			self.assertEqual(event["text"], "hello")
			self.assertEqual(event["sequence"], 9)
		finally:
			server.close()
			client.close()

	def test_ctrl_c_exits_without_traceback(self):
		original = probe.serve
		try:
			def interrupted(**kwargs):
				raise KeyboardInterrupt
			probe.serve = interrupted
			output = io.StringIO()
			with contextlib.redirect_stdout(output):
				code = probe.main([])
			self.assertEqual(code, 130)
			self.assertEqual(json.loads(output.getvalue()), {"status": "stopped"})
		finally:
			probe.serve = original


class SpeechProbeSharedTests(unittest.TestCase):
	def test_sequence_text_ignores_non_text_commands(self):
		text, segments = shared.sequence_text(["one ", object(), "two"])
		self.assertEqual(text, "one two")
		self.assertEqual(segments, 2)

	def test_build_event_omits_command_only_sequences(self):
		self.assertIsNone(shared.build_event([object()], 1))

	def test_build_event_truncates_text(self):
		event = shared.build_event(["x" * (shared.MAX_TEXT_CHARS + 10)], 3)
		assert event is not None
		self.assertEqual(len(event["text"]), shared.MAX_TEXT_CHARS)
		self.assertEqual(event["sequence"], 3)

	def test_nvda_plugin_source_is_valid_python(self):
		path = (
			ROOT
			/ "tools"
			/ "nvda"
			/ "nvda_speech_probe"
			/ "globalPlugins"
			/ "linuxRdaccessSpeechProbe"
			/ "__init__.py"
		)
		ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


if __name__ == "__main__":
	unittest.main()
