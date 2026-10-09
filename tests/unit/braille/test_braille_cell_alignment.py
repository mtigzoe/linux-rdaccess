"""Remote cells must preserve Orca 42's actual Liblouis routing positions."""
from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

import orca_adapter
import remote_access
from tests import test_remote_access as fixtures

try:
    import louis
except ImportError:
    louis = None


@unittest.skipUnless(louis is not None, "native Liblouis bindings unavailable")
class NativeBrailleAlignmentTests(unittest.TestCase):
    def native(self, text="the cat and the dog", *, contracted=True,
               cursor=0, width=40, start=0):
        braille = types.ModuleType("orca.braille")
        routes = []
        target = object()
        braille.__dict__.update({
            "re": re, "louis": louis,
            "settings": types.SimpleNamespace(enableContractedBraille=contracted,
                brailleContractionTable="en-ueb-g2.ctb", disableBrailleEOL=False),
            "debug": types.SimpleNamespace(LEVEL_INFO=1, println=lambda *a: None),
            "_defaultContractionTable": "en-ueb-g2.ctb",
            "_displaySize": [width, 1], "viewport": [start, 0],
            "_regionWithFocus": None, "_flashEventSourceId": 0,
            "orca_state": types.SimpleNamespace(activeScript=types.SimpleNamespace(
                getTextLineAtCaret=lambda *a, **kw: (text, cursor, 0),
                utilities=types.SimpleNamespace(setCaretOffset=lambda obj, off: routes.append((obj, off))))),
        })
        fixture = Path(__file__).resolve().parents[2] / "fixtures/orca42-braille-methods.py"
        exec(compile(fixture.read_text(), str(fixture), "exec"), braille.__dict__)
        region = braille.Text(target)
        line = braille.Line(region)
        braille._lines = [line]
        braille._regionWithFocus = region
        braille.cursorCell = 0
        braille.getShowingLine = lambda: line
        braille.refresh = mock.Mock(return_value="native refresh result")
        orca = types.ModuleType("orca")
        orca.braille = braille
        patches = mock.patch.dict(sys.modules, {
            "orca": orca, "orca.braille": braille,
            "linux_rdaccess_orca_adapter": orca_adapter,
        })
        return braille, region, routes, target, patches

    def expected(self, region):
        table = region.contractionTable if region.contracted else "en-us-comp8.ctb"
        return [ord(ch) - 0x2800 for ch in louis.charToDots(
            [table], region.string, mode=louis.ucBrl)]

    def test_cursor_expanded_word_keeps_original_native_routing_cells(self):
        braille, region, routes, target, patches = self.native()
        self.assertEqual(region.string, "the cat & ! dog")
        with patches:
            cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
            braille.processRoutingKey(types.SimpleNamespace(event={"argument": 4}))
        self.assertEqual(cells[:15], self.expected(region))
        self.assertEqual(cells[15:], [0] * 25)
        self.assertEqual(routes, [(target, 4)])
        self.assertEqual(cells[4], 9)  # Native cell 4 is the c of cat.

    def test_old_hook_recontracts_cursor_word_and_shifts_visible_routing(self):
        braille, region, routes, target, patches = self.native()
        messages = []
        namespace = {"controller": types.SimpleNamespace(transport=types.SimpleNamespace(
            connected=True, connection_type="slave", send=lambda **kw: messages.append(kw))),
            "_dbg": lambda *a: None}
        with patches:
            exec(remote_access._LEGACY_CUSTOMIZATION_BRAILLE_SOURCE, namespace)
            braille.refresh()
            # The old hook displays cat starting at cell 2, but native routing
            # still indexes the expanded 'the' and sends that cell to e.
            braille.processRoutingKey(types.SimpleNamespace(event={"argument": 2}))
        self.assertEqual(messages[0]["cells"][2], 9)
        self.assertEqual(self.expected(region)[2], 17)
        self.assertEqual(routes, [(target, 2)])

    def test_contracted_nontext_region_is_not_translated_twice(self):
        braille, _, _, _, patches = self.native()
        region = braille.Region("the cat and the dog")
        braille._lines = [braille.Line(region)]
        braille.getShowingLine = lambda: braille._lines[0]
        self.assertEqual(region.string, "! cat & ! dog")
        with patches:
            cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
        self.assertEqual(cells[:13], self.expected(region))
        self.assertEqual(cells[0], 46)  # the contraction, rather than punctuation
        self.assertEqual(cells[13:], [0] * 27)

    def test_first_middle_and_last_cells_route_after_native_pan_at_40_and_80(self):
        for width in (40, 80):
            with self.subTest(width=width):
                braille, region, routes, target, patches = self.native(
                    "the cat and the dog " * 40, width=width)
                with patches:
                    self.assertTrue(braille.panRight())
                    start = braille.viewport[0]
                    cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
                    for cell in (0, width // 2, width - 1):
                        braille.processRoutingKey(types.SimpleNamespace(event={"argument": cell}))
                self.assertGreater(start, 0)
                self.assertEqual(cells, self.expected(region)[start:start + width])
                self.assertEqual(routes, [(target, region.inPos[start + cell])
                                         for cell in (0, width // 2, width - 1)])

    def test_native_routing_cannot_move_caret_to_a_cell_outside_the_display(self):
        braille, _, routes, target, patches = self.native(
            'abcdefghijklmno', contracted=False, width=8)
        braille.orca_state.activeScript.processRoutingKey = braille.processRoutingKey
        with patches:
            sys.modules['orca'].orca_state = braille.orca_state
            self.assertTrue(orca_adapter.OrcaRuntimeAdapter.route_braille(7))
            self.assertFalse(orca_adapter.OrcaRuntimeAdapter.route_braille(8))
        self.assertEqual(routes, [(target, 7)])

    def test_mixed_regions_use_each_native_table_and_preserve_unicode_dots(self):
        braille, text, _, _, patches = self.native("the and 123")
        prefix = braille.Region("NASA and xyz")
        braille.settings.enableContractedBraille = False
        plain = braille.Region(" A12 ⠿")
        line = braille.Line()
        line.addRegions([prefix, text, plain])
        braille._lines = [line]
        braille.getShowingLine = lambda: line
        with patches:
            cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
        expected = self.expected(prefix) + self.expected(text) + self.expected(plain)
        # Literal Unicode braille represents dots itself, independent of table.
        expected[-1] = 63
        self.assertEqual(cells[:len(expected)], expected)
        self.assertEqual(cells[len(expected):], [0] * (40 - len(expected)))

    def test_uncontracted_text_never_inserts_capital_or_number_cells(self):
        braille, region, routes, target, patches = self.native("A12 and the", contracted=False)
        with patches:
            cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
            braille.processRoutingKey(types.SimpleNamespace(event={"argument": 3}))
        self.assertEqual(cells[:len(region.string)], self.expected(region))
        self.assertEqual(cells[:4], [65, 2, 6, 0])
        self.assertEqual(routes, [(target, 3)])

    def test_cursor_movement_regenerates_native_expanded_word_without_old_map(self):
        for cursor in (0, 4, 8, 12, 18):
            with self.subTest(cursor=cursor):
                braille, region, routes, target, patches = self.native(cursor=cursor)
                with patches:
                    cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
                    index = region.cursorOffset
                    braille.processRoutingKey(types.SimpleNamespace(event={"argument": index}))
                self.assertEqual(cells[:len(region.string)], self.expected(region))
                self.assertEqual(routes, [(target, region.inPos[index])])

    def test_native_word_wrap_masks_and_cursor_survive_forwarding(self):
        braille, region, _, _, patches = self.native("plain text", contracted=False, width=8)
        braille._adjustForWordWrap = lambda target: (0, 6)
        region.getAttributeMask = lambda get_link_mask: "\x40" + "\x00" * 9
        braille.cursorCell = 3
        with patches:
            cells = orca_adapter.OrcaRuntimeAdapter.braille_cells()
        expected = self.expected(region)[:6] + [0, 0]
        expected[0] |= 0x40
        expected[2] |= 0xc0
        self.assertEqual(cells, expected)

    def test_new_hook_keeps_native_result_and_forwards_only_connected_slave(self):
        for connected, role in ((True, "slave"), (False, "slave"), (True, "master")):
            with self.subTest(connected=connected, role=role):
                braille, region, _, _, patches = self.native()
                original = braille.refresh
                messages = []
                namespace = {"controller": types.SimpleNamespace(transport=types.SimpleNamespace(
                    connected=connected, connection_type=role, send=lambda **kw: messages.append(kw))),
                    "_dbg": lambda *a: None}
                with patches:
                    exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, namespace)
                    result = braille.refresh(False, 0, False)
                self.assertEqual(result, "native refresh result")
                original.assert_called_once_with(False, 0, False)
                if connected and role == "slave":
                    self.assertEqual(messages[0]["cells"][:len(region.string)], self.expected(region))
                else:
                    self.assertEqual(messages, [])

    def test_conversion_failure_does_not_send_false_cells_or_log_text(self):
        braille, _, _, _, patches = self.native()
        messages, logs = [], []
        namespace = {"controller": types.SimpleNamespace(transport=types.SimpleNamespace(
            connected=True, connection_type="slave", send=lambda **kw: messages.append(kw))),
            "_dbg": logs.append}
        with patches, mock.patch.object(louis, "charToDots", side_effect=RuntimeError("private text")):
            exec(remote_access._CUSTOMIZATION_BRAILLE_CELLS_HOOK, namespace)
            result = braille.refresh()
        self.assertEqual(result, "native refresh result")
        self.assertEqual(messages, [])
        self.assertNotIn("private text", str(logs))


class BrailleCellsUpdaterTests(unittest.TestCase):
    def test_recognized_hook_is_replaced_once_and_preserves_surrounding_source(self):
        source = "# π before\n" + remote_access._LEGACY_CUSTOMIZATION_BRAILLE_SOURCE + "\n# after\n"
        updated = remote_access._patch_legacy_customization_braille_cells(source)
        self.assertTrue(remote_access.legacy_customization_braille_cells_patch_current(updated))
        self.assertEqual(remote_access._patch_legacy_customization_braille_cells(updated), updated)
        self.assertTrue(updated.startswith("# π before\n"))
        self.assertTrue(updated.endswith("\n# after\n"))
        self.assertNotIn("translateString", updated)

    def test_unsupported_or_duplicate_hooks_are_rejected(self):
        original = remote_access._LEGACY_CUSTOMIZATION_BRAILLE_SOURCE
        for source in (original.replace('getLineInfo(True)', 'getLineInfo(False)'),
                       original + original,
                       original + "\n_old_braille_refresh = other\n",
                       original + "\nimport other as _linux_rdaccess_braille_adapter\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                remote_access._patch_legacy_customization_braille_cells(source)

    def test_damaged_current_marker_is_rejected_without_repair_guess(self):
        updated = remote_access._patch_legacy_customization_braille_cells(
            remote_access._LEGACY_CUSTOMIZATION_BRAILLE_SOURCE)
        for source in (updated.replace('cells=cells', 'cells=[]'),
                       updated + updated,
                       updated + "\n_linux_rdaccess_braille_adapter = other\n"):
            with self.subTest(source=source):
                self.assertFalse(remote_access.legacy_customization_braille_cells_patch_current(source))
                with self.assertRaises(ValueError):
                    remote_access._patch_legacy_customization_braille_cells(source)

    def test_minimal_configuration_without_braille_hook_is_preserved(self):
        source = "YOUR_NVDAREMOTE_KEY = 'synthetic'\n"
        self.assertEqual(remote_access._patch_legacy_customization_braille_cells(source), source)

    def test_installer_updates_only_a_temporary_configuration_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "orca-customizations.py"
            path.write_text(fixtures.LegacyConfigTests.CONFIG_SOURCE
                            + "\ndef _dbg(message):\n    return\n"
                            + remote_access._LEGACY_CUSTOMIZATION_BRAILLE_SOURCE)
            config = remote_access.RemoteAccessConfig(key="synthetic")
            remote_access.update_legacy_orca_customizations(config, path)
            updated = path.read_text()
            self.assertTrue(remote_access.legacy_customization_braille_cells_patch_current(updated))
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), updated)


if __name__ == "__main__":
    unittest.main()
