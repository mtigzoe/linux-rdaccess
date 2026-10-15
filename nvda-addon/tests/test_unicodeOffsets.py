"""Code-point offsets across the Linux snapshot and companion hooks.

The AT-SPI provider and NVDA base/handler are doubles. This exercises the real
snapshot, JSON decoder and companion hooks, not NVDA translation or a display.
"""

from __future__ import annotations

import importlib.util
import json
import types
import unittest

from tests import REPO_ROOT
from tests._objects import install_handler_runtime_stubs, load_handler_module

FIXTURES = (
	("a caf\u00e9 omega", 12, 12),
	("a\U0001f642 caf\u00e9 omega", 13, 14),
	("a\U0001f642\U0001d11e caf\u00e9 omega", 14, 16),
	("a\U0001f642\nb\U0001d11e caf\u00e9", 10, 12),
	("a\U0001f642e\u0301\U0001d11e", 5, 7),
)


class Provider:
	"""AT-SPI-shaped public text fixture; offsets count Python code points."""

	def __init__(self, text, *, caret, selection):
		self.text = text
		self.caret = caret
		self.selection = selection

	def get_name(self):
		return "Unicode fixture"

	def get_role_name(self):
		return "text"

	def get_child_count(self):
		return 0

	def get_text_iface(self):
		return self

	def get_character_count(self):
		return len(self.text)

	def get_text(self, start, end):
		return self.text[start:end]

	def get_caret_offset(self):
		return self.caret

	def get_n_selections(self):
		return int(self.selection is not None)

	def get_selection(self, index):
		assert index == 0 and self.selection is not None
		return types.SimpleNamespace(start_offset=self.selection[0], end_offset=self.selection[1])


class UnicodeOffsetTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_, _, cls.a11y = install_handler_runtime_stubs()
		cls.objects = load_handler_module()
		spec = importlib.util.spec_from_file_location(
			"_linux_unicode_snapshot_contract",
			REPO_ROOT / "linux_rdaccess_core/accessibility/a11y_model.py",
		)
		assert spec is not None and spec.loader is not None
		cls.model = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(cls.model)

	def snapshot(self, provider):
		payload = self.model.build_focus_payload("object:state-changed:focused", 1, provider)
		raw = {"type": "a11y_focus", **payload}
		# Exercise the actual streaming decoder, including escaped surrogate pairs.
		line = (json.dumps(raw, ensure_ascii=True) + "\n").encode("ascii")
		receiver = self.a11y.A11yJsonLineReceiver()
		messages = []
		for byte in line:
			messages.extend(receiver.feed(bytes([byte])))
		self.assertEqual(len(messages), 1)
		return messages[0].objects[0]

	def remote(self, node, sent):
		obj = self.objects.RemoteA11yObject(
			processID=1,
			node=node,
			parentObject=None,
			objectMap={},
			actionSender=lambda *_args: None,
			caretSender=lambda nodeId, offset: sent.append((nodeId, offset)),
		)
		return obj.TextInfo(obj)

	def test_unicode_selection_preserves_code_points_across_snapshot_wire_and_hooks(self):
		for text, points, units in FIXTURES:
			with self.subTest(text=text):
				self.assertEqual(len(text), points)
				self.assertEqual(len(text.encode("utf-16-le")) // 2, units)
				node = self.snapshot(Provider(text, caret=points, selection=(2, points)))
				info = self.remote(node, [])
				self.assertEqual(info._getStoryText(), text)
				self.assertEqual(info._getCaretOffset(), points)
				self.assertEqual(info._getSelectionOffsets(), (2, points))
				self.assertEqual(info._getStoryText()[2:points], text[2:])

	def test_every_code_point_boundary_routes_unchanged_including_combining_boundary(self):
		for text, points, _units in FIXTURES:
			with self.subTest(text=text):
				node = self.snapshot(Provider(text, caret=0, selection=None))
				sent = []
				info = self.remote(node, sent)
				for offset in range(points + 1):
					info._setCaretOffset(offset)
				self.assertEqual(sent, [(node.nodeId, offset) for offset in range(points + 1)])

	def test_utf16_endpoint_outside_code_point_story_cannot_route(self):
		for text, points, units in FIXTURES[1:]:
			with self.subTest(text=text):
				self.assertGreater(units, points)
				node = self.snapshot(Provider(text, caret=points, selection=None))
				sent = []
				with self.assertRaises(NotImplementedError):
					self.remote(node, sent)._setCaretOffset(units)
				self.assertEqual(sent, [])

	def test_collapse_and_selection_update_preserve_unicode_offsets(self):
		for text, points, _units in FIXTURES:
			with self.subTest(text=text):
				provider = Provider(text, caret=points, selection=None)
				node = self.snapshot(provider)
				self.assertEqual(self.remote(node, [])._getSelectionOffsets(), (points, points))
				provider.caret = 2
				provider.selection = (1, 2)
				payload = self.model.build_text_update(
					"object:text-selection-changed",
					provider,
					object_registry={node.nodeId: provider},
				)
				message = self.a11y.decodeMessage(json.loads(json.dumps({"type": "a11y_text", **payload})))
				self.assertEqual(message.text, text)
				self.assertEqual(message.caretOffset, 2)
				self.assertEqual((message.selectionStart, message.selectionEnd), (1, 2))

	def test_in_range_provider_shortfall_is_retained_rather_than_silently_corrected(self):
		text, points, _units = FIXTURES[1]
		node = self.snapshot(Provider(text, caret=points, selection=(0, points - 1)))
		self.assertEqual(self.remote(node, [])._getSelectionOffsets(), (0, 12))
		self.assertNotEqual(node.selectionEnd, points)
