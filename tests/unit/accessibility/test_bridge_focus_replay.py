import unittest
from unittest import mock

from tests.bridge_stubs import GLibError, import_braille_bridge
from tests.unit.accessibility.test_a11y_model_bounds import Node

bridge = import_braille_bridge()


class SpeechLink:
    ready = True

    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append((text, interrupt))
        return True


class BrailleLink:
    num_cells = 40

    def __init__(self):
        self.shown = []

    def display(self, cells):
        self.shown.append(list(cells))
        return True


def make():
    speech, braille = SpeechLink(), BrailleLink()
    return bridge.Bridge(speech, braille_link=braille), speech, braille


class FocusReplayTests(unittest.TestCase):
    def test_speech_ready_says_ready_then_the_live_focus_without_interrupting(self):
        b, speech, braille = make()
        with mock.patch.object(b, "_find_focus_target", return_value=(Node("Save", "focused"), True)):
            b.on_speech_ready()
        self.assertEqual(
            speech.spoken,
            [(bridge.READY_TEXT, False), ("Save, push button", False)],
        )
        self.assertEqual(len(braille.shown), 2)  # ready text, then the focus
        self.assertEqual(braille.shown[-1], bridge.text_to_braille_cells("Save, push button", 40))

    def test_braille_ready_refreshes_braille_only(self):
        b, speech, braille = make()
        with mock.patch.object(b, "_find_focus_target", return_value=(Node("Save", "focused"), True)):
            b.on_braille_ready()
        self.assertEqual(speech.spoken, [])
        self.assertEqual(len(braille.shown), 1)

    def test_speech_and_braille_replays_do_not_use_up_each_others_repeat_window(self):
        b, speech, braille = make()
        node = Node("Save", "focused")
        with mock.patch.object(b, "_find_focus_target", return_value=(node, True)):
            b.on_speech_ready()
            b.on_braille_ready()
        self.assertEqual(len(braille.shown), 3)

    def test_nothing_focused_or_unfindable_replays_nothing(self):
        b, speech, braille = make()
        for result in ((None, True), (None, False)):
            with mock.patch.object(b, "_find_focus_target", return_value=result):
                b.replay_focus()
        self.assertEqual((speech.spoken, braille.shown), ([], []))

    def test_dead_application_during_replay_is_ignored(self):
        b, speech, braille = make()
        with mock.patch.object(b, "_find_focus_target", side_effect=GLibError("gone")):
            b.replay_focus()
        self.assertEqual((speech.spoken, braille.shown), ([], []))

    def test_unnamed_control_is_replayed_by_role(self):
        b, speech, _ = make()
        with mock.patch.object(b, "_find_focus_target", return_value=(Node("", "focused", role="text"), True)):
            b.replay_focus()
        self.assertEqual(speech.spoken, [("text", False)])


if __name__ == "__main__":
    unittest.main()
