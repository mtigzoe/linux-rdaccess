from __future__ import annotations

import contextlib
import io
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
            for name in ("linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py", "orca_adapter.py"):
                (source / name).write_text("# test\n", encoding="utf-8")

            linux_rdaccess.install_user_files(source, share_dir=share, bin_path=bin_path)

            self.assertTrue(bin_path.exists())
            self.assertTrue(share.joinpath("remote_access.py").exists())
            self.assertTrue(share.joinpath("orca_adapter.py").exists())
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
