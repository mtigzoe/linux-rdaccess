import unittest

import announcer as A
from announcer import Announcer


class Obj:
    """Duck-typed stand-in for Atspi.Accessible."""

    def __init__(self, name="", role="push button", description="", focused=True):
        self._name, self._role, self._description, self.focused = name, role, description, focused
        self.calls = 0

    def get_name(self):
        self.calls += 1
        return self._name

    def get_role_name(self):
        self.calls += 1
        return self._role

    def get_description(self):
        self.calls += 1
        return self._description


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class AnnouncerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.a = Announcer(is_focused=lambda o: o.focused, clock=self.clock)

    def test_focus_gained_speaks_name_and_role_and_interrupts(self):
        r = self.a.handle(A.FOCUS, 1, Obj("Save", "push button"))
        self.assertEqual((r.text, r.interrupt), ("Save, push button", True))

    def test_focus_lost_is_silent_and_touches_nothing(self):
        o = Obj("Save")
        self.assertIsNone(self.a.handle(A.FOCUS, 0, o))
        self.assertEqual(o.calls, 0)

    def test_geometry_and_other_noise_never_touches_the_accessible(self):
        o = Obj("Save")
        for noisy in (
            "object:bounds-changed",
            "object:text-changed:insert",
            "object:property-change:accessible-value",
            "window:deactivate",
        ):
            self.assertIsNone(self.a.handle(noisy, 1, o))
        self.assertEqual(o.calls, 0)  # no D-Bus round trips for noise

    def test_unnamed_focus_speaks_role_only(self):
        self.assertEqual(self.a.handle(A.FOCUS, 1, Obj("", "text")).text, "text")

    def test_unnamed_focus_without_role_is_silent(self):
        self.assertIsNone(self.a.handle(A.FOCUS, 1, Obj("", "")))

    def test_whitespace_only_name_counts_as_empty(self):
        self.assertIsNone(self.a.handle(A.WINDOW_ACTIVATE, 0, Obj("  \n ", "frame")))

    def test_unnamed_window_and_selection_are_silent(self):
        self.assertIsNone(self.a.handle(A.WINDOW_ACTIVATE, 0, Obj("", "frame")))
        self.assertIsNone(self.a.handle(A.SELECTED, 1, Obj("", "list item")))

    def test_window_activate(self):
        r = self.a.handle(A.WINDOW_ACTIVATE, 0, Obj("Terminal", "frame"))
        self.assertEqual(r.text, "Terminal, frame")

    def test_selected_adds_suffix_and_deselect_is_silent(self):
        item = Obj("Bananas", "list item")
        self.assertEqual(self.a.handle(A.SELECTED, 1, item).text, "Bananas, list item, selected")
        self.assertIsNone(self.a.handle(A.SELECTED, 0, item))

    def test_active_descendant_announces_the_child_not_the_container(self):
        """Regression: the container must not be spoken when any_data holds the child."""
        tree = Obj("Fruit", "table")
        child = Obj("Apples", "table cell")
        r = self.a.handle(A.ACTIVE_DESCENDANT, 0, tree, any_data=child)
        self.assertEqual(r.text, "Apples, table cell")
        self.assertEqual(tree.calls, 0)

    def test_active_descendant_without_a_child_is_ignored(self):
        """Regression: falling back to the source spoke the container on every cleared event."""
        tree = Obj("Fruit", "table")
        self.assertIsNone(self.a.handle(A.ACTIVE_DESCENDANT, 0, tree, any_data=None))
        self.assertIsNone(self.a.handle(A.ACTIVE_DESCENDANT, 0, tree, any_data="not an object"))
        self.assertEqual(tree.calls, 0)

    def test_name_change_only_for_focused_object_and_does_not_interrupt(self):
        focused = Obj("Pause", "push button", focused=True)
        other = Obj("12:41", "label", focused=False)
        r = self.a.handle(A.NAME_CHANGED, 0, focused)
        self.assertEqual((r.text, r.interrupt), ("Pause, push button", False))
        self.assertIsNone(self.a.handle(A.NAME_CHANGED, 0, other))

    def test_description_change_uses_any_data_then_falls_back(self):
        o = Obj("Field", "text", description="fallback text")
        self.assertEqual(self.a.handle(A.DESCRIPTION_CHANGED, 0, o, any_data="new hint").text, "new hint")
        self.clock.now += 5
        self.assertEqual(self.a.handle(A.DESCRIPTION_CHANGED, 0, o, any_data=None).text, "fallback text")

    def test_empty_description_is_silent(self):
        self.assertIsNone(self.a.handle(A.DESCRIPTION_CHANGED, 0, Obj("x", description="")))

    def test_description_change_on_unfocused_object_is_silent(self):
        o = Obj("x", description="hint", focused=False)
        self.assertIsNone(self.a.handle(A.DESCRIPTION_CHANGED, 0, o, any_data="hint"))

    def test_burst_of_focus_selected_and_descendant_is_spoken_once(self):
        """One GTK keypress emits several events for the same item."""
        item = Obj("Bananas", "list item")
        first = self.a.handle(A.FOCUS, 1, item)
        self.clock.now += 0.05
        second = self.a.handle(A.SELECTED, 1, item)
        third = self.a.handle(A.ACTIVE_DESCENDANT, 0, Obj("Fruit", "list"), any_data=item)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNone(third)

    def test_alternating_duplicates_are_suppressed(self):
        """Regression: the old single-slot dedupe let A,B,A,B through."""
        a, b = Obj("A", "push button"), Obj("B", "push button")
        texts = []
        for o in (a, b, a, b):
            self.clock.now += 0.1
            r = self.a.handle(A.FOCUS, 1, o)
            if r:
                texts.append(r.text)
        self.assertEqual(texts, ["A, push button", "B, push button"])

    def test_same_item_is_spoken_again_after_the_window(self):
        o = Obj("Save", "push button")
        self.assertIsNotNone(self.a.handle(A.FOCUS, 1, o))
        self.clock.now += 1.0
        self.assertIsNotNone(self.a.handle(A.FOCUS, 1, o))

    def test_recent_table_stays_small(self):
        for i in range(500):
            self.clock.now += 0.01
            self.a.handle(A.FOCUS, 1, Obj(f"item {i}", "list item"))
        self.assertLessEqual(len(self.a._recent), 130)


if __name__ == "__main__":
    unittest.main()
