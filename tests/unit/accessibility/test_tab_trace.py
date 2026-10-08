import unittest

from diagnostics.x11.tab_trace import (
    TabCorrelator,
    parse_xi2_key_presses,
    tab_keycodes_from_xmodmap,
)

XI2_SAMPLE = """\
EVENT type 13 (RawKeyPress)
\tdevice: 3 (3)
\ttime: 1000
\tdetail: 23
\tflags:
EVENT type 14 (RawKeyRelease)
\tdevice: 3 (3)
\ttime: 1010
\tdetail: 23
EVENT type 13 (RawKeyPress)
\tdevice: 3 (3)
\ttime: 1500
\tdetail: 36
EVENT type 17 (RawMotion)
\tdevice: 2 (2)
\tdetail: 0
"""


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ParseTests(unittest.TestCase):
    def test_only_key_presses_are_yielded(self):
        self.assertEqual(list(parse_xi2_key_presses(XI2_SAMPLE.splitlines())), [23, 36])

    def test_garbage_detail_is_ignored(self):
        text = "EVENT type 13 (RawKeyPress)\n  detail: abc\nEVENT type 13 (RawKeyPress)\n  detail: 23\n"
        self.assertEqual(list(parse_xi2_key_presses(text.splitlines())), [23])

    def test_tab_keycodes_from_xmodmap(self):
        text = (
            "keycode  22 = BackSpace BackSpace BackSpace BackSpace\n"
            "keycode  23 = Tab ISO_Left_Tab Tab ISO_Left_Tab\n"
            "keycode 133 = Super_L NoSymbol Super_L\n"
        )
        self.assertEqual(tab_keycodes_from_xmodmap(text), {23})


class CorrelatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.c = TabCorrelator(window=0.6, clock=self.clock)

    def test_focus_event_matches_the_tab_that_preceded_it(self):
        self.c.tab_pressed()
        self.clock.now += 0.04
        self.assertIn("Tab #1 -> focus event after 0.04s: OK", self.c.focus_event("OK"))
        self.assertEqual(self.c.expire(), [])

    def test_tab_without_a_focus_event_is_reported_after_the_window(self):
        self.c.tab_pressed()
        self.clock.now += 0.5
        self.assertEqual(self.c.expire(), [])
        self.clock.now += 0.2
        self.assertEqual(self.c.expire(), ["Tab #1 -> NO AT-SPI focus event within 0.6s"])
        self.assertEqual(self.c.unmatched, 1)

    def test_focus_event_without_a_tab_is_ignored(self):
        self.assertIsNone(self.c.focus_event("mouse click"))

    def test_events_pair_with_tabs_in_order(self):
        self.c.tab_pressed()
        self.c.tab_pressed()
        self.assertIn("Tab #1", self.c.focus_event("A"))
        self.assertIn("Tab #2", self.c.focus_event("B"))

    def test_summary_counts(self):
        self.c.tab_pressed()
        self.c.focus_event("A")
        self.c.tab_pressed()
        self.clock.now += 1
        self.c.expire()
        self.assertEqual(
            self.c.summary(), "2 Tab press(es) reached X; 1 produced an AT-SPI focus event, 1 did not."
        )


if __name__ == "__main__":
    unittest.main()
