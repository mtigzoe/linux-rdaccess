"""run_braille_bridge.sh: AT-SPI address handling, tested with fake gdbus/xprop (no X or D-Bus needed)."""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "run_braille_bridge.sh"
LIVE = "unix:path=/run/user/1000/at-spi/bus_0,guid=LIVELIVELIVE"
STALE = "unix:path=/run/user/1000/at-spi/bus_0,guid=STALESTALE"

FAKE_GDBUS = """#!/bin/sh
[ -n "$FAKE_GDBUS_FAIL" ] && exit 1
echo "('$FAKE_LIVE_ADDRESS',)"
"""
# Stores/returns the AT_SPI_BUS "root property" in a file, like xprop -root does on a real display.
FAKE_XPROP = """#!/bin/sh
store="$FAKE_ROOT_PROP"
if [ "$1" = "-root" ] && [ "$2" = "-f" ]; then
  [ -n "$FAKE_XPROP_DROP_WRITES" ] && exit 0
  printf '%s' "$7" > "$store"; exit 0
fi
if [ "$1" = "-root" ] && [ "$2" = "AT_SPI_BUS" ]; then
  [ -s "$store" ] && printf 'AT_SPI_BUS(STRING) = "%s"\\n' "$(cat "$store")"
  exit 0
fi
if [ "$1" = "-root" ] && [ "$2" = "_NET_SUPPORTING_WM_CHECK" ]; then
  [ -n "$FAKE_NO_WM" ] && exit 1
  printf '_NET_SUPPORTING_WM_CHECK(WINDOW): window id # 0x200001\n'
  exit 0
fi
exit 1
"""


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, body in (("gdbus", FAKE_GDBUS), ("xprop", FAKE_XPROP)):
            path = self.tmp / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.prop = self.tmp / "root_prop"

    def run_launcher(self, *args, **env_overrides):
        env = {
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "DISPLAY": ":10",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/session-bus",
            "FAKE_LIVE_ADDRESS": LIVE,
            "FAKE_ROOT_PROP": str(self.prop),
        }
        env.update({k: v for k, v in env_overrides.items() if v is not None})
        for key in [k for k, v in env_overrides.items() if v is None]:
            env.pop(key, None)
        return subprocess.run(
            ["bash", str(SCRIPT), "--check", *args], env=env, capture_output=True, text=True, timeout=20
        )

    def test_live_address_is_used_and_published_on_the_root_window(self):
        r = self.run_launcher()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.prop.read_text(), LIVE)
        self.assertIn(f"AT_SPI_BUS_ADDRESS={LIVE}", r.stdout)

    def test_stale_inherited_address_is_replaced_by_the_live_one(self):
        """Regression: an inherited AT_SPI_BUS_ADDRESS won over the live bus. libatspi then aborted
        the bridge (dbind-ERROR / SIGTRAP) and the stale value was published for new applications."""
        r = self.run_launcher(AT_SPI_BUS_ADDRESS=STALE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.prop.read_text(), LIVE)
        self.assertIn("stale AT_SPI_BUS_ADDRESS", r.stderr)

    def test_matching_inherited_address_is_silent(self):
        r = self.run_launcher(AT_SPI_BUS_ADDRESS=LIVE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("stale", r.stderr)

    def test_environment_address_is_only_a_fallback_when_the_bus_cannot_be_queried(self):
        r = self.run_launcher(AT_SPI_BUS_ADDRESS=STALE, FAKE_GDBUS_FAIL="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.prop.read_text(), STALE)
        self.assertIn("could not query org.a11y.Bus", r.stderr)

    def test_no_address_anywhere_is_a_clear_error(self):
        r = self.run_launcher(FAKE_GDBUS_FAIL="1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("cannot find the AT-SPI bus", r.stderr)

    def test_root_property_that_did_not_stick_is_detected(self):
        r = self.run_launcher(FAKE_XPROP_DROP_WRITES="1")
        self.assertEqual(r.returncode, 4)
        self.assertIn("X root window", r.stderr)

    def test_missing_display_is_rejected(self):
        r = self.run_launcher(DISPLAY=None)
        self.assertEqual(r.returncode, 2)
        self.assertIn("DISPLAY is not set", r.stderr)

    def test_bridge_process_receives_the_live_address(self):
        """End to end through the exec: the bridge must see the live address, whatever was inherited."""
        (self.tmp / "atspi_nvda_braille_bridge.py").write_text(
            "import os\nprint('BRIDGE_SAW', os.environ.get('AT_SPI_BUS_ADDRESS'))\n"
        )
        env = {
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "DISPLAY": ":10",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/session-bus",
            "FAKE_LIVE_ADDRESS": LIVE,
            "FAKE_ROOT_PROP": str(self.prop),
            "AT_SPI_BUS_ADDRESS": STALE,
        }
        # Reproduce the installed source layout: legacy root wrapper, relocated
        # implementation and Python bridge in the repository root.
        script = self.tmp / "run_braille_bridge.sh"
        implementation = self.tmp / "scripts" / "linux" / "run_braille_bridge.sh"
        implementation.parent.mkdir(parents=True)
        shutil.copy(SCRIPT, script)
        shutil.copy(ROOT / "scripts" / "linux" / "run_braille_bridge.sh", implementation)
        r = subprocess.run(
            ["bash", str(script)], env=env, cwd=self.tmp, capture_output=True, text=True, timeout=20
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"BRIDGE_SAW {LIVE}", r.stdout)
        self.assertEqual(self.prop.read_text(), LIVE)

    def test_check_mode_reports_the_display_and_session_bus(self):
        r = self.run_launcher()
        self.assertIn("DISPLAY=:10", r.stdout)
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/session-bus", r.stdout)
        self.assertIn("WINDOW_MANAGER=present", r.stdout)

    def test_missing_window_manager_is_a_clear_error(self):
        """Regression: xrdp can accept Tab at X while PointerRoot owns focus, producing no AT-SPI event."""
        r = self.run_launcher(FAKE_NO_WM="1")
        self.assertEqual(r.returncode, 5)
        self.assertIn("no X11 window manager", r.stderr)
        self.assertIn("PointerRoot", r.stderr)


    def test_bridge_is_found_next_to_the_script_from_any_working_directory(self):
        """Regression: the script exec'd a relative path, so it only worked from the repo directory."""
        fake_python = self.tmp / "python3"
        fake_python.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "-c" ]; then exec "$REAL_PYTHON" "$@"; fi\n'
            'echo "$1" > "$FAKE_PY_ARGV"\n'
        )
        fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)
        argv = self.tmp / "argv"
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        env = {
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "DISPLAY": ":10",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/session-bus",
            "FAKE_LIVE_ADDRESS": LIVE,
            "FAKE_ROOT_PROP": str(self.prop),
            "REAL_PYTHON": __import__("sys").executable,
            "FAKE_PY_ARGV": str(argv),
        }
        r = subprocess.run(
            ["bash", str(SCRIPT)], env=env, cwd=elsewhere, capture_output=True, text=True, timeout=20
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(argv.read_text().strip(), str(ROOT / "atspi_nvda_braille_bridge.py"))


if __name__ == "__main__":
    unittest.main()
