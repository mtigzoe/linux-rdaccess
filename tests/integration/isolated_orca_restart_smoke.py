#!/usr/bin/env python3
"""Opt-in real Orca restart smoke check in disposable Xvfb and D-Bus.

Run only on a dedicated Linux test runner with:
    python3 tests/integration/isolated_orca_restart_smoke.py

This starts a *real* Orca executable while a separately mocked-controller
transport loopback regression runs within the same private display and bus.\nThe first Orca child is forcibly killed and the second must start cleanly.
This verifies real Orca imports the production adapter from a private copy\nand executes its safe active-script resolver before writing the import marker.\nIt does NOT wire the transport into Orca or test NVDA, speech, or braille.
"""
from __future__ import annotations

import os
import select
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def require(command: str) -> str:
    executable = shutil.which(command)
    if executable is None:
        raise RuntimeError(f"Missing required executable: {command}")
    return executable


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def smoke() -> None:
    # Explicit opt-in only. Never inherit an active DISPLAY or D-Bus address.
    xvfb = require("Xvfb")
    dbus = require("dbus-run-session")
    orca = require("orca")
    with tempfile.TemporaryDirectory(prefix="lrd-orca-smoke-") as root:
        base = Path(root)
        home = base / "home"
        runtime = base / "runtime"
        home.mkdir()
        runtime.mkdir(mode=0o700)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_CACHE_HOME": str(base / "cache"),
            "XDG_DATA_HOME": str(base / "data"),
            "XDG_RUNTIME_DIR": str(runtime),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            # Disallow inherited user session configuration.
            "NO_AT_BRIDGE": "0",
        }
        # A marker written from within Orca's customization import proves the
        # real process loaded the private test customization. It is not proof
        # that the separate Orca Remote transport/controller was loaded.
        profile = base / "data" / "orca"
        profile.mkdir(parents=True)
        marker = base / "orca-customizations-loaded"
        # Import the production adapter from a private copy inside real Orca.
        # No real Orca Remote controller or relay is installed by this smoke.
        adapter_source = (Path(__file__).resolve().parents[2]
                          / "linux_rdaccess_core" / "accessibility" / "orca_adapter.py")
        shutil.copy2(adapter_source, profile / "linux_rdaccess_orca_adapter.py")
        (profile / "orca-customizations.py").write_text(
            "import os, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, os.environ['LRD_ORCA_ADAPTER_DIR'])\n"
            "from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter\n"
            "OrcaRuntimeAdapter.active_script()\n"
            "Path(os.environ['LRD_ORCA_LOAD_MARKER']).write_text(\n"
            "    str(os.getpid()) + '|linux_rdaccess_orca_adapter')\n",
            encoding="utf-8",
        )
        env["LRD_ORCA_ADAPTER_DIR"] = str(profile)
        env["LRD_ORCA_LOAD_MARKER"] = str(marker)
        # Choose a free X display number by binding the X11 socket via -displayfd.
        xserver = subprocess.Popen(
            [xvfb, "-nolisten", "tcp", "-screen", "0", "1024x768x24",
             "-displayfd", "1"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env=env,
        )
        session = None
        try:
            if xserver.stdout is None:
                raise RuntimeError("Xvfb stdout unavailable")
            # -displayfd writes the numeric display ID when the server is ready.
            ready, _, _ = select.select([xserver.stdout], [], [], 10)
            if not ready:
                raise RuntimeError("Xvfb did not become ready")
            display = xserver.stdout.readline().strip()
            if not display.isdigit():
                raise RuntimeError(f"Xvfb did not supply a display number: {display!r}")
            env["DISPLAY"] = f":{display}"
            # Keep one private bus alive, spawn Orca twice within it. The driver
            # sends lifecycle signals only to the children it owns.
            script = (
                "import os, signal, subprocess, sys, time\n"
                "orca = sys.argv[1]\n"
                "from pathlib import Path\n"
                "marker = Path(os.environ['LRD_ORCA_LOAD_MARKER'])\n"
                "for cycle in range(2):\n"
                "    marker.unlink(missing_ok=True)\n"
                "    p = subprocess.Popen([orca, '--no-setup'], "
                "stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)\n"
                "    try:\n"
                "        time.sleep(3)\n"
                "        code = p.poll()\n"
                "        deadline = time.monotonic() + 8\n"
                "        while not marker.exists() and p.poll() is None and time.monotonic() < deadline:\n"
                "            time.sleep(0.1)\n"
                "        if not marker.exists():\n"
                "            raise RuntimeError(f'Orca did not load isolated customization in cycle {cycle}')\n"
                "        if marker.read_text().strip() != str(p.pid) + '|linux_rdaccess_orca_adapter':\n"
                "            raise RuntimeError(f'Unexpected Orca customization loading PID in cycle {cycle}')\n"
                "        if code is not None:\n"
                "            err = p.stderr.read()[-2000:]\n"
                "            raise RuntimeError(f'Orca exited early in cycle {cycle}: {code}: {err}')\n"
                "        check = subprocess.run([sys.executable, '-m', 'unittest', '-v',\n"
                "            'tests.integration.test_nvda_remote_loopback.NvdaRemoteLoopbackTests.'\n"
                "            'test_native_reconnector_two_disconnect_cycles_reject_partial_old_keys'],\n"
                "            capture_output=True, text=True, timeout=35)\n"
                "        if check.returncode:\n"
                "            raise RuntimeError('Transport loopback failed while isolated Orca was running: '\n"
                "                + check.stdout[-2000:] + check.stderr[-3500:])\n"
                "        if p.poll() is not None:\n"
                "            raise RuntimeError(f'Orca exited during transport test in cycle {cycle}')\n"
                "        if cycle == 0:\n"
                "            p.kill()  # Abrupt process death, not graceful shutdown\n"
                "            code = p.wait(timeout=5)\n"
                "            if code != -signal.SIGKILL:\n"
                "                raise RuntimeError(f'Expected SIGKILL in first cycle, got {code}')\n"
                "    finally:\n"
                "        if p.poll() is None:\n"
                "            p.terminate()\n"
                "            try: p.wait(timeout=8)\n"
                "            except subprocess.TimeoutExpired:\n"
                "                p.kill(); p.wait(timeout=5)\n"
                "        p.stderr.close()\n"
                "print('Isolated Orca crash/restart and transport loopback checks completed')\n"
            )
            session = subprocess.run(
                [dbus, "--", sys.executable, "-c", script, orca],
                env=env, capture_output=True, text=True, timeout=110,
                check=False,
            )
            if session.returncode:
                raise RuntimeError(
                    "Isolated Orca smoke failed: " + session.stderr[-2500:])
            print(session.stdout.strip())
        finally:
            stop(xserver)
            if xserver.stdout:
                xserver.stdout.close()


if __name__ == "__main__":
    try:
        smoke()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
