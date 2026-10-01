import unittest

from a11y_model import build_focus_payload, object_id


class FakeState:
    def __init__(self, value_nick):
        self.value_nick = value_nick


class FakeStateSet:
    def __init__(self, *states):
        self.states = [FakeState(state) for state in states]

    def get_states(self):
        return self.states


class FakeValue:
    def __init__(self, current=None, text=""):
        self.current = current
        self.text = text

    def get_text(self):
        return self.text

    def get_current_value(self):
        return self.current


class FakeAccessible:
    _next_hash = 100

    def __init__(
        self,
        name,
        role,
        parent=None,
        description="",
        *,
        states=(),
        value_iface=None,
    ):
        self.name = name
        self.role = role
        self.parent = parent
        self.description = description
        self.states = states
        self.value_iface = value_iface
        self._hash = FakeAccessible._next_hash
        FakeAccessible._next_hash += 1

    def __hash__(self):
        return self._hash

    def get_name(self):
        return self.name

    def get_role_name(self):
        return self.role

    def get_description(self):
        return self.description

    def get_parent(self):
        return self.parent

    def get_state_set(self):
        return FakeStateSet(*self.states)

    def get_value_iface(self):
        return self.value_iface


class A11yModelTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeAccessible("Test App", "application")
        self.dialog = FakeAccessible("Settings", "dialog", self.app)
        self.button = FakeAccessible(
            "Save",
            "push button",
            self.dialog,
            "Save changes",
            states=("focusable", "enabled"),
        )

    def test_focus_payload_contains_focus_and_ancestors(self):
        payload = build_focus_payload("object:state-changed:focused", 1, self.button)
        self.assertEqual(payload["focus_id"], object_id(self.button))
        by_id = {item["id"]: item for item in payload["objects"]}
        self.assertEqual(by_id[object_id(self.button)]["parent_id"], object_id(self.dialog))
        self.assertEqual(by_id[object_id(self.dialog)]["parent_id"], object_id(self.app))
        self.assertIsNone(by_id[object_id(self.app)]["parent_id"])
        self.assertEqual(by_id[object_id(self.button)]["name"], "Save")
        self.assertEqual(by_id[object_id(self.button)]["role"], "push button")
        self.assertEqual(by_id[object_id(self.button)]["description"], "Save changes")
        self.assertEqual(
            by_id[object_id(self.button)]["states"],
            ["enabled", "focusable", "focused"],
        )

    def test_focus_event_adds_focused_if_state_set_lags(self):
        button = FakeAccessible("Save", "push button", states=("focusable",))
        payload = build_focus_payload("object:state-changed:focused", 1, button)
        self.assertEqual(payload["objects"][0]["states"], ["focusable", "focused"])

    def test_state_names_are_normalized(self):
        button = FakeAccessible(
            "Choice",
            "check box",
            states=("half-checked", "READ_ONLY", "Atspi_State_Selected"),
        )
        payload = build_focus_payload("object:state-changed:focused", 1, button)
        self.assertEqual(
            payload["objects"][0]["states"],
            ["focused", "half checked", "read only", "selected"],
        )

    def test_human_readable_value_text_wins(self):
        slider = FakeAccessible(
            "Volume",
            "slider",
            value_iface=FakeValue(current=75.0, text="75 percent"),
        )
        payload = build_focus_payload("object:state-changed:focused", 1, slider)
        self.assertEqual(payload["objects"][0]["value"], "75 percent")

    def test_numeric_value_is_serialized(self):
        slider = FakeAccessible(
            "Volume",
            "slider",
            value_iface=FakeValue(current=75.0),
        )
        payload = build_focus_payload("object:state-changed:focused", 1, slider)
        self.assertEqual(payload["objects"][0]["value"], "75")

    def test_focus_loss_is_not_sent(self):
        self.assertIsNone(build_focus_payload("object:state-changed:focused", 0, self.button))

    def test_active_descendant_uses_child(self):
        list_obj = FakeAccessible("Items", "list", self.dialog)
        item = FakeAccessible("First", "list item", list_obj)
        payload = build_focus_payload("object:active-descendant-changed", 0, list_obj, item)
        self.assertEqual(payload["focus_id"], object_id(item))

    def test_unrelated_event_is_ignored(self):
        self.assertIsNone(build_focus_payload("object:text-changed:insert", 1, self.button))

    def test_cycle_is_bounded(self):
        a = FakeAccessible("A", "panel")
        b = FakeAccessible("B", "panel", a)
        a.parent = b
        payload = build_focus_payload("object:state-changed:focused", 1, b)
        self.assertEqual(len(payload["objects"]), 2)


if __name__ == "__main__":
    unittest.main()
