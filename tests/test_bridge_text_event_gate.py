import unittest
from unittest import mock

from a11y_model import object_id
from tests.bridge_stubs import import_braille_bridge
from tests.test_a11y_model_bounds import Node

bridge = import_braille_bridge()


class Event:
    def __init__(self, type, source):
        self.type, self.source, self.detail1, self.any_data = type, source, 0, None


class SpeechLink:
    ready = True

    def speak(self, *a, **k):
        return True


class A11y:
    def __init__(self):
        self.updates = []

    def send_text_update(self, **update):
        self.updates.append(update)
        return True


class TextEventGateTests(unittest.TestCase):
    def test_text_events_from_unrelated_objects_cost_no_state_query(self):
        link = A11y()
        b = bridge.Bridge(SpeechLink(), a11y_link=link)
        with mock.patch.object(bridge, "is_focused") as focused:
            for _ in range(50):
                b._on_event(Event("object:text-changed:insert", Node("terminal output")))
        focused.assert_not_called()
        self.assertEqual(link.updates, [])

    def test_text_event_for_the_snapshot_object_is_still_sent(self):
        node = Node("Name", "focused", role="text")
        link = A11y()
        b = bridge.Bridge(SpeechLink(), a11y_link=link)
        b._a11y_objects[object_id(node)] = node
        update = {"object_id": object_id(node), "event": "caret", "text_supported": True,
                  "text": "hi", "text_truncated": False, "caret_offset": 1,
                  "selection_start": None, "selection_end": None}
        with mock.patch.object(bridge, "is_focused", return_value=True), mock.patch.object(
            bridge, "build_text_update", return_value=update
        ):
            b._on_event(Event("object:text-caret-moved", node))
        self.assertEqual(link.updates, [update])

    def test_snapshot_object_that_lost_focus_is_not_sent(self):
        node = Node("Name", role="text")
        link = A11y()
        b = bridge.Bridge(SpeechLink(), a11y_link=link)
        b._a11y_objects[object_id(node)] = node
        with mock.patch.object(bridge, "is_focused", return_value=False):
            b._on_event(Event("object:text-caret-moved", node))
        self.assertEqual(link.updates, [])


if __name__ == "__main__":
    unittest.main()
