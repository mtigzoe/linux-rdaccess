#!/usr/bin/env python3
"""Run one simulated GTK caret route in a private Xvfb/D-Bus desktop.

Suitable for SSH: requires no existing application focus, NVDA test-session
authorization, physical keys or changes to the active desktop.
"""

from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.diagnostics.real_gui_atspi_smoke import isolated_environment


def main():
    if sys.platform != "linux":
        print("Routing simulation requires Linux with GTK3, AT-SPI, Xvfb and xfwm4.")
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix="lrd-routing-simulation-") as private:
            # The test verifies Xvfb and D-Bus ownership before opening its fixture.
            result = subprocess.run(
                ["xvfb-run", "-a", "-s", "-screen 0 1280x900x24",
                 "dbus-run-session", "--", sys.executable, "-B", "-m", "unittest", "-v",
                 "tests.integration.x11.test_routing_simulator"],
                cwd=ROOT, env=isolated_environment(Path(private)), timeout=60,
            )
            return result.returncode
    except (OSError, subprocess.TimeoutExpired):
        print("Isolated routing simulation unavailable or exceeded 60 seconds.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
