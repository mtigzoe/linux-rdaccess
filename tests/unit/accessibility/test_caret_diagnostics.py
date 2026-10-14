"""Reason codes observe existing semantic caret results without retrying input."""

import sys
import types
import unittest
from unittest import mock

import a11y_model
import orca_adapter
from linux_rdaccess_core.caret_diagnostics import CaretReason as Reason
from tests.unit.accessibility.test_a11y_model import FakeAccessible, FakeText


class CaretDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.text = FakeText("public fixture", caret=2)
        self.text.set_caret_offset = mock.Mock(return_value=True)
        self.obj = FakeAccessible("public", "text", text_iface=self.text)
        self.state = types.SimpleNamespace(
            locusOfFocus=self.obj, activeScript=object(), activeWindow=object()
        )
        orca = types.ModuleType("orca")
        orca.orca_state = self.state
        patch = mock.patch.dict(sys.modules, {"orca": orca})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(orca_adapter.OrcaRuntimeAdapter.clear_semantic_focus)
        self.publish()

    def publish(self):
        payload = orca_adapter.OrcaRuntimeAdapter.semantic_focus_payload()
        self.focus_id = payload["focus_id"]
        self.context = orca_adapter.OrcaRuntimeAdapter.semantic_focus_context()

    def request(self, *, identity=None, context=None, offset=7, before=None):
        reasons = []
        result = orca_adapter.OrcaRuntimeAdapter.set_semantic_caret(
            self.focus_id if identity is None else identity,
            offset,
            expected_context=self.context if context is None else context,
            before_route=before,
            diagnostic=reasons.append,
        )
        return result, reasons

    def test_valid_setter_return_does_not_claim_applied_offset(self):
        before = mock.Mock()
        result, reasons = self.request(before=before)
        self.assertTrue(result)
        self.assertEqual(reasons, [Reason.SETTER_RETURNED])
        self.text.set_caret_offset.assert_called_once_with(7)
        before.assert_called_once_with()
        self.assertEqual(
            self.text.caret, 2, "A provider return alone proves no readback"
        )

    def test_stale_context_unknown_object_and_changed_focus_are_distinguished(self):
        result, reasons = self.request(context=object())
        self.assertFalse(result)
        self.assertEqual(reasons, [Reason.STALE_CONTEXT])
        result, reasons = self.request(identity="unknown")
        self.assertFalse(result)
        self.assertEqual(reasons, [Reason.UNKNOWN_OBJECT])
        self.state.locusOfFocus = object()
        result, reasons = self.request()
        self.assertFalse(result)
        self.assertEqual(reasons, [Reason.STALE_FOCUS])
        self.text.set_caret_offset.assert_not_called()

    def test_invalid_payload_bounds_and_unavailable_interfaces(self):
        for offset, expected in (
            (True, Reason.INVALID_OFFSET),
            (-1, Reason.INVALID_OFFSET),
            (8193, Reason.INVALID_OFFSET),
            (99, Reason.OFFSET_OUT_OF_RANGE),
        ):
            with self.subTest(offset=offset):
                result, reasons = self.request(offset=offset)
                self.assertFalse(result)
                self.assertEqual(reasons, [expected])
        self.text.set_caret_offset = None
        self.assertEqual(self.request()[1], [Reason.SETTER_UNAVAILABLE])
        self.obj.text_iface = None
        self.assertEqual(self.request()[1], [Reason.TEXT_INTERFACE_UNAVAILABLE])

    def test_provider_refusal_exception_and_stop_callback_failure_do_not_retry(self):
        for failure, expected in (
            (False, Reason.PROVIDER_REFUSED),
            (RuntimeError("PRIVATE"), Reason.PROVIDER_ERROR),
        ):
            self.text.set_caret_offset.reset_mock()
            self.text.set_caret_offset.side_effect = (
                failure if isinstance(failure, Exception) else None
            )
            self.text.set_caret_offset.return_value = failure
            result, reasons = self.request()
            self.assertFalse(result)
            self.assertEqual(reasons, [expected])
            self.text.set_caret_offset.assert_called_once_with(7)
            self.assertNotIn("PRIVATE", str(reasons))
        self.text.set_caret_offset.reset_mock()
        before = mock.Mock(side_effect=RuntimeError("PRIVATE"))
        self.assertEqual(self.request(before=before)[1], [Reason.BEFORE_ROUTE_ERROR])
        self.text.set_caret_offset.assert_not_called()

    def test_broken_optional_diagnostic_preserves_result_and_call_counts(self):
        for diagnostic in (None, mock.Mock(side_effect=RuntimeError("PRIVATE"))):
            self.text.set_caret_offset.reset_mock()
            self.assertTrue(
                a11y_model.set_caret_offset(self.obj, 7, diagnostic=diagnostic)
            )
            self.text.set_caret_offset.assert_called_once_with(7)

    def test_character_count_and_missing_context_do_not_touch_provider(self):
        self.text.get_character_count = lambda: "unavailable"
        self.assertEqual(self.request()[1], [Reason.CHARACTER_COUNT_UNAVAILABLE])
        orca_adapter.OrcaRuntimeAdapter.clear_semantic_focus()
        self.assertEqual(self.request()[1], [Reason.NO_CONTEXT])
        self.text.set_caret_offset.assert_not_called()

    def test_missing_optional_reason_module_preserves_caret_operation(self):
        with mock.patch.dict(
            sys.modules,
            {
                "linux_rdaccess_core.caret_diagnostics": None,
                "linux_rdaccess_caret_diagnostics": None,
            },
        ):
            result, reasons = self.request()
        self.assertTrue(result)
        self.assertEqual(reasons, [])
        self.text.set_caret_offset.assert_called_once_with(7)
