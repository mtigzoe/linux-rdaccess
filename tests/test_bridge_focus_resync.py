import unittest
from unittest import mock

from a11y_model import object_id
from tests.bridge_stubs import GLibError, import_braille_bridge
from tests.unit.accessibility.test_a11y_model_bounds import Node

bridge = import_braille_bridge()


class SpeechLink:
    ready = True

    def speak(self, text, interrupt=False):
        return True

    def poll(self):
        pass


class FakeA11yLink:
    def __init__(self, last_focus_id=None):
        self.last_focus_id = last_focus_id
        self.refreshed, self.cleared = [], 0

    def refresh_focus(self, **payload):
        self.refreshed.append(payload)

    def clear_focus(self):
        self.cleared += 1


def make(last_focus_id=None):
    link = FakeA11yLink(last_focus_id)
    return bridge.Bridge(SpeechLink(), a11y_link=link), link


class ResyncFocusTests(unittest.TestCase):
    def test_incomplete_search_keeps_the_cached_focus(self):
        b, link = make()
        with mock.patch.object(bridge, "find_focused_object_ex", return_value=(None, False)):
            b.resync_focus()
        self.assertEqual((link.cleared, link.refreshed), (0, []))

    def test_complete_search_with_nothing_focused_clears_the_cache(self):
        b, link = make()
        with mock.patch.object(bridge, "find_focused_object_ex", return_value=(None, True)):
            b.resync_focus()
        self.assertEqual((link.cleared, link.refreshed), (1, []))

    def test_found_focus_is_handed_to_the_link(self):
        b, link = make()
        node = Node("OK", "focused")
        with mock.patch.object(bridge, "find_focused_object_ex", return_value=(node, True)):
            b.resync_focus()
        self.assertEqual(len(link.refreshed), 1)
        self.assertEqual(link.cleared, 0)

    def test_previous_focus_object_is_checked_before_any_desktop_walk(self):
        node = Node("OK", "focused")
        b, link = make(last_focus_id=object_id(node))
        b._a11y_objects[object_id(node)] = node
        with mock.patch.object(bridge, "is_focused", return_value=True), mock.patch.object(
            bridge, "find_focused_object_ex"
        ) as search:
            b.resync_focus()
        search.assert_not_called()
        self.assertEqual(len(link.refreshed), 1)

    def test_dead_or_unfocused_previous_object_falls_back_to_the_search(self):
        for outcome in (False, GLibError("gone")):
            node, other = Node("old", "focused"), Node("new", "focused")
            b, link = make(last_focus_id=object_id(node))
            b._a11y_objects[object_id(node)] = node
            check = mock.Mock(side_effect=outcome) if isinstance(outcome, Exception) else mock.Mock(return_value=outcome)
            with mock.patch.object(bridge, "is_focused", check), mock.patch.object(
                bridge, "find_focused_object_ex", return_value=(other, True)
            ) as search:
                b.resync_focus()
            search.assert_called_once()
            self.assertEqual(link.refreshed[0]["focus_id"], object_id(other))


if __name__ == "__main__":
    unittest.main()
