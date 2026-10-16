#!/usr/bin/env python3
"""Opt-in real Orca restart smoke check in disposable Xvfb and D-Bus.

Run only on a dedicated Linux test runner with:
    python3 tests/integration/isolated_orca_restart_smoke.py

This starts a *real* Orca executable while a separately mocked-controller
transport loopback regression runs within the same private display and bus.\nThe first Orca child is forcibly killed and the second must start cleanly.
This verifies real Orca imports the production adapter and executes a patched\nfixture-backed TCP transport reconnect in the real Orca process\nand executes its safe active-script resolver before writing the import marker.\nThe transport is exercised in-process but is not the installed Orca Remote\ncontroller. It does not test NVDA, speech, or physical braille.
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
        # Optional CI-only check using exact upstream modules rather than
        # the fixture-based transport. This is module loading, NOT relay
        # connection or a production customization startup.
        upstream = os.environ.get("LRD_PINNED_ORCA_REMOTE")
        if os.environ.get("LRD_PINNED_RELAY_FILE"):
            env["LRD_PINNED_RELAY_FILE"] = os.environ["LRD_PINNED_RELAY_FILE"]
        if upstream:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        real_import = ""
        if upstream:
            from linux_rdaccess_core.connection.remote_access import (
                _patch_legacy_transport_cleanup,
                patch_legacy_orca_local_machine,
                patch_legacy_orca_remote_controller,
            )
            scripts_source = Path(upstream) / "orca-scripts"
            scripts = profile / "orca-scripts"
            shutil.copytree(scripts_source, scripts)
            patch_legacy_orca_local_machine(scripts / "local_machine.py")
            patch_legacy_orca_remote_controller(scripts / "remote_controller.py")
            transport = scripts / "transport.py"
            transport.write_text(_patch_legacy_transport_cleanup(
                transport.read_text(encoding="utf-8")), encoding="utf-8")
            real_import = (
                "from pathlib import Path\n"
                "sys.path.insert(0, os.environ['LRD_UPSTREAM_SCRIPTS'])\n"
                "from remote_controller import RemoteController\n"
                "from transport import RelayTransport\n"
                "from serializer import JSONSerializer\n"
                "real_transport = RelayTransport(JSONSerializer(),\n"
                "    ('127.0.0.1', 1), channel='isolated-no-connect', connection_type='slave')\n"
                "real_controller = RemoteController(real_transport)\n"
                "assert real_controller.transport is real_transport\n"
                "assert real_controller.local_machine is not None\n"
                "assert real_transport.connected is False\n"
                "sys.path.insert(0, os.environ['LRD_PROJECT_ROOT'])\n"
                "from tests.integration.real_upstream_orca_loopback import exercise\n"
                "exercise(RemoteController, RelayTransport, JSONSerializer)\n"
                "from tests.integration.real_upstream_orca_tls import exercise_tls\n"
                "exercise_tls(RemoteController, RelayTransport, JSONSerializer)\n"
                "Path(os.environ['LRD_STARTUP_STAGE']).write_text('upstream legacy entry point')\n"
                "# Real relay transport lifecycle is covered by separate tests;\n"
                "# legacy customization startup must not depend on relay timing.\n"
            )
            # Execute upstream's actual legacy customization entry point in
            # the disposable Orca process, not merely its imported modules.
            # Its sentinel host/key disable any automatic external connection.
            legacy_source = (Path(upstream) / "orca-customizations.py").read_text(
                encoding="utf-8")
            legacy_path = profile / "lrd-pinned-legacy-startup.py"
            config_line = ('YOUR_ORCA_SCRIPTS_FOLDER = '
                           'os.path.expanduser("~/.local/share/orca/orca-scripts")')
            if legacy_source.count(config_line) != 1:
                raise RuntimeError("Pinned legacy customization path changed")
            legacy_source = legacy_source.replace(
                config_line,
                "YOUR_ORCA_SCRIPTS_FOLDER = os.environ['LRD_UPSTREAM_SCRIPTS']")
            legacy_path.write_text(legacy_source, encoding="utf-8")
            env["LRD_PINNED_LEGACY_STARTUP"] = str(legacy_path)
            legacy_import = (
                "import runpy, faulthandler\n"
                "faulthandler.dump_traceback_later(35, repeat=False)\n"
                "try:\n"
                "    legacy = runpy.run_path(os.environ['LRD_PINNED_LEGACY_STARTUP'])\n"
                "finally:\n"
                "    faulthandler.cancel_dump_traceback_later()\n"
                "Path(os.environ['LRD_STARTUP_STAGE']).write_text('upstream legacy entry point finished')\n"
                "assert isinstance(legacy['controller'], RemoteController)\n"
                "assert legacy['transport'].connected is False\n"
                "assert legacy['_has_config'] is False\n"
                "assert legacy['controller'].transport is legacy['transport']\n"
            )
            # Startup precedes the TLS and loopback exercises; shared module
            # state from those tests must not affect legacy initialization.
            real_import = real_import.replace(
                "from tests.integration.real_upstream_orca_loopback import exercise\\n",
                legacy_import + "from tests.integration.real_upstream_orca_loopback import exercise\\n",
                1)
            env["LRD_UPSTREAM_SCRIPTS"] = str(scripts)
        (profile / "orca-customizations.py").write_text(
            "import os, sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, os.environ['LRD_ORCA_ADAPTER_DIR'])\n"
            "from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter\n"
            "OrcaRuntimeAdapter.active_script()\n"
            + real_import
            + "sys.path.insert(0, os.environ['LRD_PROJECT_ROOT'])\n"
            "from tests.integration.nvda_remote_harness import LoopbackSession\n"
            "with_marker = LoopbackSession()\n"
            "try:\n"
            "    with_marker.start(native_reconnector=True)\n"
            "    with_marker.send(type='channel_joined', channel='test-only')\n"
            "    with_marker.barrier()\n"
            "    with_marker.disconnect_peer()\n"
            "    with_marker.transport.callback_manager.wait_for('transport_disconnected')\n"
            "    with_marker.accept()\n"
            "    with_marker.transport.callback_manager.wait_for('transport_connected', count=2)\n"
            "    with_marker.send(type='channel_joined', channel='test-only')\n"
            "    with_marker.barrier()\n"
            "finally:\n"
            "    with_marker.close()\n"
            "Path(os.environ['LRD_ORCA_LOAD_MARKER']).write_text(\n"
            "    str(os.getpid()) + '|linux_rdaccess_orca_adapter')\n",
            encoding="utf-8",
        )
        env["LRD_ORCA_ADAPTER_DIR"] = str(profile)
        env["LRD_PROJECT_ROOT"] = str(Path(__file__).resolve().parents[2])
        env["LRD_ORCA_LOAD_MARKER"] = str(marker)
        env["LRD_STARTUP_STAGE"] = str(base / "orca-startup-stage")
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
                "        deadline = time.monotonic() + 60\n"
                "        while not marker.exists() and p.poll() is None and time.monotonic() < deadline:\n"
                "            time.sleep(0.1)\n"
                "        if not marker.exists():\n"
                "            if p.poll() is None: p.terminate()\n"
                "            try: _, err = p.communicate(timeout=5)\n"
                "            except subprocess.TimeoutExpired:\n"
                "                p.kill(); _, err = p.communicate(timeout=5)\n"
                "            stage = Path(os.environ['LRD_STARTUP_STAGE'])\n"
                "            detail = stage.read_text() if stage.exists() else 'before real relay integration'\n"
                "            raise RuntimeError(f'Orca customization did not complete cycle {cycle} at {detail}: {err[-3500:]}')\n"
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
                env=env, capture_output=True, text=True, timeout=150,
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
