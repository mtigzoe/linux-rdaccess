from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import linux_rdaccess
from remote_access import RemoteAccessConfig, save_config


class InstallTests(unittest.TestCase):
    def test_install_creates_wrapper_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            share = root / "share"
            bin_path = root / "bin" / "linux-rdaccess"
            source.mkdir()
            for name in ("linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py"):
                (source / name).write_text("# test\n", encoding="utf-8")

            linux_rdaccess.install_user_files(source, share_dir=share, bin_path=bin_path)

            self.assertTrue(bin_path.exists())
            self.assertTrue(share.joinpath("remote_access.py").exists())
            self.assertIn("linux_rdaccess.py", bin_path.read_text(encoding="utf-8"))

    def test_autostart_executes_connect_quietly(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "linux-rdaccess.desktop"
            bin_path = Path(temp) / "bin" / "linux-rdaccess"
            linux_rdaccess.write_autostart(autostart_path=path, bin_path=bin_path)
            content = path.read_text(encoding="utf-8")
            self.assertIn(f"Exec={bin_path} connect --quiet", content)
            self.assertIn("Terminal=false", content)


class ConnectionTests(unittest.TestCase):
    def test_connect_applies_saved_config_without_printing_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "remote.json"
            orca_path = root / "orca-customizations.py"
            secret = "secret-channel"
            save_config(RemoteAccessConfig(key=secret), config_path)
            orca_path.write_text(
                'YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"\n'
                'YOUR_NVDAREMOTE_SERVER_PORT = 6837\n'
                'YOUR_NVDAREMOTE_KEY = "key"\n'
                'connection_type="slave"\n',
                encoding="utf-8",
            )

            result = linux_rdaccess.connect(
                config_path=config_path,
                orca_config=orca_path,
                restart=False,
                quiet=True,
            )

            self.assertEqual(result, 0)
            text = orca_path.read_text(encoding="utf-8")
            self.assertIn("nvdaremote.com", text)
            self.assertIn(secret, text)

    def test_disconnect_preserves_saved_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "remote.json"
            orca_path = root / "orca-customizations.py"
            save_config(RemoteAccessConfig(key="saved-key"), config_path)
            orca_path.write_text(
                'YOUR_NVDAREMOTE_SERVER_ADDRESS = "nvdaremote.com"\n'
                'YOUR_NVDAREMOTE_SERVER_PORT = 6837\n'
                'YOUR_NVDAREMOTE_KEY = "live-key"\n'
                'connection_type="slave"\n',
                encoding="utf-8",
            )

            result = linux_rdaccess.disconnect(
                orca_config=orca_path,
                restart=False,
                quiet=True,
            )

            self.assertEqual(result, 0)
            self.assertEqual(json.loads(config_path.read_text())["key"], "saved-key")
            live = orca_path.read_text(encoding="utf-8")
            self.assertIn('YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"', live)
            self.assertIn('YOUR_NVDAREMOTE_KEY = "key"', live)


class RestartTests(unittest.TestCase):
    def test_graphical_session_env_finds_xfce_session(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            p = proc / "1251"
            p.mkdir()
            (p / "comm").write_text("xfce4-session\n", encoding="utf-8")
            (p / "status").write_text("Name:\txfce4-session\nUid:\t1000\t1000\t1000\t1000\n", encoding="utf-8")
            (p / "environ").write_bytes(
                b"DISPLAY=:0\0"
                b"XAUTHORITY=/home/miriam/.Xauthority\0"
                b"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus\0"
                b"XDG_RUNTIME_DIR=/run/user/1000\0"
                b"XDG_SESSION_TYPE=x11\0"
            )

            env = linux_rdaccess.graphical_session_env(
                proc_root=proc,
                base_env={"PATH": "/usr/bin"},
                uid=1000,
            )

            self.assertEqual(env["DISPLAY"], ":0")
            self.assertEqual(env["XAUTHORITY"], "/home/miriam/.Xauthority")
            self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus")

    @mock.patch("linux_rdaccess.graphical_session_env")
    @mock.patch("linux_rdaccess.subprocess.run")
    def test_restart_orca_uses_replace_and_graphical_env(self, run, graphical_env):
        graphical_env.return_value = {"DISPLAY": ":0"}
        run.return_value.returncode = 0
        self.assertEqual(linux_rdaccess.restart_orca(), 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["orca", "--replace"])
        self.assertEqual(run.call_args.kwargs["env"], {"DISPLAY": ":0"})


if __name__ == "__main__":
    unittest.main()


class ConfigureForwardingTests(unittest.TestCase):
    @mock.patch("linux_rdaccess.subprocess.call")
    def test_configure_forwards_role_option(self, call):
        call.return_value = 0

        result = linux_rdaccess.main(["configure", "--role", "host"])

        self.assertEqual(result, 0)
        argv = call.call_args.args[0]
        self.assertEqual(argv[-3:], ["configure", "--role", "host"])

    @mock.patch("linux_rdaccess.subprocess.call")
    def test_configure_forwards_generate_key_option(self, call):
        call.return_value = 0

        result = linux_rdaccess.main(["configure", "--generate-key"])

        self.assertEqual(result, 0)
        argv = call.call_args.args[0]
        self.assertEqual(argv[-2:], ["configure", "--generate-key"])

    def test_unknown_option_for_other_command_is_rejected(self):
        with self.assertRaises(SystemExit):
            linux_rdaccess.main(["status", "--role", "host"])
