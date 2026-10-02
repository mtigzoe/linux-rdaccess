import unittest

from a11y_model import (
    action_names,
    build_focus_payload,
    build_text_update,
    find_focused_object,
    object_id,
    perform_action,
)


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


class FakeAction:
    def __init__(self, names, results=None):
        self.names = list(names)
        self.results = list(results) if results is not None else [True] * len(self.names)
        self.performed = []

    def get_n_actions(self):
        return len(self.names)

    def get_action_name(self, index):
        return self.names[index]

    def do_action(self, index):
        self.performed.append(index)
        return self.results[index]


class FakeSelection:
    def __init__(self, start_offset, end_offset):
        self.start_offset = start_offset
        self.end_offset = end_offset


class FakeText:
    def __init__(self, text, *, caret=0, selection=None):
        self.text = text
        self.caret = caret
        self.selection = selection

    def get_character_count(self):
        return len(self.text)

    def get_text(self, start, end):
        return self.text[start:end]

    def get_caret_offset(self):
        return self.caret

    def get_n_selections(self):
        return 1 if self.selection is not None else 0

    def get_selection(self, index):
        if index != 0 or self.selection is None:
            raise IndexError(index)
        return FakeSelection(*self.selection)


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
        action_iface=None,
        text_iface=None,
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
        self.action_iface = action_iface
        self.text_iface = text_iface
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

    def get_action_iface(self):
        return self.action_iface

    def get_text_iface(self):
        return self.text_iface


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

    def test_focused_text_caret_and_selection_are_serialized(self):
        text = FakeText("hello world", caret=5, selection=(1, 4))
        field = FakeAccessible("Editor", "text", text_iface=text)
        payload = build_focus_payload("object:state-changed:focused", 1, field)
        item = payload["objects"][0]
        self.assertTrue(item["text_supported"])
        self.assertEqual(item["text"], "hello world")
        self.assertFalse(item["text_truncated"])
        self.assertEqual(item["caret_offset"], 5)
        self.assertEqual(item["selection_start"], 1)
        self.assertEqual(item["selection_end"], 4)

    def test_nonfocused_neighbors_do_not_serialize_text(self):
        app = FakeAccessible("App", "application")
        dialog = FakeAccessible("Dialog", "dialog", app)
        focused = FakeAccessible("Save", "push button", dialog)
        neighbor = FakeAccessible(
            "Editor",
            "text",
            dialog,
            text_iface=FakeText("secret neighbor text", caret=3),
        )
        payload = build_focus_payload("object:state-changed:focused", 1, focused)
        by_id = {item["id"]: item for item in payload["objects"]}
        self.assertIn(object_id(neighbor), by_id)
        self.assertFalse(by_id[object_id(neighbor)]["text_supported"])
        self.assertEqual(by_id[object_id(neighbor)]["text"], "")
        self.assertIsNone(by_id[object_id(neighbor)]["caret_offset"])

    def test_empty_focused_text_still_reports_text_support(self):
        field = FakeAccessible("Editor", "text", text_iface=FakeText("", caret=0))
        payload = build_focus_payload("object:state-changed:focused", 1, field)
        item = payload["objects"][0]
        self.assertTrue(item["text_supported"])
        self.assertEqual(item["text"], "")
        self.assertEqual(item["caret_offset"], 0)

    def test_focused_text_is_bounded_and_marks_truncation(self):
        text = FakeText("x" * 9000, caret=9000)
        field = FakeAccessible("Editor", "text", text_iface=text)
        payload = build_focus_payload("object:state-changed:focused", 1, field)
        item = payload["objects"][0]
        self.assertEqual(len(item["text"]), 8192)
        self.assertTrue(item["text_truncated"])
        self.assertIsNone(item["caret_offset"])

    def test_invalid_selection_outside_bounded_text_is_dropped(self):
        text = FakeText("abcdef", caret=2, selection=(2, 99))
        field = FakeAccessible("Editor", "text", text_iface=text)
        payload = build_focus_payload("object:state-changed:focused", 1, field)
        item = payload["objects"][0]
        self.assertIsNone(item["selection_start"])
        self.assertIsNone(item["selection_end"])

    def test_caret_event_builds_text_update_for_registered_object(self):
        text = FakeText("hello world", caret=6, selection=None)
        field = FakeAccessible("Editor", "text", text_iface=text)
        registry = {}
        build_focus_payload(
            "object:state-changed:focused",
            1,
            field,
            object_registry=registry,
        )
        update = build_text_update(
            "object:text-caret-moved",
            field,
            object_registry=registry,
        )
        self.assertEqual(update["object_id"], object_id(field))
        self.assertEqual(update["event"], "caret")
        self.assertEqual(update["text"], "hello world")
        self.assertEqual(update["caret_offset"], 6)

    def test_selection_event_builds_caret_update(self):
        text = FakeText("hello", caret=4, selection=(1, 4))
        field = FakeAccessible("Editor", "text", text_iface=text)
        registry = {object_id(field): field}
        update = build_text_update(
            "object:text-selection-changed",
            field,
            object_registry=registry,
        )
        self.assertEqual(update["event"], "caret")
        self.assertEqual(update["selection_start"], 1)
        self.assertEqual(update["selection_end"], 4)

    def test_text_change_builds_text_change_update(self):
        text = FakeText("hello!", caret=6, selection=None)
        field = FakeAccessible("Editor", "text", text_iface=text)
        registry = {object_id(field): field}
        update = build_text_update(
            "object:text-changed:insert",
            field,
            object_registry=registry,
        )
        self.assertEqual(update["event"], "textChange")
        self.assertEqual(update["text"], "hello!")

    def test_text_update_rejects_stale_or_non_text_objects(self):
        text_field = FakeAccessible(
            "Editor",
            "text",
            text_iface=FakeText("hello", caret=1, selection=None),
        )
        self.assertIsNone(
            build_text_update(
                "object:text-caret-moved",
                text_field,
                object_registry={},
            ),
        )
        button = FakeAccessible("Save", "push button")
        self.assertIsNone(
            build_text_update(
                "object:text-caret-moved",
                button,
                object_registry={object_id(button): button},
            ),
        )

    def test_unrelated_event_does_not_build_text_update(self):
        field = FakeAccessible(
            "Editor",
            "text",
            text_iface=FakeText("hello", caret=1, selection=None),
        )
        self.assertIsNone(
            build_text_update(
                "object:state-changed:focused",
                field,
                object_registry={object_id(field): field},
            ),
        )

    def test_action_names_are_serialized_in_order(self):
        actions = FakeAction(["click", "show menu"])
        button = FakeAccessible("More", "push button", action_iface=actions)
        payload = build_focus_payload("object:state-changed:focused", 1, button)
        self.assertEqual(payload["objects"][0]["actions"], ["click", "show menu"])

    def test_blank_action_name_gets_stable_fallback(self):
        actions = FakeAction([""])
        button = FakeAccessible("Action", "push button", action_iface=actions)
        self.assertEqual(action_names(button), ["action 1"])

    def test_perform_action_calls_requested_atspi_action(self):
        actions = FakeAction(["click", "show menu"])
        button = FakeAccessible("More", "push button", action_iface=actions)
        self.assertTrue(perform_action(button, 1))
        self.assertEqual(actions.performed, [1])

    def test_perform_action_rejects_invalid_or_failed_actions(self):
        actions = FakeAction(["click"], results=[False])
        button = FakeAccessible("More", "push button", action_iface=actions)
        self.assertFalse(perform_action(button, -1))
        self.assertFalse(perform_action(button, 1))
        self.assertFalse(perform_action(button, 0))
        self.assertEqual(actions.performed, [0])

    def test_object_registry_contains_only_serialized_snapshot(self):
        app = FakeAccessible("App", "application")
        dialog = FakeAccessible("Dialog", "dialog", app)
        focused = FakeAccessible("Focused", "push button", dialog)
        omitted = FakeAccessible("Omitted", "push button", dialog)
        registry = {"stale": object()}

        payload = build_focus_payload(
            "object:state-changed:focused",
            1,
            focused,
            max_objects=3,
            object_registry=registry,
        )
        ids = {item["id"] for item in payload["objects"]}
        self.assertEqual(set(registry), ids)
        self.assertIs(registry[object_id(focused)], focused)
        self.assertNotIn(object_id(omitted), registry)
        self.assertNotIn("stale", registry)

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


class TreeNode:
    def __init__(self, name, *states, children=(), role="push button"):
        self.name = name
        self.role = role
        self._states = states
        self.kids = list(children)

    def get_name(self):
        return self.name

    def get_role_name(self):
        return self.role

    def get_state_set(self):
        return FakeStateSet(*self._states)

    def get_child_count(self):
        return len(self.kids)

    def get_child_at_index(self, index):
        return self.kids[index]


class FindFocusedObjectTests(unittest.TestCase):
    def test_finds_focused_descendant_of_active_window(self):
        button = TreeNode("Save", "focused")
        window = TreeNode("Main", "active", children=[TreeNode("panel", children=[button])], role="frame")
        desktop = TreeNode("desktop", children=[TreeNode("app", children=[window], role="application")])
        self.assertIs(find_focused_object(desktop), button)

    def test_active_window_is_searched_before_background_windows(self):
        background = TreeNode("old", "focused")
        active = TreeNode("current", "active", children=[TreeNode("Name", "focused")])
        desktop = TreeNode(
            "desktop",
            children=[TreeNode("app", children=[TreeNode("bg", children=[background]), active])],
        )
        self.assertEqual(find_focused_object(desktop).get_name(), "Name")

    def test_returns_none_when_nothing_is_focused(self):
        desktop = TreeNode("desktop", children=[TreeNode("app", children=[TreeNode("w", "active")])])
        self.assertIsNone(find_focused_object(desktop))

    def test_empty_desktop_returns_none(self):
        self.assertIsNone(find_focused_object(TreeNode("desktop")))

    def test_search_is_bounded_by_node_budget(self):
        leaves = [TreeNode(f"n{i}") for i in range(50)]
        leaves.append(TreeNode("late", "focused"))
        desktop = TreeNode("desktop", children=[TreeNode("app", children=[TreeNode("w", "active", children=leaves)])])
        self.assertIsNone(find_focused_object(desktop, max_nodes=10))
        self.assertEqual(find_focused_object(desktop).get_name(), "late")

    def test_broken_nodes_are_skipped(self):
        class Broken(TreeNode):
            def get_child_count(self):
                raise RuntimeError("dead proxy")

        good = TreeNode("Save", "focused")
        desktop = TreeNode(
            "desktop",
            children=[TreeNode("app", children=[Broken("gone", "active"), TreeNode("w", "active", children=[good])])],
        )
        self.assertIs(find_focused_object(desktop), good)

    def test_discovered_focus_builds_a_payload_with_text_state(self):
        class Edit(TreeNode):
            def get_text_iface(self):
                return FakeText("hello", caret=2)

        edit = Edit("Name", "focused", role="text")
        window = TreeNode("Main", "active", children=[edit], role="frame")
        desktop = TreeNode("desktop", children=[TreeNode("app", children=[window], role="application")])
        target = find_focused_object(desktop)
        payload = build_focus_payload("object:state-changed:focused", 1, target)
        focused = next(o for o in payload["objects"] if o["id"] == payload["focus_id"])
        self.assertTrue(focused["text_supported"])
        self.assertEqual(focused["text"], "hello")
        self.assertEqual(focused["caret_offset"], 2)
