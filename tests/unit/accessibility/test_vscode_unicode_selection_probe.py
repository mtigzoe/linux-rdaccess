"""Regression coverage for interpreting private Unicode selection evidence."""

import unittest

from tools.diagnostics import vscode_unicode_selection_probe as probe


class UnicodeSelectionProbeTests(unittest.TestCase):
    def test_bmp_full_selection_agrees_across_stages(self):
        value = probe.CASES["bmp"]
        length = len(value)
        dom = {
            "utf16": length,
            "codepoints": length,
            "anchor": 0,
            "focus": length,
            "selected_utf16": length,
            "selected_codepoints": length,
        }
        comparison = probe.selection_comparison(value, dom, [0, length], [0, length])
        self.assertTrue(comparison["dom_full_selection"])
        self.assertTrue(comparison["provider_full_selection"])
        self.assertTrue(comparison["semantic_matches_provider"])
        self.assertEqual(comparison["provider_end_shortfall"], 0)

    def test_astral_provider_shortfall_is_not_hidden_by_dom_or_semantics(self):
        for case, points, units, shortfall in (
            ("astral", 13, 14, 1),
            ("two_astral", 14, 16, 2),
        ):
            with self.subTest(case=case):
                dom = {
                    "utf16": units,
                    "codepoints": points,
                    "anchor": units,
                    "focus": 0,
                    "selected_utf16": units,
                    "selected_codepoints": points,
                }
                provider = [0, points - shortfall]
                comparison = probe.selection_comparison(
                    probe.CASES[case], dom, provider, provider
                )
                self.assertTrue(comparison["dom_full_selection"])
                self.assertFalse(comparison["provider_full_selection"])
                self.assertTrue(comparison["semantic_matches_provider"])
                self.assertEqual(comparison["provider_end_shortfall"], shortfall)

    def test_semantic_difference_is_visible_even_with_full_provider_selection(self):
        dom = {
            "utf16": 14,
            "codepoints": 13,
            "anchor": 0,
            "focus": 14,
            "selected_utf16": 14,
            "selected_codepoints": 13,
        }
        comparison = probe.selection_comparison(
            probe.CASES["astral"], dom, [0, 13], [0, 12]
        )
        self.assertTrue(comparison["provider_full_selection"])
        self.assertFalse(comparison["semantic_matches_provider"])

    def test_runtime_metadata_omits_debugger_session_and_unknown_fields(self):
        metadata = probe.browser_metadata(
            {
                "Browser": "Chrome/150.0.7871.250",
                "V8-Version": "15.0",
                "Protocol-Version": "1.3",
                "webSocketDebuggerUrl": "ws://127.0.0.1:1/secret-uuid",
                "User-Agent": "private profile details",
                "future-field": "private",
            }
        )
        self.assertEqual(
            metadata,
            {
                "Browser": "Chrome/150.0.7871.250",
                "V8-Version": "15.0",
                "Protocol-Version": "1.3",
            },
        )

    def test_debugger_connection_requires_private_loopback_port(self):
        url = "ws://127.0.0.1:12345/devtools/page/private"
        self.assertEqual(probe.loopback_websocket_url(url, 12345), url)
        for invalid in (
            "ws://example.com:12345/page",
            "ws://127.0.0.1:54321/page",
            "wss://127.0.0.1:12345/page",
            "ws://user@127.0.0.1:12345/page",
        ):
            with self.subTest(url=invalid), self.assertRaises(ValueError):
                probe.loopback_websocket_url(invalid, 12345)


if __name__ == "__main__":
    unittest.main()
