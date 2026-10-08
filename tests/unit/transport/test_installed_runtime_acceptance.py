"""Acceptance checks for the installed CLI in an isolated temporary home.

No real Orca configuration is modified and no remote connection is attempted.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import linux_rdaccess
from remote_access import RemoteAccessConfig, save_config
from linux_rdaccess_core.installation.files import RUNTIME_FILES, RUNTIME_PACKAGE_FILES


class InstalledRuntimeAcceptanceTests(unittest.TestCase):
    def test_launcher_quotes_literal_share_directory(self):
        source = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "bin/linux-rdaccess"
            linux_rdaccess.install_user_files(source, share_dir=root / "share 'quoted' $HOME", bin_path=executable)
            result = subprocess.run([str(executable), "--help"], cwd=root,
                                    text=True, capture_output=True, timeout=25,
                                    env=dict(os.environ, HOME=str(root), PYTHONPATH=""))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("usage:", result.stdout)

    def test_real_install_command_and_installed_reinstall_in_private_home(self):
        source = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, HOME=str(root), PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1",
                       XDG_CONFIG_HOME=str(root / ".config"), XDG_DATA_HOME=str(root / ".local/share"))
            installed = root / ".local/share/linux-rdaccess"
            executable = root / ".local/bin/linux-rdaccess"
            for command in ([sys.executable, str(source / "linux_rdaccess.py"), "install"],
                            [str(executable), "install"]):
                result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / ".config/autostart/linux-rdaccess.desktop").is_file())
            self.assertFalse((root / ".config/linux-rdaccess/remote.json").exists())
            for name in RUNTIME_FILES:
                self.assertTrue((installed / name).is_file(), name)
            for name in RUNTIME_PACKAGE_FILES:
                self.assertTrue((installed / "linux_rdaccess_core" / name).is_file(), name)
            configured = subprocess.run(
                [str(executable), "configure", "--role", "host", "--generate-key"],
                cwd=root, env=env, text=True, capture_output=True, timeout=25,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            config = root / ".config/linux-rdaccess/remote.json"
            import json
            secret = json.loads(config.read_text())["key"]
            self.assertTrue(secret)
            self.assertNotIn(secret, configured.stdout + configured.stderr)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_installed_commands_in_isolated_environment(self):
        source = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            share = root / "share"
            executable = root / "bin" / "linux-rdaccess"
            config = root / "missing-remote.json"
            orca = root / "missing-orca.py"
            linux_rdaccess.install_user_files(source, share_dir=share, bin_path=executable)
            env = dict(os.environ, HOME=str(root), PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
            self.assertTrue(executable.is_file())
            self.assertTrue((share / "linux_rdaccess_core" / "installation" / "files.py").is_file())
            self.assertTrue((share / "linux_rdaccess_core" / "connection" / "session.py").is_file())

            def invoke(*args):
                return subprocess.run(
                    [str(executable), "--config", str(config),
                     "--orca-config", str(orca), *args],
                    cwd=root, env=env, text=True, capture_output=True, timeout=25,
                )

            # A missing configuration must produce an unsuccessful readiness
            # result, never start Orca or create a remote-access config.
            status = invoke("status")
            self.assertEqual(status.returncode, 1, status.stdout + status.stderr)
            self.assertIn("ready: False", status.stdout)
            doctor = invoke("doctor")
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            self.assertNotIn("Traceback", doctor.stderr)
            connect = invoke("connect", "--no-restart")
            self.assertEqual(connect.returncode, 1, connect.stdout + connect.stderr)
            self.assertIn("configuration is incomplete", connect.stdout)
            disconnect = invoke("disconnect", "--no-restart")
            self.assertEqual(disconnect.returncode, 1, disconnect.stdout + disconnect.stderr)
            self.assertIn("config not found", disconnect.stdout)
            self.assertFalse(config.exists())
            self.assertFalse(orca.exists())

            # Exercise benign commands and the ready status with a synthetic
            # configuration held entirely under the disposable test directory.
            for command, expected in (
                ("compatibility", "Firefox"),
                ("shortcuts", "Insert+Alt+Tab"),
            ):
                result = invoke(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(expected, result.stdout)
            save_config(
                RemoteAccessConfig(host="example.invalid", port=6837,
                                   role="host", key="synthetic-test-only"),
                config,
            )
            ready = invoke("status")
            self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
            self.assertIn("ready: True", ready.stdout)
            self.assertIn("orca_remote_config_found: False", ready.stdout)
            self.assertNotIn("synthetic-test-only", ready.stdout)
            self.assertFalse(orca.exists())


    def test_installed_connect_disconnect_cycle_without_orca_restart(self):
        source = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "bin" / "linux-rdaccess"
            config = root / "remote.json"
            orca = root / "orca-customizations.py"
            linux_rdaccess.install_user_files(
                source, share_dir=root / "share", bin_path=executable,
            )
            secret = "synthetic-connection-test-only"
            save_config(RemoteAccessConfig(host="example.invalid", port=6837,
                                           role="host", key=secret), config)
            orca.write_text(
                'YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"\n'
                'YOUR_NVDAREMOTE_SERVER_PORT = 6837\n'
                'YOUR_NVDAREMOTE_KEY = "key"\n'
                'connection_type="slave"\n',
                encoding="utf-8",
            )
            env = dict(os.environ, HOME=str(root), PYTHONPATH="",
                       PYTHONDONTWRITEBYTECODE="1")
            def invoke(action):
                return subprocess.run(
                    [str(executable), "--config", str(config),
                     "--orca-config", str(orca), action, "--no-restart"],
                    cwd=root, env=env, text=True, capture_output=True, timeout=25,
                )

            connected = invoke("connect")
            self.assertEqual(connected.returncode, 0, connected.stdout + connected.stderr)
            self.assertNotIn(secret, connected.stdout + connected.stderr)
            self.assertIn(secret, orca.read_text(encoding="utf-8"))
            disconnected = invoke("disconnect")
            self.assertEqual(disconnected.returncode, 0, disconnected.stdout + disconnected.stderr)
            self.assertNotIn(secret, disconnected.stdout + disconnected.stderr)
            self.assertNotIn(secret, orca.read_text(encoding="utf-8"))
            self.assertIn(secret, config.read_text(encoding="utf-8"))
            for file in (config, orca, orca.with_name(orca.name + ".linux-rdaccess-backup")):
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
