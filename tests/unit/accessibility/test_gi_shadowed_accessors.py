"""Regression coverage for libatspi 2.50+ Accessible alias collisions."""
import sys
import types
import unittest
from unittest.mock import patch

from linux_rdaccess_core.accessibility import a11y_model


class ShadowedAccessible:
    def __init__(self):
        self.text = "hello world"
        self.current = 42.0
        self.value_text = ""

    def get_text_iface(self):
        return self

    def get_value_iface(self):
        return self

    def get_character_count(self):
        return len(self.text)

    def get_caret_offset(self):
        return 4

    def get_n_selections(self):
        return 1

    # Accessible aliases shadow Text/Value methods in newer libatspi.
    def get_text(self):
        raise AssertionError("Accessible.get_text alias was used")

    def get_selection(self):
        raise AssertionError("Accessible.get_selection alias was used")

    def get_current_value(self):
        raise AssertionError("Accessible.get_current_value must be bypassed")


class TextInterface:
    @staticmethod
    def get_text(obj, start, end):
        return obj.text[start:end]

    @staticmethod
    def get_selection(obj, index):
        return (2, 5) if index == 0 else None


class ValueInterface:
    @staticmethod
    def get_text(obj):
        return obj.value_text

    @staticmethod
    def get_current_value(obj):
        return obj.current


class ShadowedAccessorTests(unittest.TestCase):
    def setUp(self):
        gi = types.ModuleType("gi")
        repository = types.ModuleType("gi.repository")
        repository.Atspi = types.SimpleNamespace(
            Accessible=ShadowedAccessible, Text=TextInterface, Value=ValueInterface
        )
        gi.repository = repository
        self.modules = patch.dict(sys.modules, {"gi": gi, "gi.repository": repository})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_text_snapshot_uses_text_interface_and_preserves_caret(self):
        result = a11y_model._text_snapshot(ShadowedAccessible(), focused=True)
        self.assertEqual(result["text"], "hello world")
        self.assertEqual(result["caret_offset"], 4)
        self.assertTrue(result["text_supported"])
        self.assertFalse(result["text_truncated"])

    def test_selection_uses_text_interface(self):
        result = a11y_model._text_snapshot(ShadowedAccessible(), focused=True)
        self.assertEqual((result["selection_start"], result["selection_end"]), (2, 5))

    def test_value_uses_value_interface_instead_of_accessible_alias(self):
        self.assertEqual(a11y_model._value(ShadowedAccessible()), "42")

    def test_value_interface_text_takes_precedence(self):
        obj = ShadowedAccessible()
        obj.value_text = "Loud"
        obj.current = 3.0
        self.assertEqual(a11y_model._value(obj), "Loud")

    def test_empty_text_is_not_truncated(self):
        obj = ShadowedAccessible()
        obj.text = ""
        result = a11y_model._text_snapshot(obj, focused=True)
        self.assertEqual(result["text"], "")
        self.assertFalse(result["text_truncated"])

    def test_non_gi_value_object_repr_is_not_reported(self):
        class FakeValue:
            def get_text(self):
                return object()

            def get_current_value(self):
                return 7.0

        class FakeAccessible:
            def get_value_iface(self):
                return FakeValue()

        self.assertEqual(a11y_model._value(FakeAccessible()), "7")



if __name__ == "__main__":
    unittest.main()
