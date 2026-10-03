from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import remote_access


class RemoteAccessConfigTests(unittest.TestCase):
    def test_defaults_use_public_nvda_remote_relay(self):
        config = remote_access.RemoteAccessConfig()
        self.assertEqual(config.host, "nvdaremote.com")
        self.assertEqual(config.port, 6837)
        self.assertEqual(config.role, "host")
        self.assertEqual(config.orca_connection_type, "slave")
        self.assertFalse(config.ready)

    def test_client_maps_to_master(self):
        config = remote_access.RemoteAccessConfig(role="client")
        self.assertEqual(config.orca_connection_type, "master")

    def test_generated_keys_are_nonempty_and_distinct(self):
        first = remote_access.generate_key()
        second = remote_access.generate_key()
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_redacted_status_never_contains_key(self):
        secret = "super-secret-channel-key"
        config = remote_access.RemoteAccessConfig(key=secret)
        encoded = json.dumps(config.redacted())
        self.assertNotIn(secret, encoded)
        self.assertTrue(config.redacted()["key_configured"])

    def test_save_uses_private_permissions_when_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote.json"
            config = remote_access.RemoteAccessConfig(key="secret")
            remote_access.save_config(config, path)
            loaded = remote_access.load_config(path)
            self.assertEqual(loaded, config)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class LegacyConfigTests(unittest.TestCase):
    def test_apply_updates_endpoint_key_and_role(self):
        original = """YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "key"
transport = RelayTransport(
    serializer,
    ("host", 6837),
    channel="key",
    connection_type="slave"
)
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "orca-customizations.py"
            path.write_text(original, encoding="utf-8")
            config = remote_access.RemoteAccessConfig(
                host="nvdaremote.com",
                port=6837,
                role="client",
                key="abc123",
            )
            remote_access.update_legacy_orca_customizations(config, path)
            result = path.read_text(encoding="utf-8")

            self.assertIn('YOUR_NVDAREMOTE_SERVER_ADDRESS = "nvdaremote.com"', result)
            self.assertIn("YOUR_NVDAREMOTE_SERVER_PORT = 6837", result)
            self.assertIn('YOUR_NVDAREMOTE_KEY = "abc123"', result)
            self.assertIn('connection_type="master"', result)
            self.assertTrue(path.with_name(path.name + ".linux-rdaccess-backup").exists())


    # ---- legacy Orca Remote input shim -------------------------------

    UPSTREAM_CONTROLLER = '''import logging
log = logging.getLogger("fake")

class RemoteController:
    control_state = 1

    def _on_remote_key(self, key_name=None, pressed=None, modifiers=None,
                       vk_code=None, scan_code=None, extended=None, **kwargs):
        if pressed is None:
            return
        self.local_machine.send_key(
            key_name=key_name, pressed=pressed, modifiers=modifiers,
            vk_code=vk_code, scan_code=scan_code, extended=extended,
        )

    def toggle_control(self):
        self.control_state = 0 if self.control_state else 1

    def _on_remote_sas(self, **kwargs):
        pass

    def _on_remote_braille_input(self, **kwargs):
        log.debug("Remote braille input: %s" % kwargs)

    def _on_remote_braille_info(self, name=None, numCells=None, **kwargs):
        pass
'''

    class FakeLocal:
        def __init__(self):
            self.events = []

        def cancel_speech(self):
            self.events.append(("cancel",))

        def send_key(self, **kw):
            self.events.append(("key", kw["vk_code"], bool(kw["pressed"])))

    def _patched_controller(self, home=None, source=None):
        import types
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "remote_controller.py"
        path.write_text(source or self.UPSTREAM_CONTROLLER, encoding="utf-8")
        self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
        module = types.ModuleType("patched_rc")
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        controller = module.RemoteController()
        controller.local_machine = self.FakeLocal()
        return controller, path, temp.name

    def _key(self, controller, vk, pressed, extended=False):
        controller._on_remote_key(
            key_name=None, pressed=pressed, modifiers=None,
            vk_code=vk, scan_code=0, extended=extended,
        )

    def test_patch_is_idempotent_compiles_and_backs_up(self):
        controller, path, _ = self._patched_controller()
        once = path.read_text(encoding="utf-8")
        self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))
        self.assertEqual(path.read_text(encoding="utf-8"), once)
        self.assertEqual(
            path.with_name(path.name + ".linux-rdaccess-backup").read_text(encoding="utf-8"),
            self.UPSTREAM_CONTROLLER,
        )

    def test_patch_rejects_signature_without_vk_code(self):
        broken = self.UPSTREAM_CONTROLLER.replace("vk_code=None, ", "")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(broken, encoding="utf-8")
            with self.assertRaises(ValueError):
                remote_access.patch_legacy_orca_remote_controller(path)
            self.assertEqual(path.read_text(encoding="utf-8"), broken)

    def test_v1_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V1 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertEqual(result.count("_linux_rdaccess_filter_key(\n"), 1)

    def test_ctrl_interrupts_speech_once_but_modifier_repeat_does_not(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x11, True)
        self._key(c, 0x11, True)      # auto-repeat
        self._key(c, 0x2D, True)      # Insert held for a chord
        self._key(c, 0x2D, True)      # Insert auto-repeat
        self.assertEqual([e for e in c.local_machine.events if e[0] == "cancel"], [("cancel",)])
        self._key(c, 0x28, True, extended=True)   # Down arrow
        self.assertEqual(sum(e[0] == "cancel" for e in c.local_machine.events), 2)

    def test_nvda_space_becomes_a_once_and_repeat_is_consumed(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True)
        self._key(c, 0x20, True)
        self._key(c, 0x20, True)      # auto-repeat must not toggle again
        self._key(c, 0x20, False)
        keys = [e for e in c.local_machine.events if e[0] == "key"]
        self.assertEqual([k for k in keys if k[1] == 0x20], [])
        self.assertEqual(sum(k[1] == 0x41 and k[2] for k in keys), 1)

    def test_plain_space_then_insert_does_not_leave_space_stuck(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x20, True)      # normal Space, forwarded
        self._key(c, 0x2D, True)      # Insert pressed while Space held
        self._key(c, 0x20, False)     # release must be forwarded
        keys = [e for e in c.local_machine.events if e[0] == "key"]
        self.assertIn(("key", 0x20, True), keys)
        self.assertIn(("key", 0x20, False), keys)

    def test_stale_nvda_modifier_is_forgotten_when_control_changes(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True)      # Insert down, release never arrives
        c.toggle_control()            # back to local ...
        c.toggle_control()            # ... and remote again, no key between
        self._key(c, 0x20, True)
        self._key(c, 0x20, False)
        keys = [e for e in c.local_machine.events if e[0] == "key"]
        self.assertIn(("key", 0x20, True), keys)
        self.assertFalse(any(k[1] == 0x41 for k in keys))

    def test_braille_trace_is_private_bounded_and_redacts_typed_input(self):
        import os
        c, _, home = self._patched_controller()
        with mock.patch.dict(os.environ, {"HOME": home}):
            Path(home, ".local/share/orca").mkdir(parents=True)
            c._on_remote_braille_input(
                id="br(eurobraille.bnote):backward", identifiers=["br(eurobraille):backward"],
                scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"],
                source="eurobraille", model="bnote", key="SECRET-KEY",
            )
            c._on_remote_braille_input(
                id="br(eurobraille.bnote):dot1+dot2", dots=3, space=False,
                source="eurobraille", model="bnote",
            )
            log = Path(home, ".local/share/orca/orca-remote-braille-input.log")
            data = log.read_text(encoding="utf-8")
            self.assertEqual(oct(log.stat().st_mode & 0o777), "0o600")
            self.assertIn("braille_scrollBack", data)
            self.assertNotIn("SECRET-KEY", data)
            self.assertNotIn("dot1", data)
            self.assertIn("braille-keyboard-input", data)

    def test_braille_pan_gestures_dispatch_to_orca(self):
        import sys, types, os
        calls = []
        fake_braille = types.SimpleNamespace(
            panLeft=lambda: calls.append("left"), panRight=lambda: calls.append("right"))
        fake_orca = types.ModuleType("orca")
        fake_orca.braille = fake_braille
        c, _, home = self._patched_controller()
        c._linux_rdaccess_run_main = lambda func: func()
        Path(home, ".local/share/orca").mkdir(parents=True)
        with mock.patch.dict(sys.modules, {"orca": fake_orca, "orca.braille": fake_braille}), \
                mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"])
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "script_braille_scrollForward"])
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"], routingIndex=4)
        self.assertEqual(calls, ["left", "right"])

    def test_connect_survives_unpatchable_controller(self):
        with tempfile.TemporaryDirectory() as temp:
            orca = Path(temp)
            cfg = orca / "orca-customizations.py"
            cfg.write_text('YOUR_NVDAREMOTE_SERVER_ADDRESS = "x"\nYOUR_NVDAREMOTE_SERVER_PORT = 1\nYOUR_NVDAREMOTE_KEY = "k"\nconnection_type="slave"\n', encoding="utf-8")
            scripts = orca / "orca-scripts"
            scripts.mkdir()
            (scripts / "remote_controller.py").write_text("class RemoteController:\n    pass\n", encoding="utf-8")
            config = remote_access.RemoteAccessConfig(host="h", port=2, key="secret", role="host")
            remote_access.update_legacy_orca_customizations(config, cfg)
            self.assertIn('"h"', cfg.read_text(encoding="utf-8"))


class ValidationTests(unittest.TestCase):
    def test_bad_port_rejected(self):
        with self.assertRaises(ValueError):
            remote_access.validate_port(0)

    def test_whitespace_host_rejected(self):
        with self.assertRaises(ValueError):
            remote_access.validate_host("bad host")


if __name__ == "__main__":
    unittest.main()
