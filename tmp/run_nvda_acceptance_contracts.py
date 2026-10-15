from pathlib import Path
import json
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent
MODULES = [
    "tests.unit.braille.test_nvda_native_braille",
    "tests.unit.braille.test_braille_cell_alignment",
    "tests.unit.braille.test_braille_routing_speech",
    "tests.unit.braille.test_braille_input_help",
    "tests.unit.braille.test_temporary_braille_messages",
    "tests.integration.test_nvda_remote_loopback",
]

if "--inner" not in sys.argv:
    env = os.environ.copy()
    for name in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS", "WAYLAND_DISPLAY", "NO_AT_BRIDGE"):
        env.pop(name, None)
    for key, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
        target = ROOT / directory
        target.mkdir(mode=0o700, exist_ok=True)
        env[key] = str(target)
    env["GSETTINGS_BACKEND"] = "memory"
    with (ROOT / "bridge-loopback-isolated.log").open("w") as log:
        completed = subprocess.run(["xvfb-run", "-a", "dbus-run-session", "--", sys.executable, "-B", str(Path(__file__).resolve()), "--inner"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    print("exit_code", completed.returncode)
    print((ROOT / "bridge-loopback-isolated-summary.json").read_text() if (ROOT / "bridge-loopback-isolated-summary.json").exists() else "no summary")
    raise SystemExit(completed.returncode)

# Existing fixtures patch sys.modules: load the real GI dependency graph first
# so removing test mocks cannot import a registered enum a second time.
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib, GObject, Gio

loader = unittest.TestLoader()
suite = loader.loadTestsFromNames(MODULES)
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = {
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skipped": len(result.skipped),
    "status": "PASS" if result.wasSuccessful() and not result.skipped else "FAIL",
    "scope": "Private Xvfb/D-Bus mocked bridge and real socket loopback; no real NVDA or braille device",
    "modules": MODULES,
}
(ROOT / "bridge-loopback-isolated-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
