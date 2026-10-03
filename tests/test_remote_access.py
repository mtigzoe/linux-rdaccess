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

    class FakeTransport:
        connected = True

        def __init__(self):
            self.events = []

        def send(self, **kw):
            self.events.append(kw)

    class FakeLocal:
        def __init__(self):
            self.events = []

        def cancel_speech(self):
            self.events.append(("cancel",))

        def send_key(self, **kw):
            self.events.append(("key", kw["vk_code"], bool(kw["pressed"]), kw.get("key_name")))

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
        controller.transport = self.FakeTransport()
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

    def test_v2_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V2 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V2 + "\n", result)

    def test_v1_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V1 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertEqual(result.count("_linux_rdaccess_filter_key(\n"), 1)

    def test_ctrl_interrupts_local_and_remote_speech_once(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x11, True)
        self._key(c, 0x11, True)      # auto-repeat
        self._key(c, 0x2D, True)      # Insert held for a chord
        self._key(c, 0x2D, True)      # Insert auto-repeat
        self.assertEqual([e for e in c.local_machine.events if e[0] == "cancel"], [("cancel",)])
        self.assertEqual(c.transport.events, [{"type": "cancel"}])

        # Ordinary navigation can interrupt local Orca output, but should not
        # add NVDA Remote cancel traffic for every key press.
        self._key(c, 0x28, True, extended=True)   # Down arrow
        self.assertEqual(sum(e[0] == "cancel" for e in c.local_machine.events), 2)
        self.assertEqual(c.transport.events, [{"type": "cancel"}])

    def test_nvda_f7_opens_elements_list_once_and_consumes_release(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_run_main = lambda func: func()
        c._linux_rdaccess_show_elements_list = lambda modifiers: calls.append("elements")
        self._key(c, 0x2D, True)
        self._key(c, 0x76, True)      # NVDA+F7
        self._key(c, 0x76, True)      # auto-repeat consumed
        self._key(c, 0x76, False)
        self.assertEqual(calls, ["elements"])
        keys = [e for e in c.local_machine.events if e[0] == "key" and e[1] == 0x76]
        self.assertEqual(keys, [])

    def test_plain_f7_is_untouched(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x76, True)
        self._key(c, 0x76, False)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertIn(("key", 0x76, True), keys)
        self.assertIn(("key", 0x76, False), keys)

    def test_nvda_space_becomes_a_once_and_repeat_is_consumed(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True)
        self._key(c, 0x20, True)
        self._key(c, 0x20, True)      # auto-repeat must not toggle again
        self._key(c, 0x20, False)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertEqual([k for k in keys if k[1] == 0x20], [])
        self.assertEqual(sum(k[1] == 0x41 and k[2] for k in keys), 1)

    def test_plain_space_then_insert_does_not_leave_space_stuck(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x20, True)      # normal Space, forwarded
        self._key(c, 0x2D, True)      # Insert pressed while Space held
        self._key(c, 0x20, False)     # release must be forwarded
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertIn(("key", 0x20, True), keys)
        self.assertIn(("key", 0x20, False), keys)

    def test_stale_nvda_modifier_is_forgotten_when_control_changes(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True)      # Insert down, release never arrives
        c.toggle_control()            # back to local ...
        c.toggle_control()            # ... and remote again, no key between
        self._key(c, 0x20, True)
        self._key(c, 0x20, False)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
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

    def _with_fake_orca(self, c, home):
        import sys, types
        calls = []
        script = types.SimpleNamespace(
            panBrailleLeft=lambda ev=None: calls.append(("left", ev)),
            panBrailleRight=lambda ev=None: calls.append(("right", ev)),
            processRoutingKey=lambda ev=None: calls.append(("route", ev.event["argument"])),
        )
        orca = types.ModuleType("orca")
        state = types.ModuleType("orca.orca_state")
        state.activeScript = script
        orca.orca_state = state
        c._linux_rdaccess_run_main = lambda func: func()
        Path(home, ".local/share/orca").mkdir(parents=True, exist_ok=True)
        patches = mock.patch.dict(sys.modules, {"orca": orca, "orca.orca_state": state})
        return calls, patches

    def test_braille_pan_uses_active_script_handlers_not_viewport(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"])
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "script_braille_scrollForward"])
        self.assertEqual(calls, [("left", None), ("right", None)])

    def test_braille_routing_key_reaches_script_with_cell_argument(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"], routingIndex=7)
            for bad in (-1, 5000, True, "3", None):
                c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"], routingIndex=bad)
        self.assertEqual(calls, [("route", 7)])

    def test_typed_braille_never_triggers_pan_or_route(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(id="br(x):dot1", dots=1, space=False,
                                       scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"])
        self.assertEqual(calls, [])

    def _names(self, c):
        return [(e[1], e[2]) for e in c.local_machine.events if e[0] == "key"]

    def test_nvda_say_all_drops_modifier_around_numpad_plus(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x28, True, extended=True)    # NVDA+Down
        self._key(c, 0x28, True, extended=True)    # auto-repeat consumed
        self._key(c, 0x28, False, extended=True)
        self.assertEqual(self._names(c), [
            (0x2D, True), (0x2D, False), (0x6B, True), (0x6B, False), (0x2D, True)])

    def test_plain_arrow_and_numpad_arrow_with_nvda_are_untouched(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x28, True, extended=True)    # no NVDA key: plain Down
        self._key(c, 0x28, False, extended=True)
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x28, True, extended=False)   # numpad 2 with NVDA: not ours
        self.assertEqual(self._names(c), [(0x28, True), (0x28, False), (0x2D, True), (0x28, True)])

    def test_chords_with_other_modifiers_pass_through(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA0, True)                   # Shift
        self._key(c, 0x28, True, extended=True)    # NVDA+Shift+Down
        self.assertIn((0x28, True), self._names(c))
        self.assertNotIn((0x6B, True), self._names(c))

    def test_capslock_nvda_key_is_never_released_or_repressed(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        self._key(c, 0x28, True, extended=True)    # drop-chord would toggle CapsLock
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [(0x14, True)])
        self.assertIn((0x28, True), self._names(c))
        self._key(c, 0x20, True)                   # keep-modifier chord still works
        self.assertIn((0x41, True), self._names(c))

    def test_title_and_status_chords_keep_modifier_and_count_presses(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x54, True); self._key(c, 0x54, False)           # NVDA+T
        self._key(c, 0x23, True, extended=True); self._key(c, 0x23, False, extended=True)  # NVDA+End
        enter = [k for k in self._names(c) if k[0] == 0x0D]
        self.assertEqual(enter, [(0x0D, True), (0x0D, False)] * 3)
        self.assertNotIn((0x2D, False), self._names(c))

    def test_v2_patch_is_upgraded_to_v4(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V1 + " v2\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            self.assertIn(" v4", path.read_text(encoding="utf-8"))

    def test_connect_installs_orca_runtime_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / "orca-customizations.py"
            cfg.write_text(
                'YOUR_NVDAREMOTE_SERVER_ADDRESS = "x"\n'
                'YOUR_NVDAREMOTE_SERVER_PORT = 1\n'
                'YOUR_NVDAREMOTE_KEY = "k"\n'
                'connection_type="slave"\n',
                encoding="utf-8",
            )
            scripts = root / "orca-scripts"
            scripts.mkdir()
            controller = scripts / "remote_controller.py"
            controller.write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            adapter_source = Path(remote_access.__file__).with_name("orca_adapter.py")
            self.assertTrue(adapter_source.exists())

            config = remote_access.RemoteAccessConfig(
                host="h", port=2, key="secret", role="host"
            )
            remote_access.update_legacy_orca_customizations(config, cfg)

            installed = scripts / "linux_rdaccess_orca_adapter.py"
            self.assertTrue(installed.exists())
            self.assertIn("OrcaRuntimeAdapter", installed.read_text(encoding="utf-8"))

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
