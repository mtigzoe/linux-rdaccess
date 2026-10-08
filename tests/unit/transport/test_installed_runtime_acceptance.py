"""Acceptance checks for the installed CLI in an isolated temporary home.

No real Orca configuration is modified and no remote connection is attempted.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import linux_rdaccess


class InstalledRuntimeAcceptanceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
