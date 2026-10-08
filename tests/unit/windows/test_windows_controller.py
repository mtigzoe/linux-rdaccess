"""Unit tests for the Windows-side controller; no SSH server required."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from linux_rdaccess_core.connection import windows_controller as controller


class WindowsControllerTests(unittest.TestCase):
    def test_saved_configuration_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            controller.save_config("linux-pc.local", "linuxuser", 2222, path)
            self.assertEqual(controller.load_config(path), {
                "host": "linux-pc.local", "username": "linuxuser", "port": 2222,
            })
            self.assertNotIn("password", path.read_text())

    def test_reject_unsafe_host_and_user(self):
        for host, user in [("-oProxyCommand=evil", "normal"), ("host name", "normal"),
                           ("host", "-bad"), ("host", "bad@host")]:
            with self.subTest(host=host, user=user):
                with self.assertRaises(ValueError):
                    controller.validate(host, user, 22)

    def test_reject_unsafe_ports(self):
        for port in (0, 65536, -1):
            with self.assertRaises(ValueError):
                controller.validate("host", "user", port)

    def test_reject_boolean_port_in_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"ssh":{"host":"host","username":"user","port":true}}')
            with self.assertRaises(ValueError):
                controller.load_config(path)

    def test_allowlisted_commands_only(self):
        config = {"host": "linux-pc.local", "username": "linuxuser", "port": 22}
        args = controller.ssh_arguments(config, "status")
        self.assertEqual(args[-2:], ["linuxuser@linux-pc.local", "~/.local/bin/linux-rdaccess status"])
        with self.assertRaises(ValueError):
            controller.ssh_arguments(config, "status; rm -rf ~")

    def test_invokes_ssh_without_shell(self):
        config = {"host": "linux-pc.local", "username": "linuxuser", "port": 22}
        with patch.object(controller, "load_config", return_value=config), patch.object(
            controller.subprocess, "run"
        ) as run:
            run.return_value.returncode = 0
            self.assertEqual(controller.execute("doctor"), 0)
            self.assertEqual(run.call_args.kwargs, {"check": False})
            self.assertEqual(run.call_args.args[0][-1], "~/.local/bin/linux-rdaccess doctor")


if __name__ == "__main__":
    unittest.main()
