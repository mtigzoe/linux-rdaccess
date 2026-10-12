import unittest
from unittest import mock

import a11y_model
from a11y_model import object_id
from tests.bridge_stubs import import_braille_bridge
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeText

bridge = import_braille_bridge()
LIMIT = a11y_model.MAX_FOCUS_TEXT_CHARS


class Event:
    def __init__(self, type, source, detail1=0):
        self.type, self.source, self.detail1, self.any_data = type, source, detail1, None


class SpeechLink:
    ready = True

    def speak(self, *a, **k):
        return True


class A11y:
    last_focus_id = None

    def __init__(self):
        self.focus, self.refreshed, self.updates, self.cleared = [], [], [], 0

    def send_focus(self, **payload):
        self.focus.append(payload)
        return True

    def refresh_focus(self, **payload):
        self.refreshed.append(payload)

    def clear_focus(self):
        self.cleared += 1

    def send_text_update(self, **update):
        self.updates.append(update)
        return True


def editor(count, caret):
    return FakeAccessible("Editor", "text", text_iface=FakeText("x" * count, caret=caret))


class BridgeLongTextTests(unittest.TestCase):
    """The AT-SPI bridge must not show NVDA the document start for a caret beyond it.

    The snapshot carries at most MAX_FOCUS_TEXT_CHARS characters. With the real
    caret past them the payload holds the document start and no caret, so NVDA would
    show the wrong text; the semantic channel must stay silent instead.
    """

    def setUp(self):
        self.link = A11y()
        self.bridge = bridge.Bridge(SpeechLink(), a11y_link=self.link)

    def focus(self, node):
        self.bridge._on_event(Event("object:state-changed:focused", node, 1))

    def caret_moved(self, node):
        self.bridge._a11y_objects[object_id(node)] = node
        with mock.patch.object(bridge, "is_focused", return_value=True):
            self.bridge._on_event(Event("object:text-caret-moved", node))

    def test_focus_with_caret_beyond_the_window_sends_no_semantic_focus(self):
        for caret in (LIMIT + 1, 15000, 20000):
            with self.subTest(caret=caret):
                self.link.focus.clear()
                self.focus(editor(20000, caret))
                self.assertTrue(not self.link.focus, "semantic focus sent for a caret outside its window")

    def test_focus_with_caret_inside_the_window_is_still_sent(self):
        for caret in (0, 100, LIMIT):
            with self.subTest(caret=caret):
                self.link.focus.clear()
                self.focus(editor(20000, caret))
                self.assertEqual(len(self.link.focus), 1)

    def test_caret_moving_beyond_the_window_sends_no_text_update(self):
        for caret in (LIMIT + 1, 20000):
            with self.subTest(caret=caret):
                self.link.updates.clear()
                self.caret_moved(editor(20000, caret))
                self.assertTrue(not self.link.updates, "text update sent for a caret outside its window")

    def test_caret_inside_the_window_still_sends_a_text_update(self):
        for caret in (0, 100, LIMIT):
            with self.subTest(caret=caret):
                self.link.updates.clear()
                self.caret_moved(editor(20000, caret))
                self.assertEqual(len(self.link.updates), 1)

    def test_resync_with_caret_beyond_the_window_does_not_replay_wrong_text(self):
        node = editor(20000, 15000)
        with mock.patch.object(self.bridge, "_find_focus_target", return_value=(node, True)):
            self.bridge.resync_focus()
        self.assertTrue(not self.link.refreshed, "wrong-text focus refreshed after reconnect")
        self.assertEqual(self.link.cleared, 1)


class MovingText(FakeText):
    """Text whose caret the test can move after the object has been focused."""

    def __init__(self, text, caret):
        super().__init__(text, caret=caret)
        self.position = caret

    def get_caret_offset(self):
        return self.position


class BridgeLongTextResumptionTests(unittest.TestCase):
    """Once the caret returns inside the window NVDA must get the object again.

    A focus snapshot withheld for a caret beyond the window never reached NVDA, so a
    plain text update for that object would address an object NVDA does not have.
    """

    setUp = BridgeLongTextTests.setUp
    focus = BridgeLongTextTests.focus
    caret_moved = BridgeLongTextTests.caret_moved

    def long_editor(self, caret):
        text = MovingText("x" * 20000, caret)
        return FakeAccessible("Editor", "text", text_iface=text), text

    def test_caret_returning_inside_the_window_sends_the_withheld_focus_once(self):
        node, text = self.long_editor(15000)
        self.focus(node)
        self.assertEqual(self.link.focus, [])
        for position in (100, 200):
            text.position = position
            self.caret_moved(node)
        self.assertEqual(len(self.link.focus), 1, "withheld focus was not sent on resumption")
        item = next(i for i in self.link.focus[0]["objects"] if i["id"] == self.link.focus[0]["focus_id"])
        self.assertEqual(item["caret_offset"], 100)
        self.assertEqual([u["caret_offset"] for u in self.link.updates], [200])

    def test_resync_beyond_the_window_resumes_when_the_caret_returns(self):
        node, text = self.long_editor(15000)
        with mock.patch.object(self.bridge, "_find_focus_target", return_value=(node, True)):
            self.bridge.resync_focus()
        text.position = 100
        self.caret_moved(node)
        self.assertEqual(len(self.link.focus), 1, "withheld focus was not sent on resumption")
        self.assertEqual(self.link.updates, [])


if __name__ == "__main__":
    unittest.main()
