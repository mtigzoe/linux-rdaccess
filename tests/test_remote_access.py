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
import os
import time
log = logging.getLogger("fake")
_DBG_LOG = os.path.expanduser("~/.local/share/orca/orca-remote-debug.log")

def _dbg(msg):
    with open(_DBG_LOG, "a") as f:
        f.write("RC: %s\\n" % msg)

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

    transport = None

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
        def __init__(self, connected=True, connection_type="slave"):
            self.connected = connected
            self.connection_type = connection_type
            self.events = []
            self.sent = []

        def send(self, **kw):
            self.events.append(kw)
            self.sent.append(kw.get("type"))


    class FakeLocal:
        def __init__(self):
            self.events = []

        def cancel_speech(self):
            self.events.append(("cancel",))

        def send_key(self, **kw):
            self.events.append(("key", kw["vk_code"], bool(kw["pressed"]), kw.get("key_name")))

    def _patched_controller(self, home=None, source=None, inline=True):
        import types
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "remote_controller.py"
        path.write_text(source or self.UPSTREAM_CONTROLLER, encoding="utf-8")
        self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
        module = types.ModuleType("patched_rc")
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        controller = module.RemoteController()
        controller._module = module
        controller.local_machine = self.FakeLocal()
        controller.transport = self.FakeTransport()
        if inline:
            controller._linux_rdaccess_run_main = lambda func: func()
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

    def test_f6_and_shift_f6_are_forwarded_unchanged(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x75, True)                    # F6
        self._key(c, 0x75, False)
        self._key(c, 0xA0, True)                    # Shift
        self._key(c, 0x75, True)                    # Shift+F6
        self._key(c, 0x75, False)
        self._key(c, 0xA0, False)
        self.assertEqual(self._names(c), [
            (0x75, True), (0x75, False),
            (0xA0, True), (0x75, True), (0x75, False), (0xA0, False),
        ])

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

    def test_v2_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V1 + " v2\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            self.assertIn(" v8", path.read_text(encoding="utf-8"))

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


    # ---- latency / privacy ---------------------------------------------

    UPSTREAM_LOCAL = '''import os, time
_DBG_LOG = os.path.expanduser("~/.local/share/orca/orca-remote-debug.log")

def _dbg(msg):
    try:
        with open(_DBG_LOG, "a") as f:
            f.write("[%.3f] LM: %s\\n" % (time.time(), msg))
    except Exception:
        pass

class LocalMachine:
    fallback_calls = []

    clip_threads = []

    def set_clipboard_text(self, text=None, **kwargs):
        import threading
        LocalMachine.clip_threads.append((threading.current_thread().name, text))

    def _send_key_xdotool(self, key, pressed):
        LocalMachine.fallback_calls.append((key, pressed))
        return True
'''

    def _patched_local(self):
        import types
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "local_machine.py"
        path.write_text(self.UPSTREAM_LOCAL, encoding="utf-8")
        self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
        module = types.ModuleType("patched_lm")
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)
        module.LocalMachine.fallback_calls = []
        module.LocalMachine.clip_threads = []
        return module, path, temp.name

    def test_local_machine_patch_idempotent_backup_and_compiles(self):
        module, path, _ = self._patched_local()
        once = path.read_text(encoding="utf-8")
        self.assertFalse(remote_access.patch_legacy_orca_local_machine(path))
        self.assertEqual(path.read_text(encoding="utf-8"), once)
        self.assertEqual(
            path.with_name(path.name + ".linux-rdaccess-backup").read_text(encoding="utf-8"),
            self.UPSTREAM_LOCAL)

    def test_local_machine_patch_rejects_unknown_layout_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local_machine.py"
            path.write_text("class LocalMachine:\n    pass\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                remote_access.patch_legacy_orca_local_machine(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "class LocalMachine:\n    pass\n")

    def test_xtest_success_skips_the_xdotool_process(self):
        module, _, _ = self._patched_local()
        module._LRD_XTEST.key = lambda name, pressed: True
        self.assertTrue(module.LocalMachine()._send_key_xdotool("Down", True))
        self.assertEqual(module.LocalMachine.fallback_calls, [])

    def test_xtest_unavailable_falls_back_to_upstream_path(self):
        module, _, _ = self._patched_local()
        module._LRD_XTEST.key = lambda name, pressed: False
        module.LocalMachine()._send_key_xdotool("Down", True)
        self.assertEqual(module.LocalMachine.fallback_calls, [("Down", True)])

    def test_xtest_helper_without_display_or_libs_disables_itself(self):
        import os
        module, _, _ = self._patched_local()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            helper = module._LrdXTest()
            self.assertFalse(helper.key("Down", True))
            self.assertFalse(helper.key("Down", False))
            self.assertTrue(helper._failed)

    def test_per_keypress_debug_log_is_off_by_default_and_opt_in(self):
        import os
        module, _, home = self._patched_local()
        log = Path(home, ".local/share/orca/orca-remote-debug.log")
        log.parent.mkdir(parents=True)
        module._DBG_LOG = str(log)
        env = {k: v for k, v in os.environ.items() if k != "LINUX_RDACCESS_DEBUG"}
        with mock.patch.dict(os.environ, env, clear=True):
            module._dbg("key=SECRET")
        self.assertFalse(log.exists())
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_DEBUG": "1"}):
            module._dbg("key=visible-when-opted-in")
        self.assertIn("visible-when-opted-in", log.read_text(encoding="utf-8"))

    def test_controller_debug_log_is_silenced_too(self):
        import os
        c, path, home = self._patched_controller()
        import sys
        module = sys.modules.get("patched_rc")
        log = Path(home, "dbg.log")
        ns = {}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
        ns["_DBG_LOG"] = str(log)
        env = {k: v for k, v in os.environ.items() if k != "LINUX_RDACCESS_DEBUG"}
        with mock.patch.dict(os.environ, env, clear=True):
            ns["_dbg"]("name='SECRET'")
        self.assertFalse(log.exists())

    def test_held_arrow_does_not_cancel_speech_on_every_repeat(self):
        c, _, _ = self._patched_controller()
        clock = [100.0]
        with mock.patch("time.monotonic", lambda: clock[0]):
            self._key(c, 0x28, True, extended=True)              # first press
            for _ in range(5):                                    # 30 Hz repeats
                clock[0] += 0.033
                self._key(c, 0x28, True, extended=True)
            cancels = sum(e[0] == "cancel" for e in c.local_machine.events)
            self.assertEqual(cancels, 2)                          # first + one after 150 ms
            self._key(c, 0x28, False, extended=True)
            self._key(c, 0x28, True, extended=True)               # a fresh press always cancels
            self.assertEqual(sum(e[0] == "cancel" for e in c.local_machine.events), 3)

    def test_ctrl_sends_cancel_to_nvda_immediately(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0xA2, True)                    # Left Ctrl, nothing spoken after
        self.assertEqual(c.transport.sent, ["cancel"])
        self._key(c, 0xA2, True)                    # auto-repeat: no second cancel
        self.assertEqual(c.transport.sent, ["cancel"])
        self._key(c, 0xA2, False)
        self.assertEqual(c.transport.sent, ["cancel"])

    def test_right_ctrl_and_generic_ctrl_also_cancel_nvda(self):
        for vk in (0x11, 0xA3):
            c, _, _ = self._patched_controller()
            self._key(c, vk, True)
            self.assertEqual(c.transport.sent, ["cancel"], hex(vk))

    def test_only_ctrl_sends_the_nvda_protocol_cancel(self):
        # Policy of this branch: the protocol cancel is Ctrl-only so ordinary
        # navigation keys add no network message. Local Orca speech is still
        # stopped for real actions, but never for bare modifiers.
        c, _, _ = self._patched_controller()
        for vk in (0x10, 0x12, 0x2D, 0x14, 0x5B):   # Shift Alt Insert Caps Win
            self._key(c, vk, True)
        self.assertEqual(c.transport.sent, [])
        self.assertEqual([e for e in c.local_machine.events if e[0] == "cancel"], [])
        self._key(c, 0x28, True, extended=True)     # Down
        self.assertEqual(c.transport.sent, [])
        self.assertEqual([e for e in c.local_machine.events if e[0] == "cancel"], [("cancel",)])

    def test_no_cancel_sent_when_disconnected_or_not_slave(self):
        for transport in (self.FakeTransport(connected=False), self.FakeTransport(connection_type="master")):
            c, _, _ = self._patched_controller()
            c.transport = transport
            self._key(c, 0xA2, True)
            self.assertEqual(transport.sent, [])
            self.assertEqual(c.local_machine.events[0], ("cancel",))   # local stop still happens

    def test_transport_failure_never_blocks_key_forwarding(self):
        c, _, _ = self._patched_controller()
        def boom(type, **kw):
            raise RuntimeError("socket gone")
        c.transport.send = boom
        self._key(c, 0xA2, True)
        self.assertIn((0xA2, True), [(e[1], e[2]) for e in c.local_machine.events if e[0] == "key"])

    def test_held_arrow_stops_local_speech_at_most_every_150ms_and_never_hits_the_network(self):
        c, _, _ = self._patched_controller()
        clock = [50.0]
        with mock.patch("time.monotonic", lambda: clock[0]):
            self._key(c, 0x28, True, extended=True)
            for _ in range(5):
                clock[0] += 0.033
                self._key(c, 0x28, True, extended=True)
        self.assertEqual(c.transport.sent, [])
        self.assertEqual(sum(e[0] == "cancel" for e in c.local_machine.events), 2)

    def _fake_glib(self):
        import sys, types
        queue = []
        glib = types.SimpleNamespace(idle_add=lambda fn: queue.append(fn))
        gi = types.ModuleType("gi")
        repo = types.ModuleType("gi.repository")
        repo.GLib = glib
        gi.repository = repo
        return queue, mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repo})

    def test_slow_speech_stop_never_runs_on_the_key_receiving_thread(self):
        import time
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        slow = []
        c.local_machine.cancel_speech = lambda: (time.sleep(0.2), slow.append(1))
        with patches:
            start = time.perf_counter()
            for _ in range(20):
                self._key(c, 0x28, True, extended=True)
                self._key(c, 0x28, False, extended=True)
            elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.1)            # 20 keystrokes while stop would take 200 ms
        self.assertEqual(slow, [])               # nothing ran on this thread
        self.assertEqual(len(queue), 1)          # coalesced into one main-loop job
        self.assertEqual(c.transport.sent, [])   # arrows: no protocol cancel (Ctrl-only policy)

    def test_pending_local_stop_is_coalesced_then_rearmed(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        calls = []
        c.local_machine.cancel_speech = lambda: calls.append(1)
        with patches:
            for _ in range(5):
                self._key(c, 0x28, True, extended=True)
                self._key(c, 0x28, False, extended=True)
            self.assertEqual(len(queue), 1)
            queue.pop()()
            self.assertEqual(calls, [1])
            self._key(c, 0x28, True, extended=True)
            self.assertEqual(len(queue), 1)

    def test_slow_event_log_records_duration_not_key_identity(self):
        import os, time
        c, path, home = self._patched_controller()
        import sys
        ns = {}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
        ctl = ns["RemoteController"]()
        local = self.FakeLocal()
        local.send_key = lambda **kw: time.sleep(0.04)
        ctl.local_machine = local
        ctl.transport = self.FakeTransport()
        ctl._linux_rdaccess_run_main = lambda func: func()
        log = Path(home, ".local/share/orca/orca-remote-slow-events.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "LINUX_RDACCESS_DEBUG"}
        env["HOME"] = home
        with mock.patch.dict(os.environ, env, clear=True):
            ctl._on_remote_key(key_name="SECRETKEY", pressed=True, modifiers=None, vk_code=0x41, scan_code=0, extended=False)
        self.assertFalse(log.exists())           # off by default
        env["LINUX_RDACCESS_DEBUG"] = "1"
        with mock.patch.dict(os.environ, env, clear=True):
            ctl._on_remote_key(key_name="SECRETKEY", pressed=True, modifiers=None, vk_code=0x41, scan_code=0, extended=False)
        data = log.read_text(encoding="utf-8")
        import re
        # Exact format: timestamp, duration, press/release - nothing identifying the key.
        for line in data.splitlines():
            self.assertRegex(line, r"^\d+\.\d+ key-event handling took \d+ ms \((press|release)\)$")
        self.assertNotIn("SECRETKEY", data)

    def test_clipboard_write_from_network_thread_is_moved_to_main_loop(self):
        import threading
        module, _, _ = self._patched_local()
        queue, patches = self._fake_glib()
        machine = module.LocalMachine()
        with patches:
            worker = threading.Thread(target=lambda: machine.set_clipboard_text(text="x"), name="net")
            worker.start()
            worker.join()
            self.assertEqual(module.LocalMachine.clip_threads, [])   # not executed on "net"
            self.assertEqual(len(queue), 1)
            queue.pop()()                                            # main loop runs it
        self.assertEqual(module.LocalMachine.clip_threads[0][1], "x")

    def test_clipboard_write_on_main_thread_runs_directly(self):
        module, _, _ = self._patched_local()
        module.LocalMachine().set_clipboard_text(text="direct")
        self.assertEqual([t for _, t in module.LocalMachine.clip_threads], ["direct"])

    def test_local_machine_v1_patch_is_upgraded_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local_machine.py"
            path.write_text(self.UPSTREAM_LOCAL + "\n" + remote_access.LOCAL_MACHINE_MARKER_V1 + " v1\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_LOCAL, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LOCAL_MACHINE_MARKER, result)
            self.assertEqual(result.count("_LRD_XTEST = _LrdXTest()"), 1)

    # ---- NVDA D (landmark) -> Orca M, browse mode only -------------------

    SHIFT, CTRL, ALT, ORCA = 1, 4, 8, 256
    M_CODE, D_CODE = 58, 40

    def _orca_env(self, browse=True):
        """Fake Orca 42 pieces with the same shouldConsume order as the real one."""
        import sys, types
        test = self
        kb = types.ModuleType("orca.keybindings")
        kb.SHIFT_MODIFIER_MASK, kb.CTRL_MODIFIER_MASK = self.SHIFT, self.CTRL
        kb.ALT_MODIFIER_MASK, kb.ORCA_MODIFIER_MASK = self.ALT, self.ORCA
        kb.getKeycode = lambda key: {"m": self.M_CODE, "d": self.D_CODE}.get(key)

        landmark_next = types.SimpleNamespace(function="landmark_next")
        landmark_prev = types.SimpleNamespace(function="landmark_prev")
        live_region = types.SimpleNamespace(function="live_region")

        class Bindings:
            table = {
                (test.M_CODE, 0): landmark_next,
                (test.M_CODE, test.SHIFT): landmark_prev,
                (test.D_CODE, 0): live_region,
                (test.D_CODE, test.SHIFT): live_region,
            }

            def getInputHandler(self, event):
                return self.table.get((event.hw_code, event.modifiers & test.SHIFT))

        class Script:
            keyBindings = Bindings()
            structuralNavigation = types.SimpleNamespace(
                functions=["landmark_next", "landmark_prev"])
            state = {"browse": browse}

            def useStructuralNavigationModel(self):
                return self.state["browse"]

        script = Script()

        class KeyboardEvent:
            def __init__(self, string, hw_code, modifiers=0, pressed=True):
                self.event_string, self.hw_code = string, hw_code
                self.modifiers, self._pressed, self._script = modifiers, pressed, script
                self._handler = None
                self.consume = self.shouldConsume()

            def isPressedKey(self):
                return self._pressed

            def shouldConsume(self):
                # Orca captures the handler first, then asks the script.
                self._handler = self._script.keyBindings.getInputHandler(self)
                return bool(self._handler)

        ie = types.ModuleType("orca.input_event")
        ie.KeyboardEvent = KeyboardEvent
        orca = types.ModuleType("orca")
        orca.input_event, orca.keybindings = ie, kb
        patches = mock.patch.dict(sys.modules, {
            "orca": orca, "orca.input_event": ie, "orca.keybindings": kb})
        return KeyboardEvent, script, patches

    def _hooked(self, browse=True):
        c, _, _ = self._patched_controller()
        KeyboardEvent, script, patches = self._orca_env(browse)
        patches.start()
        self.addCleanup(patches.stop)
        self.assertTrue(c._module._lrd_install_orca_hook())
        return c, KeyboardEvent, script

    def _remote_d(self, c, shift=False):
        if shift:
            self._key(c, 0xA0, True)
        self._key(c, 0x44, True)

    def test_remote_d_in_browse_mode_becomes_landmark_and_hw_code_is_restored(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        ev = KE("d", self.D_CODE)
        self.assertTrue(ev.consume)
        self.assertEqual(ev._handler.function, "landmark_next")
        self.assertEqual(ev.hw_code, self.D_CODE)       # echo/click-count see the real key

    def test_shift_d_goes_to_previous_landmark(self):
        c, KE, _ = self._hooked()
        self._remote_d(c, shift=True)
        ev = KE("D", self.D_CODE, modifiers=self.SHIFT)
        self.assertEqual(ev._handler.function, "landmark_prev")
        self.assertEqual(ev.modifiers, self.SHIFT)

    def test_d_not_from_the_remote_session_is_never_translated(self):
        c, KE, _ = self._hooked()
        ev = KE("d", self.D_CODE)                        # local keyboard: no remote marker
        self.assertEqual(ev._handler.function, "live_region")

    def test_stale_remote_marker_expires(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        c._module._LRD_D["ts"] -= 5.0
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_focus_mode_or_non_document_is_left_alone_so_typing_works(self):
        c, KE, script = self._hooked(browse=False)       # Orca says: no structural nav
        self._remote_d(c)
        ev = KE("d", self.D_CODE)
        self.assertEqual(ev._handler.function, "live_region")
        self.assertEqual(ev.hw_code, self.D_CODE)

    def test_refused_remote_d_does_not_leak_into_a_later_local_d(self):
        # Found by running the hook through real Orca 42: the marker used to
        # survive a refused (focus-mode) remote D and tag the next local D.
        c, KE, script = self._hooked(browse=False)
        self._remote_d(c)
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")
        script.state["browse"] = True
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_one_remote_d_marks_exactly_one_orca_d(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "landmark_next")
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_mode_is_re_read_from_orca_for_every_key(self):
        c, KE, script = self._hooked()
        self._remote_d(c)
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "landmark_next")
        script.state["browse"] = False                   # user pressed NVDA+Space
        self._remote_d(c)
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_ctrl_alt_orca_d_and_nvda_d_are_untouched(self):
        c, KE, _ = self._hooked()
        for mod in (self.CTRL, self.ALT, self.ORCA):
            c._module._LRD_D["ts"] = __import__("time").monotonic()   # even with a fresh marker
            ev = KE("d", self.D_CODE, modifiers=mod)
            self.assertNotEqual(getattr(ev._handler, "function", None), "landmark_next", mod)
            self.assertEqual(ev.hw_code, self.D_CODE)
            c._module._LRD_D["ts"] = 0.0
        # NVDA key held: remote side never marks the D
        c3, KE3, _ = self._hooked()
        self._key(c3, 0x2D, True)
        self._key(c3, 0x44, True)
        self.assertEqual(c3._module._LRD_D["ts"], 0.0)
        self.assertEqual(KE3("d", self.D_CODE)._handler.function, "live_region")

    def test_remote_ctrl_d_does_not_mark_the_key(self):
        c, KE, _ = self._hooked()
        self._key(c, 0xA2, True)
        self._key(c, 0x44, True)
        self.assertEqual(c._module._LRD_D["ts"], 0.0)

    def test_release_follows_its_press_and_stray_release_does_not_swap(self):
        c, KE, _ = self._hooked()
        stray = KE("d", self.D_CODE, pressed=False)      # release with no swapped press
        self.assertEqual(stray._handler.function, "live_region")
        self._remote_d(c)
        KE("d", self.D_CODE)                              # swapped press
        rel = KE("d", self.D_CODE, pressed=False)
        self.assertEqual(rel._handler.function, "landmark_next")
        again = KE("d", self.D_CODE, pressed=False)       # second release: state cleared
        self.assertEqual(again._handler.function, "live_region")

    def test_other_keys_pass_through_untouched(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        ev = KE("m", self.M_CODE)
        self.assertEqual(ev._handler.function, "landmark_next")
        self.assertEqual(ev.hw_code, self.M_CODE)

    def test_opt_out_environment_variable_disables_translation(self):
        import os
        c, KE, _ = self._hooked()
        self._remote_d(c)
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_D_LANDMARK": "0"}):
            self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_hook_is_installed_once_and_survives_internal_errors(self):
        c, KE, script = self._hooked()
        self.assertTrue(c._module._lrd_install_orca_hook())       # idempotent
        first = KE.shouldConsume
        c._module._lrd_install_orca_hook()
        self.assertIs(KE.shouldConsume, first)
        self._remote_d(c)
        script.useStructuralNavigationModel = lambda: 1 / 0       # Orca-side failure
        ev = KE("d", self.D_CODE)
        self.assertEqual(ev._handler.function, "live_region")     # original still ran
        self.assertEqual(ev.hw_code, self.D_CODE)

    def test_hook_without_orca_importable_does_not_raise(self):
        c, _, _ = self._patched_controller()
        import sys
        with mock.patch.dict(sys.modules, {"orca": None}):
            self.assertFalse(c._module._lrd_install_orca_hook())

    # ---- NVDA+Shift+Space (single-letter nav) and NVDA+F2 (pass next key) --

    def test_nvda_shift_space_is_orca_z_with_shift_released_around_it(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)     # NVDA (Insert)
        self._key(c, 0xA0, True)                    # Left Shift
        self._key(c, 0x20, True)                    # Space
        self.assertEqual(self._names(c), [
            (0x2D, True), (0xA0, True),             # forwarded as typed
            (0xA0, False), (0x5A, True), (0x5A, False), (0xA0, True)])
        # NVDA stays held throughout (Orca needs its modifier for Orca+Z).
        self.assertNotIn((0x2D, False), self._names(c))

    def test_nvda_shift_space_repeat_and_release_are_consumed(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA0, True)
        self._key(c, 0x20, True)
        before = len(self._names(c))
        self._key(c, 0x20, True)                    # auto-repeat
        self._key(c, 0x20, False)                   # release of the translated Space
        self.assertEqual(len(self._names(c)), before)
        self.assertNotIn((0x20, True), self._names(c))
        self.assertNotIn((0x20, False), self._names(c))

    def test_both_shift_keys_are_released_and_restored(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA0, True)
        self._key(c, 0xA1, True)
        self._key(c, 0x20, True)
        tail = self._names(c)[3:]
        self.assertEqual(sorted(tail[:2]), [(0xA0, False), (0xA1, False)])
        self.assertEqual(tail[2:4], [(0x5A, True), (0x5A, False)])
        self.assertEqual(sorted(tail[4:]), [(0xA0, True), (0xA1, True)])

    def test_shift_space_without_nvda_key_types_normally(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0xA0, True)
        self._key(c, 0x20, True)
        self._key(c, 0x20, False)
        self.assertEqual(self._names(c), [(0xA0, True), (0x20, True), (0x20, False)])

    def test_nvda_shift_space_with_ctrl_or_alt_is_untouched(self):
        for extra in (0xA2, 0xA4):
            c, _, _ = self._patched_controller()
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0xA0, True)
            self._key(c, extra, True)
            self._key(c, 0x20, True)
            self.assertIn((0x20, True), self._names(c), hex(extra))
            self.assertNotIn((0x5A, True), self._names(c))

    def test_nvda_space_without_shift_is_still_the_focus_browse_toggle(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x20, True)
        self.assertEqual(self._names(c)[1:], [(0x41, True), (0x41, False)])

    def test_shift_released_before_space_does_not_confuse_the_release(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA0, True)
        self._key(c, 0x20, True)                    # translated while Shift held
        self._key(c, 0xA0, False)                   # user lets go of Shift first
        self._key(c, 0x20, False)                   # then Space: still consumed
        self.assertEqual([k for k in self._names(c) if k[0] == 0x20], [])
        names = self._names(c)
        self.assertEqual(names.count((0xA0, True)), 2)    # typed press + our restore
        self.assertEqual(names.count((0xA0, False)), 2)   # our release + the user's

    def test_nvda_f2_is_orca_backspace_with_nvda_held(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x71, True)
        self.assertEqual(self._names(c)[1:], [(0x08, True), (0x08, False)])
        self.assertNotIn((0x2D, False), self._names(c))
        self._key(c, 0x71, False)
        self.assertEqual(len(self._names(c)), 3)    # release consumed

    def test_plain_f2_and_shift_f2_rename_keys_are_untouched(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x71, True); self._key(c, 0x71, False)          # Thunar F2 rename
        self._key(c, 0xA0, True); self._key(c, 0x71, True)
        self.assertEqual(self._names(c), [(0x71, True), (0x71, False), (0xA0, True), (0x71, True)])

    def test_capslock_as_nvda_key_still_gets_the_shift_space_chord(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        self._key(c, 0xA0, True)
        self._key(c, 0x20, True)
        self.assertIn((0x5A, True), self._names(c))
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [(0x14, True)])

    def test_elements_list_chord_from_the_branch_still_works(self):
        c, _, _ = self._patched_controller()
        shown = []
        c._linux_rdaccess_show_elements_list = lambda modifiers: shown.append(1)
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x76, True)                    # NVDA+F7
        self.assertEqual(shown, [1])

    def test_connect_patches_local_machine_too(self):
        with tempfile.TemporaryDirectory() as temp:
            orca = Path(temp)
            cfg = orca / "orca-customizations.py"
            cfg.write_text('YOUR_NVDAREMOTE_SERVER_ADDRESS = "x"\nYOUR_NVDAREMOTE_SERVER_PORT = 1\nYOUR_NVDAREMOTE_KEY = "k"\nconnection_type="slave"\n', encoding="utf-8")
            scripts = orca / "orca-scripts"
            scripts.mkdir()
            (scripts / "local_machine.py").write_text(self.UPSTREAM_LOCAL, encoding="utf-8")
            config = remote_access.RemoteAccessConfig(host="h", port=2, key="secret", role="host")
            remote_access.update_legacy_orca_customizations(config, cfg)
            self.assertIn(remote_access.LOCAL_MACHINE_MARKER, (scripts / "local_machine.py").read_text(encoding="utf-8"))


class ValidationTests(unittest.TestCase):
    def test_bad_port_rejected(self):
        with self.assertRaises(ValueError):
            remote_access.validate_port(0)

    def test_whitespace_host_rejected(self):
        with self.assertRaises(ValueError):
            remote_access.validate_host("bad host")


if __name__ == "__main__":
    unittest.main()
