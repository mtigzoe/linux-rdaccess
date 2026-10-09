"""Caret routing must use a provider setter, not an arbitrary Python field."""

import unittest
from unittest import mock

from linux_rdaccess_core.accessibility import a11y_model
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeText


class CaretSetterFailureTests(unittest.TestCase):
    def editor(self, text):
        return FakeAccessible("Editor", "text", text_iface=text)

    def test_failed_provider_setter_cannot_create_a_fake_caret_property(self):
        text = FakeText("alpha bravo", caret=2)
        text.set_caret_offset = mock.Mock(side_effect=RuntimeError("provider unavailable"))
        self.assertFalse(a11y_model.set_caret_offset(self.editor(text), 7))
        text.set_caret_offset.assert_called_once_with(7)
        self.assertEqual(text.get_caret_offset(), 2)
        self.assertFalse(hasattr(text, "caretOffset"))

    def test_text_without_a_setter_cannot_claim_routing_succeeded(self):
        text = FakeText("alpha bravo", caret=2)
        self.assertFalse(a11y_model.set_caret_offset(self.editor(text), 7))
        self.assertFalse(hasattr(text, "caretOffset"))

    def test_legacy_property_setter_remains_supported(self):
        class PropertyText(FakeText):
            @property
            def caretOffset(self):
                return self.caret

            @caretOffset.setter
            def caretOffset(self, offset):
                self.caret = offset

        text = PropertyText("alpha bravo", caret=2)
        self.assertTrue(a11y_model.set_caret_offset(self.editor(text), 7))
        self.assertEqual(text.get_caret_offset(), 7)

    def test_failed_method_is_not_retried_through_a_property(self):
        property_calls = []
        class PropertyText(FakeText):
            @property
            def caretOffset(self):
                return self.caret

            @caretOffset.setter
            def caretOffset(self, offset):
                property_calls.append(offset)
                self.caret = offset

        text = PropertyText("alpha bravo", caret=2)
        text.set_caret_offset = mock.Mock(side_effect=RuntimeError("provider unavailable"))
        self.assertFalse(a11y_model.set_caret_offset(self.editor(text), 7))
        self.assertEqual(text.get_caret_offset(), 2)
        self.assertEqual(property_calls, [])


if __name__ == "__main__":
    unittest.main()
