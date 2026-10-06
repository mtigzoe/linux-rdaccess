"""start-orca-session.sh / start-orca-remote.sh with fake pgrep, orca and /proc (no desktop needed)."""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSION = ROOT / "start-orca-session.sh"
REMOTE = ROOT / "start-orca-remote.sh"

FAKE_PGREP = """#!/bin/sh
echo "$@" >> "$FAKE_PGREP_LOG"
case "$*" in
  *xfce4-session*) [ -n "$FAKE_SESSION_PID" ] && echo "$FAKE_SESSION_PID" ;;
  *orca*) echo "4242 orca" ;;
esac
exit 0
"""
FAKE_ORCA = """#!/bin/sh
env -0 > "$FAKE_ORCA_ENV"
echo "$@" > "$FAKE_ORCA_ARGS"
"""


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class OrcaStartScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("pgrep", FAKE_PGREP), ("orca", FAKE_ORCA)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.proc = self.tmp / "proc"
        (self.proc / "777").mkdir(parents=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.shared_tmp = self.tmp / "shared-tmp"
        self.shared_tmp.mkdir()

    def environ(self, raw: bytes) -> None:
        (self.proc / "777" / "environ").write_bytes(raw)

    def run_script(self, script, unset=(), **extra):
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "TMPDIR": str(self.shared_tmp),
            "USER": "someone",
            "LINUX_RDACCESS_PROC_ROOT": str(self.proc),
            "LINUX_RDACCESS_ORCA_WAIT": "0.3",
            "FAKE_SESSION_PID": "777",
            "FAKE_PGREP_LOG": str(self.tmp / "pgrep.log"),
            "FAKE_ORCA_ENV": str(self.tmp / "orca.env"),
            "FAKE_ORCA_ARGS": str(self.tmp / "orca.args"),
        }
        env.update(extra)
        for key in unset:
            env.pop(key, None)
        return subprocess.run(["bash", str(script)], env=env, capture_output=True,
                              text=True, timeout=20)

    def orca_env(self):
        import time
        for _ in range(50):
            if (self.tmp / "orca.env").exists() and (self.tmp / "orca.args").exists():
                break
            time.sleep(0.1)
        raw = (self.tmp / "orca.env").read_bytes().decode(errors="replace")
        return dict(item.split("=", 1) for item in raw.split("\0") if "=" in item)

    def test_scripts_are_executable_as_the_readme_runs_them(self):
        for script in (SESSION, REMOTE):
            self.assertTrue(os.access(script, os.X_OK), script.name)

    def test_session_script_only_looks_at_the_current_users_session(self):
        self.environ(b"DISPLAY=:10\0DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1/bus\0")
        r = self.run_script(SESSION)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        first = (self.tmp / "pgrep.log").read_text().splitlines()[0]
        self.assertIn(f"-u {os.getuid()}", first)
        self.assertEqual(self.orca_env()["DISPLAY"], ":10")

    def test_session_script_does_not_split_environ_on_newlines(self):
        self.environ(b"XAUTHORITY=/x\nDBUS_SESSION_BUS_ADDRESS=forged\0DISPLAY=:10\0")
        r = self.run_script(SESSION)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        seen = self.orca_env()
        self.assertNotEqual(seen.get("DBUS_SESSION_BUS_ADDRESS"), "forged")
        self.assertEqual(seen["DISPLAY"], ":10")

    def test_session_script_keeps_a_final_entry_without_a_terminator(self):
        self.environ(b"XDG_RUNTIME_DIR=/run/user/1\0DISPLAY=:10")
        r = self.run_script(SESSION)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.orca_env()["DISPLAY"], ":10")

    def test_session_script_reports_an_unreadable_environment(self):
        r = self.run_script(SESSION, FAKE_SESSION_PID="888")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Cannot read", r.stdout)
        self.assertFalse((self.tmp / "orca.env").exists())

    def test_session_script_log_is_private_and_not_in_shared_tmp(self):
        self.environ(b"DISPLAY=:10\0")
        r = self.run_script(SESSION)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(list(self.shared_tmp.iterdir()), [])
        log_dir = self.home / ".local/state/linux-rdaccess"
        self.assertTrue((log_dir / "orca.log").exists())
        self.assertEqual(stat.S_IMODE(log_dir.stat().st_mode), 0o700)

    def test_remote_script_works_when_user_is_unset(self):
        self.environ(b"DISPLAY=:10\0")
        r = self.run_script(REMOTE, unset=("USER",))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.orca_env()["DISPLAY"], ":10")
        self.assertIn(f"-u {os.getuid()}", (self.tmp / "pgrep.log").read_text())

    def test_remote_script_requires_a_display(self):
        self.environ(b"XDG_RUNTIME_DIR=/run/user/1\0")
        r = self.run_script(REMOTE, unset=("DISPLAY", "WAYLAND_DISPLAY"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("No graphical display", r.stderr)


if __name__ == "__main__":
    unittest.main()
