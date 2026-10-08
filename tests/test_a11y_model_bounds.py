import unittest

from a11y_model import (
    MAX_CHILDREN,
    build_focus_payload,
    find_focused_object,
    find_focused_object_ex,
)
from tests.test_a11y_model import FakeStateSet


class Node:
    """Fake accessible that counts the D-Bus-like calls made on it."""

    calls = 0

    def __init__(self, name, *states, role="push button", kids=()):
        self.name, self.role, self._states = name, role, states
        self.kids, self.parent, self.index = [], None, 0
        for kid in kids:
            self.add(kid)

    def add(self, kid):
        kid.parent, kid.index = self, len(self.kids)
        self.kids.append(kid)
        return kid

    def get_name(self):
        return self.name

    def get_role_name(self):
        return self.role

    def get_parent(self):
        return self.parent

    def get_index_in_parent(self):
        return self.index

    def get_state_set(self):
        return FakeStateSet(*self._states)

    def get_child_count(self):
        return len(self.kids)

    def get_child_at_index(self, index):
        Node.calls += 1
        return self.kids[index]


def long_list(count, focused_index):
    items = [Node(f"item {i}", *(("focused",) if i == focused_index else ())) for i in range(count)]
    view = Node("files", role="list", kids=items)
    window = Node("Thunar", "active", role="frame", kids=[view])
    app = Node("thunar", role="application", kids=[window])
    return Node("desktop", kids=[app]), items[focused_index], view


class BoundedEnumerationTests(unittest.TestCase):
    def setUp(self):
        Node.calls = 0

    def test_focus_in_a_huge_list_enumerates_a_bounded_window(self):
        _, focused, view = long_list(5000, 2500)
        payload = build_focus_payload("object:state-changed:focused", 1, focused)
        self.assertLessEqual(Node.calls, 2 * MAX_CHILDREN)
        names = {o["name"] for o in payload["objects"]}
        self.assertIn("item 2500", names)
        self.assertIn("item 2499", names)  # neighbours, not the first items of the list
        self.assertIn("item 2501", names)
        self.assertNotIn("item 0", names)

    def test_path_link_survives_the_window(self):
        _, focused, view = long_list(5000, 4999)
        payload = build_focus_payload("object:state-changed:focused", 1, focused)
        by_id = {o["id"]: o for o in payload["objects"]}
        focus = by_id[payload["focus_id"]]
        parent = by_id[focus["parent_id"]]
        self.assertEqual(parent["name"], "files")
        self.assertIn(focus["id"], parent["child_ids"])

    def test_hierarchy_links_are_kept_when_the_object_cap_stops_enumeration(self):
        leaf = Node("leaf", "focused")
        node = leaf
        for depth in range(6):
            node = Node(f"level{depth}", kids=[node, Node(f"sibling{depth}"), Node(f"sibling-b{depth}")])
        payload = build_focus_payload("object:state-changed:focused", 1, leaf, max_objects=8)
        by_id = {o["id"]: o for o in payload["objects"]}
        for obj in payload["objects"]:
            if obj["parent_id"] is not None:
                self.assertIn(obj["id"], by_id[obj["parent_id"]]["child_ids"], obj["name"])

    def test_only_path_members_are_enumerated(self):
        wide = [Node(f"w{i}", kids=[Node(f"c{i}-{j}") for j in range(20)]) for i in range(10)]
        target = Node("target", "focused")
        root = Node("root", kids=[target] + wide)
        build_focus_payload("object:state-changed:focused", 1, target)
        total_children = len(root.kids)  # path members: target (0 kids) and root
        self.assertLessEqual(Node.calls, total_children)  # siblings' own children untouched


class SearchCompletenessTests(unittest.TestCase):
    def test_exhausted_budget_is_not_reported_as_nothing_focused(self):
        desktop, focused, _ = long_list(500, 450)
        found, complete = find_focused_object_ex(desktop, max_nodes=20)
        self.assertIsNone(found)
        self.assertFalse(complete)

    def test_truncated_children_make_the_search_incomplete(self):
        desktop, _, _ = long_list(MAX_CHILDREN + 50, MAX_CHILDREN + 10)
        found, complete = find_focused_object_ex(desktop)
        self.assertIsNone(found)
        self.assertFalse(complete)

    def test_genuinely_nothing_focused_is_complete(self):
        desktop = Node("desktop", kids=[Node("app", kids=[Node("w", "active")])])
        self.assertEqual(find_focused_object_ex(desktop), (None, True))

    def test_found_object_is_complete_and_wrapper_still_returns_it(self):
        desktop, focused, _ = long_list(10, 7)
        self.assertEqual(find_focused_object_ex(desktop), (focused, True))
        self.assertIs(find_focused_object(desktop), focused)


if __name__ == "__main__":
    unittest.main()
