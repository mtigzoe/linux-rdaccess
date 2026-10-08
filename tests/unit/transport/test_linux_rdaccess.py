from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
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
            for name in ("linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py", "orca_adapter.py", "a11y_model.py"):
                (source / name).write_text("# test\n", encoding="utf-8")

            connection = source / "linux_rdaccess_core" / "connection"
            connection.mkdir(parents=True)
            (connection / "__init__.py").write_text("", encoding="utf-8")
            (connection / "nvda_remote_check.py").write_text("# installed module\n", encoding="utf-8")
            (source / "linux_rdaccess_core" / "__init__.py").write_text("", encoding="utf-8")

            linux_rdaccess.install_user_files(source, share_dir=share, bin_path=bin_path)

            self.assertTrue(bin_path.exists())
            self.assertTrue(share.joinpath("remote_access.py").exists())
            self.assertTrue(share.joinpath("orca_adapter.py").exists())
            self.assertTrue(share.joinpath("a11y_model.py").exists())
            self.assertTrue((share / "linux_rdaccess_core" / "connection" / "nvda_remote_check.py").is_file())
            self.assertIn("linux_rdaccess.py", bin_path.read_text(encoding="utf-8"))

    def test_install_rejects_missing_package_before_writing_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            share = root / "share"
            bin_path = root / "bin" / "linux-rdaccess"
            source.mkdir()
            for name in ("linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py",
                         "orca_adapter.py", "a11y_model.py"):
                (source / name).write_text("# fixture\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                linux_rdaccess.install_user_files(source, share_dir=share, bin_path=bin_path)
            self.assertFalse(share.exists())
            self.assertFalse(bin_path.exists())

    def test_real_installed_cli_and_connection_probe_start(self):
        # Exercise the installed bundle rather than only validating copied filenames.
        source = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            share = root / "share"
            bin_path = root / "bin" / "linux-rdaccess"
            linux_rdaccess.install_user_files(source, share_dir=share, bin_path=bin_path)
            for command in (
                [str(bin_path), "--help"],
                [sys.executable, str(share / "nvda_remote_check.py"), "--help"],
            ):
                with self.subTest(command=command[-2:]):
                    result = subprocess.run(
                        command, cwd=root, capture_output=True, text=True,
                        timeout=15,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("usage:", result.stdout.lower())

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

    def test_graphical_session_env_replaces_partial_ssh_display_with_desktop_session(self):
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
                base_env={"PATH": "/usr/bin", "DISPLAY": "localhost:10.0"},
                uid=1000,
            )

            self.assertEqual(env["DISPLAY"], ":0")
            self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus")
            self.assertEqual(env["XDG_RUNTIME_DIR"], "/run/user/1000")

    def _fake_session(self, proc, pid, display, start=None, uid=1000, comm="xfce4-session"):
        p = proc / str(pid)
        p.mkdir()
        (p / "comm").write_text(comm + "\n", encoding="utf-8")
        (p / "status").write_text(f"Name:\t{comm}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="utf-8")
        (p / "environ").write_bytes(
            f"DISPLAY={display}\0DBUS_SESSION_BUS_ADDRESS=unix:path=/bus{display}\0"
            f"XDG_RUNTIME_DIR=/run/user/{uid}\0".encode())
        if start is not None:
            fields = ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 10
            (p / "stat").write_text(f"{pid} ({comm} x) " + " ".join(fields) + "\n", encoding="utf-8")

    class _OrderedProc:
        """Lists /proc entries in a fixed order; real directory order is arbitrary."""

        def __init__(self, root, order):
            self._entries = [root / str(pid) for pid in order]

        def iterdir(self):
            return iter(self._entries)

    def test_graphical_session_env_prefers_the_newest_session_of_the_user(self):
        # An xrdp desktop started after a console login must win whatever order
        # /proc lists the processes in, and a lower pid is not necessarily older.
        for order in ((900, 300), (300, 900)):
            with self.subTest(listing_order=order), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self._fake_session(root, 900, ":0", 5000)
                self._fake_session(root, 300, ":10", 90000)      # pid 300 started later
                env = linux_rdaccess.graphical_session_env(
                    proc_root=self._OrderedProc(root, order),
                    base_env={"PATH": "/usr/bin"}, uid=1000)
                self.assertEqual(env["DISPLAY"], ":10")
                self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/bus:10")

    def test_graphical_session_env_falls_back_to_highest_pid_without_stat(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            self._fake_session(proc, 400, ":0")
            self._fake_session(proc, 200, ":5")
            for order in ((400, 200), (200, 400)):
                env = linux_rdaccess.graphical_session_env(
                    proc_root=self._OrderedProc(proc, order),
                    base_env={"PATH": "/usr/bin"}, uid=1000)
                self.assertEqual(env["DISPLAY"], ":0")

    def test_graphical_session_env_ignores_other_users_newer_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            self._fake_session(proc, 100, ":0", 10)
            self._fake_session(proc, 900, ":11", 99999, uid=1001)
            env = linux_rdaccess.graphical_session_env(
                proc_root=proc, base_env={"PATH": "/usr/bin"}, uid=1000)
            self.assertEqual(env["DISPLAY"], ":0")

    def test_graphical_session_env_keeps_complete_desktop_environment(self):
        env = {
            "PATH": "/usr/bin",
            "DISPLAY": ":0",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        }
        self.assertEqual(
            linux_rdaccess.graphical_session_env(
                proc_root=Path("/definitely/not/needed"),
                base_env=env,
                uid=1000,
            ),
            env,
        )

    @mock.patch("linux_rdaccess.graphical_session_env")
    @mock.patch("linux_rdaccess.subprocess.Popen")
    def test_restart_orca_uses_replace_without_waiting(self, popen, graphical_env):
        graphical_env.return_value = {"DISPLAY": ":0"}
        self.assertEqual(linux_rdaccess.restart_orca(), 0)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["orca", "--replace"])
        self.assertEqual(popen.call_args.kwargs["env"], {"DISPLAY": ":0"})
        self.assertTrue(popen.call_args.kwargs["start_new_session"])


class VSCodeSetupTests(unittest.TestCase):
    def test_vscode_setup_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(
                json.dumps({"editor.fontSize": 14, "window.titleBarStyle": "native"}),
                encoding="utf-8",
            )
            linux_rdaccess.configure_vscode_accessibility(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["editor.fontSize"], 14)
            self.assertEqual(data["editor.accessibilitySupport"], "on")
            self.assertEqual(data["window.titleBarStyle"], "native")

    def test_vscode_setup_creates_accessible_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            linux_rdaccess.configure_vscode_accessibility(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["editor.accessibilitySupport"], "on")
            self.assertEqual(data["window.titleBarStyle"], "custom")


class VSCodeJsoncTests(unittest.TestCase):
    def test_comments_and_trailing_commas_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            original = '{\n    // my font\n    "editor.fontSize": 14, /* keep */\n    "files.exclude": {"a": true,},\n}\n'
            path.write_text(original, encoding="utf-8")
            linux_rdaccess.configure_vscode_accessibility(path)
            result = path.read_text(encoding="utf-8")
            self.assertIn("// my font", result)
            self.assertIn("/* keep */", result)
            self.assertIn('"editor.accessibilitySupport": "on"', result)
            self.assertEqual(
                path.with_name(path.name + ".linux-rdaccess-backup").read_text(encoding="utf-8"),
                original,
            )

    def test_existing_value_is_replaced_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text('{"editor.accessibilitySupport": "off"}', encoding="utf-8")
            linux_rdaccess.configure_vscode_accessibility(path)
            result = path.read_text(encoding="utf-8")
            self.assertEqual(result.count("editor.accessibilitySupport"), 1)
            self.assertIn('"on"', result)

    def test_url_with_slashes_in_string_is_not_treated_as_comment(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text('{"http.proxy": "http://x//y"}', encoding="utf-8")
            linux_rdaccess.configure_vscode_accessibility(path)
            self.assertIn("http://x//y", path.read_text(encoding="utf-8"))

    def test_invalid_settings_are_left_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text("{ nope", encoding="utf-8")
            with self.assertRaises(ValueError):
                linux_rdaccess.configure_vscode_accessibility(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "{ nope")


class DoctorTests(unittest.TestCase):
    def _orca(self, controller=None, local=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        (base / "orca-scripts").mkdir()
        cfg = base / "orca-customizations.py"
        cfg.write_text("", encoding="utf-8")
        if controller is not None:
            (base / "orca-scripts" / "remote_controller.py").write_text(controller, encoding="utf-8")
        if local is not None:
            (base / "orca-scripts" / "local_machine.py").write_text(local, encoding="utf-8")
        return cfg

    def test_native_keyboard_hook_status_checks_functional_patch(self):
        import remote_access
        cfg = self._orca()
        label = "native Orca keyboard events (orca-customizations.py)"
        self.assertIn("not patched", dict(linux_rdaccess.patch_status(cfg))[label])
        source = (
            "def _patched_process_key(event_self):\n"
            "    return event_self.is_pressed_key()\n"
        )
        cfg.write_text(remote_access._patch_legacy_customization_event_api(source), encoding="utf-8")
        self.assertEqual(dict(linux_rdaccess.patch_status(cfg))[label], "current")
        cfg.write_text(remote_access.CUSTOMIZATION_EVENT_API_MARKER, encoding="utf-8")
        self.assertIn("incomplete", dict(linux_rdaccess.patch_status(cfg))[label])
        cfg.unlink()
        self.assertEqual(dict(linux_rdaccess.patch_status(cfg))[label], "missing")

    def test_reconnect_status_checks_actual_worker_startup(self):
        import remote_access
        cfg = self._orca()
        label = "automatic relay reconnect (orca-customizations.py)"
        self.assertIn("not patched", dict(linux_rdaccess.patch_status(cfg))[label])
        patched = remote_access._patch_legacy_customization_reconnect(
            remote_access._CUSTOMIZATION_ONESHOT_START)
        cfg.write_text(patched, encoding="utf-8")
        self.assertEqual(dict(linux_rdaccess.patch_status(cfg))[label], "current")
        cfg.write_text(patched.replace("t.start()", "transport.run()"), encoding="utf-8")
        self.assertIn("incomplete", dict(linux_rdaccess.patch_status(cfg))[label])
        cfg.unlink()
        self.assertEqual(dict(linux_rdaccess.patch_status(cfg))[label], "missing")

    def test_speech_status_checks_wire_shape_and_native_callback_helper(self):
        import remote_access
        from tests.unit.transport.test_customization_reconnect import CustomizationReconnectTests
        cfg = self._orca()
        labels = ("NVDA speech sequence (orca-customizations.py)",
                  "native Say All callbacks (orca-customizations.py)")
        source = (CustomizationReconnectTests.CONFIG
                  + remote_access._CUSTOMIZATION_SPEECH_FORWARD_SOURCE)
        cfg.write_text(source, encoding="utf-8")
        remote_access.update_legacy_orca_customizations(
            remote_access.RemoteAccessConfig(key='synthetic'), cfg)
        patched = cfg.read_text()
        self.assertTrue(all(dict(linux_rdaccess.patch_status(cfg))[label] == "current"
                            for label in labels))
        cfg.write_text(patched.replace("return [text] if isinstance(text, str) else text",
                                       "return text"), encoding="utf-8")
        self.assertIn("incomplete", dict(linux_rdaccess.patch_status(cfg))[labels[0]])
        cfg.write_text(patched.replace("server._send_command = muted_send",
                                       "server._send_command = send"), encoding="utf-8")
        self.assertIn("incomplete", dict(linux_rdaccess.patch_status(cfg))[labels[1]])
        cfg.unlink()
        self.assertTrue(all(dict(linux_rdaccess.patch_status(cfg))[label] == "missing"
                            for label in labels))

    def test_reports_current_outdated_unpatched_and_missing(self):
        from remote_access import (LEGACY_COMPAT_MARKER, LOCAL_MACHINE_MARKER_V1)
        cfg = self._orca(controller="x\n" + LEGACY_COMPAT_MARKER, local="x\n" + LOCAL_MACHINE_MARKER_V1 + " v1")
        # A marker-only fake is incomplete, not an installed working patch.
        rows = dict(linux_rdaccess.patch_status(cfg))
        self.assertIn("incomplete", rows["input shim (remote_controller.py)"])
        from tests import test_remote_access as fixtures
        from remote_access import patch_legacy_orca_remote_controller
        controller = cfg.parent / "orca-scripts" / "remote_controller.py"
        controller.write_text(fixtures.LegacyConfigTests.UPSTREAM_CONTROLLER, encoding="utf-8")
        patch_legacy_orca_remote_controller(controller)
        rows = dict(linux_rdaccess.patch_status(cfg))
        self.assertEqual(rows["input shim (remote_controller.py)"], "current")
        self.assertIn("outdated", rows["fast key injection (local_machine.py)"])
        cfg = self._orca(controller="plain upstream")
        rows = dict(linux_rdaccess.patch_status(cfg))
        self.assertIn("not patched", rows["input shim (remote_controller.py)"])
        self.assertEqual(rows["fast key injection (local_machine.py)"], "missing")

    def test_doctor_command_runs_and_never_prints_the_key(self):
        cfg = self._orca(controller="plain", local="plain")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = linux_rdaccess.main(["--orca-config", str(cfg), "doctor"])
        self.assertEqual(code, 0)
        self.assertIn("patch status", out.getvalue())
        self.assertIn("not patched", out.getvalue())


class CompatibilityStatusTests(unittest.TestCase):
    def test_compatibility_status_reports_all_targets(self):
        with mock.patch("linux_rdaccess.shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}" if cmd == "thunar" else None):
            rows = linux_rdaccess.compatibility_status()
        self.assertEqual([row[0] for row in rows], [item[0] for item in linux_rdaccess.COMPATIBILITY_APPS])
        self.assertTrue(rows[0][2])
        self.assertTrue(all(not row[2] for row in rows[1:]))


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
