"""Tests for atspi_nvda_braille_bridge (needs the Atspi typelib and liblouis; skipped without them)."""

import unittest
import logging
import contextlib
import io
from unittest import mock

try:
    import gi

    gi.require_version("Atspi", "2.0")
    import louis

    import atspi_nvda_bridge as speech_bridge
    import atspi_nvda_braille_bridge as bridge
except (ImportError, ValueError) as exc:  # pragma: no cover
    raise unittest.SkipTest(f"Atspi or liblouis not available: {exc}")

assert louis  # imported to skip this module cleanly where liblouis is missing


class FakeAccessible:
    def __init__(self, name="", role="push button"):
        self._name, self._role = name, role

    def get_name(self):
        return self._name

    def get_role_name(self):
        return self._role

    def get_description(self):
        return ""


class FakeEvent:
    def __init__(self, type, detail1=1, source=None, any_data=None):
        self.type, self.detail1, self.source, self.any_data = type, detail1, source, any_data


class SpeechLink:
    ready = True

    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append((text, interrupt))
        return True


class BrailleLink:
    def __init__(self, num_cells=80):
        self.num_cells = num_cells
        self.shown = []

    def display(self, cells):
        self.shown.append(list(cells))
        return True


class ListenerRegistrationTests(unittest.TestCase):
    def test_braille_bridge_listens_broadly_like_the_speech_bridge(self):
        """Regression: per-event registrations were unreliable in the xrdp session (recorded in the
        speech bridge); the braille bridge had drifted to narrow registrations."""
        self.assertEqual(bridge.LISTEN_TO, ("object", "window"))
        self.assertEqual(bridge.LISTEN_TO, speech_bridge.LISTEN_TO)


class SpeechAndBrailleAgreeTests(unittest.TestCase):
    def test_dry_run_output_does_not_persist_speech(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            bridge.DryRunLink().speak('private-speech-text', interrupt=True)
        self.assertNotIn('private-speech-text', output.getvalue())

    def test_debugging_does_not_log_application_text_or_callback_exceptions(self):
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        b, speech, braille = self.make()
        secret = 'private-application-text'
        with self.assertLogs('bridge', level='DEBUG') as logs:
            b._on_event(FakeEvent('object:state-changed:focused', 1, FakeAccessible(secret)))
            with mock.patch.object(b.announcer, 'handle', side_effect=RuntimeError(secret)):
                b._on_event(FakeEvent('object:state-changed:focused', 1, FakeAccessible(secret)))
        self.assertNotIn(secret, str(logs.output))
        self.assertEqual(speech.spoken, [(secret + ', push button', True)])

    def make(self, cells=80):
        speech, braille = SpeechLink(), BrailleLink(cells)
        return bridge.Bridge(speech, braille_link=braille), speech, braille

    def decode(self, cells):
        return "".join(chr(0x2800 + c) for c in cells)

    def test_one_accepted_announcement_reaches_both_speech_and_braille(self):
        b, speech, braille = self.make()
        b._on_event(FakeEvent("object:state-changed:focused", 1, FakeAccessible("Cancel")))
        self.assertEqual(speech.spoken, [("Cancel, push button", True)])
        self.assertEqual(len(braille.shown), 1)
        expected = bridge.text_to_braille_cells("Cancel, push button", 80)
        self.assertEqual(braille.shown[0], expected)

    def test_a_filtered_event_reaches_neither(self):
        b, speech, braille = self.make()
        b._on_event(FakeEvent("object:bounds-changed", 0, FakeAccessible("Cancel")))
        b._on_event(FakeEvent("object:state-changed:focused", 0, FakeAccessible("Cancel")))
        self.assertEqual((speech.spoken, braille.shown), ([], []))

    def test_each_of_two_identically_labelled_controls_reaches_both_outputs(self):
        b, speech, braille = self.make()
        # Retain both simulated controls: ephemeral Python objects can reuse
        # id(), unlike the stable AT-SPI identities exercised by this case.
        first, second = FakeAccessible("Browse"), FakeAccessible("Browse")
        b._on_event(FakeEvent("object:state-changed:focused", 1, first))
        b._on_event(FakeEvent("object:state-changed:focused", 1, second))
        self.assertEqual(len(speech.spoken), 2)
        self.assertEqual(len(braille.shown), 2)

    def test_cell_count_follows_the_display_not_a_hardcoded_80(self):
        for width in (12, 20, 32, 40, 64, 80):
            b, _, braille = self.make(cells=width)
            b._on_event(FakeEvent("object:state-changed:focused", 1, FakeAccessible("OK")))
            self.assertEqual(len(braille.shown[-1]), width, width)

    def test_text_is_clipped_to_the_display_width_not_wrapped(self):
        cells = bridge.text_to_braille_cells("x" * 500, 40)
        self.assertEqual(len(cells), 40)

    def test_braille_uses_ueb_grade_2(self):
        self.assertEqual(bridge.BRAILLE_TABLE, ["en-ueb-g2.ctb"])
        # Grade 2 contracts "the": one cell, dots 2-3-4-6 (0x2E) -- grade 1 would spell three cells.
        self.assertEqual(bridge.text_to_braille_cells("the", 4)[:2], [0b101110, 0])

    def test_ready_text_goes_to_both_outputs(self):
        b, speech, braille = self.make()
        b.say_ready()
        self.assertEqual(speech.spoken, [(bridge.READY_TEXT, False)])
        self.assertEqual(len(braille.shown), 1)


if __name__ == "__main__":
    unittest.main()
