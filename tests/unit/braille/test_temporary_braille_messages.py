"""Sanitizing of Orca temporary braille messages sent to NVDA semantic braille."""
from __future__ import annotations

import unittest

from linux_rdaccess_core.accessibility import orca_adapter

sanitize = orca_adapter.OrcaRuntimeAdapter.sanitize_braille_message


class SanitizeBrailleMessageTests(unittest.TestCase):
    def test_plain_text_is_unchanged(self):
        self.assertEqual(sanitize("Focus mode"), "Focus mode")

    def test_control_format_and_separator_characters_become_spaces(self):
        self.assertEqual(sanitize("  Focus\x00 mode\n\tnow\u202e!\x1b  "), "Focus mode now !")
        self.assertEqual(sanitize("a\u2028b\u2029c\u200bd"), "a b c d")

    def test_unprintable_or_blank_text_is_rejected(self):
        for text in ("", "   ", "\x00\x07\x1b", "\u202e\u200b", "\ud800"):
            with self.subTest(text=text):
                self.assertIsNone(sanitize(text))

    def test_non_text_is_rejected(self):
        for text in (None, 5, b"Focus mode", ["Focus mode"], {"text": "x"}):
            with self.subTest(text=text):
                self.assertIsNone(sanitize(text))

    def test_text_is_bounded(self):
        limit = orca_adapter.OrcaRuntimeAdapter.MAX_BRAILLE_MESSAGE_LENGTH
        self.assertEqual(limit, 256)
        self.assertEqual(sanitize("x" * 100000), "x" * limit)
        self.assertEqual(len(sanitize("word " * 1000)), limit)
        # A cut that ends on a separator never leaves trailing whitespace.
        self.assertEqual(sanitize("x" * (limit - 1) + " y"), "x" * (limit - 1))

    def test_unicode_braille_and_accents_survive(self):
        self.assertEqual(sanitize("Caps Lock on \u2803 café"), "Caps Lock on \u2803 café")


if __name__ == "__main__":
    unittest.main()
