"""Tests for safe, machine-readable Windows session readiness."""
import contextlib
import io
import json
import unittest
from unittest import mock

import linux_rdaccess_test_session as session


class SessionLauncherTests(unittest.TestCase):
    def test_simulated_message_route_is_a_distinct_action(self):
        from linux_rdaccess_core.connection import test_session as orchestration
        with mock.patch.object(orchestration, "windows_operation", return_value=({}, 0)) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(session.main(["nvda-route-message"]), 0)
        run.assert_called_once_with("braille_message_route", None)

    def test_ambiguous_route_failure_is_not_retried_or_reported_as_no_input(self):
        from linux_rdaccess_core.connection import test_session as orchestration
        client = mock.Mock()
        client.operation.side_effect = TimeoutError("PRIVATE")
        with mock.patch.object(orchestration, "AuthorizedClient", return_value=client):
            result, code = orchestration.windows_operation("braille_message_route")
        self.assertEqual(code, 2)
        self.assertEqual(result["message_route"]["outcome"], "unknown")
        client.operation.assert_called_once_with("braille_message_route")
        self.assertNotIn("PRIVATE", str(result))

    def test_parse_only_allowlisted_boolean_status(self):
        output = ("host: relay.example\nkey_configured: True\nready: False\n"
                  "command_installed: True\npassword: sensitive\n")
        flags = session._flags(output)
        self.assertEqual(flags["key_configured"], True)
        self.assertEqual(flags["ready"], False)
        self.assertIsNone(flags["autostart_enabled"])
        self.assertNotIn("password", flags)
        self.assertNotIn("host", flags)

    def test_status_requires_saved_configuration(self):
        with mock.patch.object(session.controller, "load_config", side_effect=ValueError("missing")):
            data, status = session.probe()
        self.assertEqual(status, 2)
        self.assertEqual(data["linux_ssh"], "not_configured")
        self.assertEqual(data["windows_remote_connected"], "unverified")

    def test_status_does_not_start_linux(self):
        with mock.patch.object(session.controller, "load_config", return_value={}):
            with mock.patch.object(session, "_ssh", return_value=(True, "ready: True")) as ssh:
                data, status = session.probe()
        self.assertEqual(status, 0)
        ssh.assert_called_once_with("status")
        self.assertTrue(data["linux_config"]["ready"])
        self.assertFalse(data["started_linux_connection"])
        self.assertEqual(data["semantic_braille_negotiated"], "unverified")

    def test_start_requires_explicit_permission(self):
        with self.assertRaises(SystemExit) as error:
            session.main(["start"])
        self.assertEqual(error.exception.code, 2)

    def test_start_fails_closed_when_connect_fails(self):
        with mock.patch.object(session.controller, "load_config", return_value={}):
            with mock.patch.object(session, "_ssh", return_value=(False, "")) as ssh:
                data, code = session.probe(start=True)
        self.assertEqual(code, 1)
        self.assertFalse(data["started_linux_connection"])
        ssh.assert_called_once_with("connect")

    def test_start_success_checks_status_but_not_nvda(self):
        with mock.patch.object(session.controller, "load_config", return_value={}):
            with mock.patch.object(session, "_ssh", side_effect=[(True, ""), (True, "ready: True")]) as ssh:
                data, code = session.probe(start=True)
        self.assertEqual(code, 0)
        self.assertTrue(data["started_linux_connection"])
        self.assertEqual([c.args[0] for c in ssh.call_args_list], ["connect", "status"])
        self.assertEqual(data["windows_remote_connected"], "unverified")

    def test_ssh_requires_batch_auth_and_verified_hostkey(self):
        with mock.patch.object(session.controller, "load_config", return_value={
            "host": "cyber.local", "username": "tester", "port": 22,
        }):
            with mock.patch.object(session.subprocess, "run") as run:
                run.return_value = mock.Mock(returncode=0, stdout="key_configured: True")
                success, raw = session._ssh("status")
        self.assertTrue(success)
        self.assertEqual(raw, "key_configured: True")
        command = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=yes", command)
        self.assertNotIn("StrictHostKeyChecking=ask", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 35)
        self.assertTrue(run.call_args.kwargs["capture_output"])


    def test_nvda_launch_requires_explicit_consent(self):
        with self.assertRaises(SystemExit) as error:
            session.main(["launch-nvda", "--nvda-path", "C:/NVDA/nvda.exe"])
        self.assertEqual(error.exception.code, 2)

    def test_nvda_launch_rejects_relative_executable(self):
        with mock.patch.object(session.os, "name", "nt"):
            with mock.patch.object(session, "_windows_nvda", return_value="not_running"):
                with mock.patch.object(session, "Path") as path:
                    path.return_value.expanduser.return_value.is_absolute.return_value = False
                    status, _ = session.launch_nvda("nvda.exe")
        self.assertEqual(status, "invalid_path")

    def test_running_nvda_is_never_restarted(self):
        with mock.patch.object(session.os, "name", "nt"):
            with mock.patch.object(session, "_windows_nvda", return_value="running"):
                with mock.patch.object(session.subprocess, "Popen") as popen:
                    status, _ = session.launch_nvda("C:/Program Files/NVDA/nvda.exe")
        self.assertEqual(status, "already_running")
        popen.assert_not_called()

    def test_nvda_launch_does_not_claim_remote_connection(self):
        output = io.StringIO()
        with mock.patch.object(session, "launch_nvda", return_value=("launch_requested", "Started")):
            with contextlib.redirect_stdout(output):
                code = session.main([
                    "launch-nvda", "--confirm-launch",
                    "--nvda-path", "C:/Program Files/NVDA/nvda.exe",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["remote_connected"], "unverified")


    def test_prepare_requires_both_explicit_authorizations(self):
        for argv in (
            ["prepare"],
            ["prepare", "--confirm-start"],
            ["prepare", "--confirm-launch", "--nvda-path", "C:/NVDA/nvda.exe"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                session.main(argv)

    def test_prepare_runs_launch_then_linux_start(self):
        output = io.StringIO()
        with mock.patch.object(session.controller, "load_config", return_value={}):
            with mock.patch.object(session, "launch_nvda", return_value=("already_running", "Preserved")) as launch:
                with mock.patch.object(session, "probe", return_value=({
                    "linux_ssh": "reachable", "windows_remote_connected": "unverified",
                }, 0)) as probe:
                    with contextlib.redirect_stdout(output):
                        code = session.main([
                            "prepare", "--confirm-start", "--confirm-launch",
                            "--nvda-path", "C:/NVDA/nvda.exe",
                        ])
        self.assertEqual(code, 0)
        launch.assert_called_once_with("C:/NVDA/nvda.exe")
        probe.assert_called_once_with(start=True)
        self.assertEqual(json.loads(output.getvalue())["windows_remote_connected"], "unverified")

    def test_prepare_does_not_connect_linux_if_nvda_launch_fails(self):
        with mock.patch.object(session.controller, "load_config", return_value={}):
            with mock.patch.object(session, "launch_nvda", return_value=("not_found", "Missing")):
                with mock.patch.object(session, "probe") as probe:
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = session.main([
                            "prepare", "--confirm-start", "--confirm-launch",
                            "--nvda-path", "C:/Missing/nvda.exe",
                        ])
        self.assertEqual(code, 1)
        probe.assert_not_called()

    def test_prepare_missing_ssh_config_never_launches_nvda(self):
        output = io.StringIO()
        with mock.patch.object(session.controller, "load_config", side_effect=ValueError("missing")):
            with mock.patch.object(session, "launch_nvda") as launch:
                with mock.patch.object(session, "probe") as probe:
                    with contextlib.redirect_stdout(output):
                        code = session.main([
                            "prepare", "--confirm-start", "--confirm-launch",
                            "--nvda-path", "C:/NVDA/nvda.exe",
                        ])
        self.assertEqual(code, 2)
        launch.assert_not_called()
        probe.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["nvda_launch"], "not_attempted")

    def test_json_doctor_does_not_report_live_validation(self):
        with mock.patch.object(session, "probe", return_value=({
            "windows_remote_connected": "unverified",
            "physical_braille": "unverified",
        }, 0)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = session.main(["doctor"])
        self.assertEqual(code, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["physical_braille"], "unverified")
        self.assertIn("limitations", data)


if __name__ == "__main__":
    unittest.main()
