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


class FakeRect:
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class FakeComponent:
    def __init__(self, rect):
        self.rect = rect
        self.last_coord_type = None

    def get_extents(self, coord_type):
        self.last_coord_type = coord_type
        return self.rect


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
        component_iface=None,
    ):
        self.name = name
        self.role = role
        self.parent = parent
        self.children = []
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)
        self.description = description
        self.states = states
        self.value_iface = value_iface
        self.component_iface = component_iface
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

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]

    def get_state_set(self):
        return FakeStateSet(*self.states)

    def get_value_iface(self):
        return self.value_iface

    def get_component_iface(self):
        return self.component_iface


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

    def test_screen_bounds_are_serialized_when_requested(self):
        component = FakeComponent(FakeRect(10, 20, 300, 40))
        button = FakeAccessible(
            "Save",
            "push button",
            component_iface=component,
        )
        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            button,
            coord_type=0,
        )
        self.assertEqual(payload["objects"][0]["bounds"], [10, 20, 300, 40])
        self.assertEqual(component.last_coord_type, 0)

    def test_missing_component_has_null_bounds(self):
        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            self.button,
            coord_type=0,
        )
        self.assertIsNone(payload["objects"][0]["bounds"])

    def test_negative_component_size_is_ignored(self):
        component = FakeComponent(FakeRect(10, 20, -1, -1))
        button = FakeAccessible(
            "Hidden",
            "push button",
            component_iface=component,
        )
        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            button,
            coord_type=0,
        )
        self.assertIsNone(payload["objects"][0]["bounds"])

    def test_focus_neighborhood_includes_siblings_and_focus_children(self):
        app = FakeAccessible("App", "application")
        dialog = FakeAccessible("Dialog", "dialog", app)
        before = FakeAccessible("Before", "push button", dialog)
        focused = FakeAccessible(
            "Save",
            "push button",
            dialog,
            states=("focusable",),
        )
        after = FakeAccessible("After", "push button", dialog)
        child = FakeAccessible("Inner", "label", focused)

        payload = build_focus_payload("object:state-changed:focused", 1, focused)
        by_id = {item["id"]: item for item in payload["objects"]}

        self.assertIn(object_id(before), by_id)
        self.assertIn(object_id(after), by_id)
        self.assertIn(object_id(child), by_id)
        self.assertEqual(
            by_id[object_id(dialog)]["child_ids"],
            [object_id(before), object_id(focused), object_id(after)],
        )
        self.assertEqual(
            by_id[object_id(focused)]["child_ids"],
            [object_id(child)],
        )

    def test_child_ids_preserve_atspi_child_order(self):
        dialog = FakeAccessible("Dialog", "dialog", self.app)
        first = FakeAccessible("First", "push button", dialog)
        focused = FakeAccessible("Focused", "push button", dialog)
        third = FakeAccessible("Third", "push button", dialog)
        payload = build_focus_payload("object:state-changed:focused", 1, focused)
        by_id = {item["id"]: item for item in payload["objects"]}
        self.assertEqual(
            by_id[object_id(dialog)]["child_ids"],
            [object_id(first), object_id(focused), object_id(third)],
        )

    def test_focus_child_ids_are_serialized(self):
        container = FakeAccessible("Group", "panel", self.dialog)
        first = FakeAccessible("One", "label", container)
        second = FakeAccessible("Two", "label", container)
        payload = build_focus_payload("object:state-changed:focused", 1, container)
        by_id = {item["id"]: item for item in payload["objects"]}
        self.assertEqual(
            by_id[object_id(container)]["child_ids"],
            [object_id(first), object_id(second)],
        )
        self.assertEqual(by_id[object_id(first)]["parent_id"], object_id(container))
        self.assertEqual(by_id[object_id(second)]["parent_id"], object_id(container))

    def test_max_objects_truncates_neighborhood_not_focus_chain(self):
        dialog = FakeAccessible("Dialog", "dialog", self.app)
        focused = FakeAccessible("Focused", "push button", dialog)
        for index in range(20):
            FakeAccessible(f"Sibling {index}", "push button", dialog)

        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            focused,
            max_objects=4,
        )
        ids = {item["id"] for item in payload["objects"]}
        self.assertEqual(len(payload["objects"]), 4)
        self.assertIn(object_id(focused), ids)
        self.assertIn(object_id(dialog), ids)
        self.assertIn(object_id(self.app), ids)

    def test_child_ids_never_reference_truncated_objects(self):
        dialog = FakeAccessible("Dialog", "dialog", self.app)
        focused = FakeAccessible("Focused", "push button", dialog)
        for index in range(10):
            FakeAccessible(f"Sibling {index}", "push button", dialog)

        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            focused,
            max_objects=5,
        )
        ids = {item["id"] for item in payload["objects"]}
        for item in payload["objects"]:
            self.assertTrue(set(item["child_ids"]) <= ids)

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
