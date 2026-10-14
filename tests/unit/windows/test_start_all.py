"""Safe orchestration policy; no SSH, live NVDA, or desktop sessions."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

import linux_rdaccess_test_session as launcher
from linux_rdaccess_core.connection import test_session as orchestration


def reply(result):
    return {"result": result, "status": {
        "schema_version": 1, "bridge_attached": False,
        "transport_connected": "unverified", "remote_control_active": "unverified",
        "semantic_braille_negotiated": False, "temporary_message_supported": False,
        "physical_braille": "unverified",
    }}


class StartAllTests(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()
        self.factory = mock.Mock(return_value=self.client)
        self.probe = mock.Mock(return_value=({
            "linux_ssh": "reachable",
            "linux_config": {"ready": True, "orca_remote_config_found": True},
        }, 0))

    def test_missing_consent_cannot_probe_or_connect(self):
        self.factory.side_effect = PermissionError("secret exception detail")
        result, code = orchestration.start_all(self.probe, client_factory=self.factory)
        self.assertEqual(code, 2)
        self.probe.assert_not_called()
        self.client.operation.assert_not_called()
        self.assertNotIn("secret", json.dumps(result))

    def test_connects_saved_windows_session_and_never_restarts_linux(self):
        self.client.operation.side_effect = [reply("disconnected"), reply("connecting"), reply("connected")]
        with mock.patch.object(orchestration.time, "sleep"):
            result, code = orchestration.start_all(self.probe, client_factory=self.factory)
        self.assertEqual(code, 0)
        self.probe.assert_called_once_with(start=False)
        self.assertEqual(
            [c.args[0] for c in self.client.operation.call_args_list], ["status", "connect", "status"],
        )
        self.assertTrue(result["windows_remote_connected"])
        self.assertFalse(result["semantic_braille_negotiated"])
        self.assertEqual(result["physical_braille"], "unverified")

    def test_existing_connection_is_reused_without_cleanup(self):
        self.client.operation.return_value = reply("connected")
        result, code = orchestration.start_all(self.probe, client_factory=self.factory)
        self.assertEqual(code, 0)
        self.client.operation.assert_called_once_with("status")
        self.assertEqual(result["cleanup"], "not_needed")

    def test_linux_incomplete_cannot_connect_or_mutate_orca(self):
        self.probe.return_value[0]["linux_config"]["ready"] = False
        result, code = orchestration.start_all(self.probe, client_factory=self.factory)
        self.assertEqual(code, 2)
        self.probe.assert_called_once_with(start=False)
        self.client.operation.assert_not_called()
        self.assertEqual(result["linux_session"], "setup_required")

    def test_failed_busy_unauthorized_and_timeout_attempts_request_owned_cleanup(self):
        for state in ("failed", "busy", "not_authorized", "not_configured", "connecting"):
            with self.subTest(state=state):
                self.client.operation.reset_mock()
                self.client.operation.side_effect = [reply("disconnected"), reply(state), reply("cancelled")]
                result, code = orchestration.start_all(self.probe, client_factory=self.factory, timeout=0)
                self.assertEqual(code, 1)
                self.assertEqual(self.client.operation.call_args_list[-1], mock.call("cancel"))
                self.assertEqual(result["cleanup"], "session_owned_connection_cancelled")

    def test_keyboard_cancellation_and_revoked_cleanup_are_redacted(self):
        self.client.operation.side_effect = [reply("disconnected"), KeyboardInterrupt(),
                                             PermissionError("private credentials")]
        result, code = orchestration.start_all(self.probe, client_factory=self.factory)
        self.assertEqual(code, 130)
        self.assertEqual(result["cleanup"], "authorization_expiry_will_cleanup")
        self.assertNotIn("private", json.dumps(result))

    def test_cli_start_all_and_status_keep_json_only(self):
        with mock.patch.object(orchestration, "start_all", return_value=({"mode": "start-all"}, 0)) as start:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(launcher.main(["start-all"]), 0)
            self.assertEqual(json.loads(output.getvalue()), {"mode": "start-all"})
            start.assert_called_once_with(launcher.probe, path=None)

    def test_client_repr_never_contains_session_secret(self):
        from linux_rdaccess_core.connection.nvda_test_client import AuthorizedClient
        client = object.__new__(AuthorizedClient)
        client._address = "private-address"
        client._key = b"test-key-value"
        self.assertNotIn("test-key-value", repr(client))

    def test_trace_cli_uses_only_the_authorized_read_only_operation(self):
        payload = {"windows_authorization": "active", "braille_trace": {"available": False}}
        with mock.patch.object(orchestration, "windows_operation", return_value=(payload, 0)) as operation:
            with mock.patch.object(launcher, "probe") as probe:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(launcher.main(["nvda-braille-trace"]), 0)
                operation.assert_called_once_with("braille_trace", None)
                probe.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())["mode"], "nvda-braille-trace")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            launcher.main(["nvda-braille-trace", "--confirm-start"])

    def test_older_endpoint_trace_failure_reports_supported_status_without_reconnecting(self):
        client = mock.Mock()
        client.operation.side_effect = [EOFError("PRIVATE DETAILS"), reply("connected")]
        with mock.patch.object(orchestration, "AuthorizedClient", return_value=client):
            result, code = orchestration.windows_operation("braille_trace")
        self.assertEqual(code, 2)
        self.assertEqual(result["windows_authorization"], "active")
        self.assertEqual(result["routing_trace"], "unavailable_or_unsupported")
        self.assertEqual(client.operation.call_args_list, [mock.call("braille_trace"), mock.call("status")])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_outcomes_cli_and_unsupported_endpoint_are_read_only(self):
        with mock.patch.object(orchestration, "windows_operation", return_value=({}, 0)) as operation:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(launcher.main(["nvda-braille-outcomes"]), 0)
            operation.assert_called_once_with("braille_outcomes", None)
        client = mock.Mock()
        client.operation.side_effect = [EOFError("PRIVATE"), reply("connected")]
        with mock.patch.object(orchestration, "AuthorizedClient", return_value=client):
            result, code = orchestration.windows_operation("braille_outcomes")
        self.assertEqual(code, 2)
        self.assertEqual(result["windows_authorization"], "active")
        self.assertEqual(client.operation.call_args_list, [mock.call("braille_outcomes"), mock.call("status")])
        self.assertNotIn("PRIVATE", json.dumps(result))
