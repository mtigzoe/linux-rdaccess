from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import remote_access


@contextmanager
def private_write_checks(test):
    """Observe permissions before writing, including newly created files."""
    real_open, real_fdopen = Path.open, os.fdopen
    observed = []

    def check(handle, mode):
        if any(flag in mode for flag in ('w', 'a', 'x', '+')):
            observed.append(os.fstat(handle.fileno()).st_mode & 0o777)
            test.addCleanup(handle.close)
            test.assertEqual(observed[-1], 0o600)
        return handle

    def path_open(path, mode='r', *args, **kwargs):
        return check(real_open(path, mode, *args, **kwargs), mode)

    def fdopen(fd, mode='r', *args, **kwargs):
        return check(real_fdopen(fd, mode, *args, **kwargs), mode)

    previous_umask = os.umask(0o022)
    try:
        with mock.patch.object(Path, 'open', path_open), mock.patch.object(os, 'fdopen', fdopen):
            yield
        test.assertTrue(observed)
    finally:
        os.umask(previous_umask)


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

    def test_config_is_private_before_secret_content_is_written(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'remote.json'
            for existing in (False, True):
                if existing:
                    path.chmod(0o644)
                with private_write_checks(self):
                    remote_access.save_config(remote_access.RemoteAccessConfig(key='secret'), path)
                self.assertEqual(remote_access.load_config(path).key, 'secret')

    def test_failed_config_publish_preserves_old_file_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'remote.json'
            old = remote_access.RemoteAccessConfig(key='old-key')
            remote_access.save_config(old, path)
            with mock.patch.object(remote_access.os, 'replace', side_effect=OSError('failed')):
                with self.assertRaises(OSError):
                    remote_access.save_config(remote_access.RemoteAccessConfig(key='new-key'), path)
            self.assertEqual(remote_access.load_config(path), old)
            self.assertEqual(list(Path(temp).iterdir()), [path])


class LegacyConfigTests(unittest.TestCase):
    CONFIG_SOURCE = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "old-key"
connection_type="slave"
'''

    def test_customizations_and_backup_are_private_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(self.CONFIG_SOURCE, encoding='utf-8')
            path.chmod(0o644)
            with private_write_checks(self):
                remote_access.update_legacy_orca_customizations(
                    remote_access.RemoteAccessConfig(key='new-key'), path)
            backup = path.with_name(path.name + '.linux-rdaccess-backup')
            self.assertEqual(backup.read_text(encoding='utf-8'), self.CONFIG_SOURCE)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_connection_key_escapes_are_preserved_literally(self):
        import ast
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            path.write_text(self.CONFIG_SOURCE, encoding='utf-8')
            key = 'channel\\n\\1"tail'
            remote_access.update_legacy_orca_customizations(
                remote_access.RemoteAccessConfig(key=key), path)
            tree = ast.parse(path.read_text(encoding='utf-8'))
            assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                              and node.targets[0].id == 'YOUR_NVDAREMOTE_KEY')
            self.assertEqual(ast.literal_eval(assignment.value), key)

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


    def test_apply_protects_orca_customizations_key_permissions(self):
        original = """YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "key"
connection_type="slave"
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "orca-customizations.py"
            path.write_text(original, encoding="utf-8")
            path.chmod(0o644)
            config = remote_access.RemoteAccessConfig(
                host="nvdaremote.com",
                port=6837,
                role="host",
                key="private-channel-key",
            )
            remote_access.update_legacy_orca_customizations(config, path)
            backup = path.with_name(path.name + ".linux-rdaccess-backup")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertIn("key", backup.read_text(encoding="utf-8"))

    def test_local_orca_speech_preference_is_applied_in_slave_mode(self):
        original = """YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "key"
connection_type="slave"

class Transport:
    connection_type = "slave"
    connected = True  # Real legacy Transport has a connected flag.

transport = Transport()
calls = []

def old_speak(*args, **kwargs):
    calls.append("speak")

def old_speakCharacter(*args, **kwargs):
    calls.append("character")
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "orca-customizations.py"
            path.write_text(original, encoding="utf-8")

            muted = remote_access.RemoteAccessConfig(
                host="nvdaremote.com", port=6837, role="host",
                key="abc", mute_local_orca_speech=True,
            )
            remote_access.update_legacy_orca_customizations(muted, path)
            namespace = {}
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
            namespace["old_speak"]()
            namespace["old_speakCharacter"]()
            self.assertEqual(namespace["calls"], [])
            self.assertIn(
                remote_access.LOCAL_SPEECH_PREF_MARKER,
                path.read_text(encoding="utf-8"),
            )

            speaking = remote_access.RemoteAccessConfig(
                host="nvdaremote.com", port=6837, role="host",
                key="abc", mute_local_orca_speech=False,
            )
            remote_access.update_legacy_orca_customizations(speaking, path)
            namespace = {}
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
            namespace["old_speak"]()
            namespace["old_speakCharacter"]()
            self.assertEqual(namespace["calls"], ["speak", "character"])
            self.assertEqual(
                path.read_text(encoding="utf-8").count(
                    remote_access.LOCAL_SPEECH_PREF_MARKER),
                1,
            )

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

    def _on_client_left(self, client=None, **kwargs):
        if client:
            self.connected_clients.pop(client.get('id'), None)

    def _on_channel_joined(self, channel=None, **kwargs):
        log.info("Joined channel: %s" % channel)

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

    def test_v34_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            old = self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V34 + "\n"
            path.write_text(old, encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V34 + "\n", result)

    def test_v35_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            old = self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V35 + "\n"
            path.write_text(old, encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V35 + "\n", result)

    def test_v37_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            old = self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V37 + "\n"
            path.write_text(old, encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V37 + "\n", result)
            self.assertTrue(remote_access.legacy_controller_patch_current(result))

    def test_v36_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            old = self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V36 + "\n"
            path.write_text(old, encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V36 + "\n", result)
            self.assertTrue(remote_access.legacy_controller_patch_current(result))

    def test_v33_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            old = self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V33 + "\n"
            path.write_text(old, encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V33 + "\n", result)

    def test_v32_patch_is_replaced_from_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            old = self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V32 + "\n"
            path.write_text(old, encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V32 + "\n", result)

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

    def test_control_reset_invalidates_queued_local_machine_main_loop_work(self):
        c, _, _ = self._patched_controller()
        calls = []
        c.local_machine._linux_rdaccess_invalidate_pending = lambda: calls.append("invalidate")
        c._linux_rdaccess_reset_keys()
        self.assertEqual(calls, ["invalidate"])

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

    def test_controller_departure_releases_keys_while_relay_stays_connected(self):
        c, _, _ = self._patched_controller()
        c.connected_clients = {23: {'connection_type': 'master'}}
        self._key(c, 0xA2, True)
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x14, True)  # deferred, never injected
        c._on_client_left(client={'id': 23})
        keys = [e[:3] for e in c.local_machine.events if e[0] == 'key']
        self.assertEqual(keys, [('key', 0xA2, True), ('key', 0xA2, False)])
        self.assertTrue(c.transport.connected)
        self.assertEqual(c._lrd_down, set())
        self.assertEqual(c.connected_clients, {})

    def test_non_controller_departure_preserves_held_keys(self):
        c, _, _ = self._patched_controller()
        c.connected_clients = {23: {'connection_type': 'slave'}}
        self._key(c, 0xA2, True)
        c._on_client_left({'id': 23})
        self.assertEqual(c._lrd_down, {(0xA2, False)})
        self.assertEqual(c.connected_clients, {})

    def test_channel_join_never_logs_connection_key(self):
        c, _, _ = self._patched_controller()
        with mock.patch.object(c._module.log, 'info') as info:
            c._on_channel_joined(channel='private-channel-key')
        self.assertTrue(info.called)
        self.assertNotIn('private-channel-key', str(info.call_args_list))

    def test_orca42_fallback_passes_required_input_event(self):
        import sys, types
        c, _, _ = self._patched_controller()
        calls = []
        script = SimpleNamespace()
        for name in ('sayAll', 'presentTitle', 'presentStatusBar',
                     'togglePresentationMode'):
            # These signatures require inputEvent in actual ORCA_42_0 source.
            def handler(inputEvent, command=name):
                calls.append((command, inputEvent))
            setattr(script, name, handler)
        orca = types.ModuleType('orca')
        orca.orca_state = SimpleNamespace(activeScript=script)
        with mock.patch.dict(sys.modules, {'orca': orca,
                                          'linux_rdaccess_orca_adapter': None}):
            for name in ('sayAll', 'presentTitle', 'presentStatusBar',
                         'togglePresentationMode'):
                c._linux_rdaccess_script_call(name)
        self.assertEqual(calls, [(name, None) for name in
                                ('sayAll', 'presentTitle', 'presentStatusBar')]
                         + [('togglePresentationMode',
                             SimpleNamespace(type='keyboard', event_string='space'))])

    def test_pass_next_bypasses_translation_before_main_loop_runs(self):
        c, _, _ = self._patched_controller()
        queue = []
        c._linux_rdaccess_run_main = queue.append
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x71, True)
        self._key(c, 0x71, True)  # repeat must still be consumed
        self._key(c, 0x71, False)  # consumed F2 must not acquire a stray release
        self._key(c, 0x20, True)
        self._key(c, 0x20, False)
        keys = [e[:3] for e in c.local_machine.events if e[0] == 'key']
        self.assertEqual(keys, [('key', 0x20, True), ('key', 0x20, False)])
        self.assertFalse(c._lrd_bypass_next)
        # A later chord is translated again after the one bypassed command.
        self._key(c, 0x54, True)
        self.assertIn((0x54, False), c._lrd_swapped)

    def test_external_orca_bypass_prevents_remote_translation(self):
        import sys, types
        c, _, _ = self._patched_controller()
        orca = types.ModuleType('orca')
        orca.orca_state = SimpleNamespace(bypassNextCommand=True)
        with mock.patch.dict(sys.modules, {'orca': orca}):
            self._key(c, 0x14, True)
            self._key(c, 0x54, True)
            self._key(c, 0x54, False)
            self._key(c, 0x14, False)
        keys = [e[:3] for e in c.local_machine.events if e[0] == 'key']
        self.assertEqual(keys, [('key', 0x14, True), ('key', 0x54, True),
                                ('key', 0x54, False), ('key', 0x14, False)])

    def test_queued_orca_actions_and_speech_stops_expire_on_control_handoff(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        commands = []
        c._linux_rdaccess_script_call = lambda *args: commands.append(args)
        with patches:
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x54, True)  # queued stop + title
            self.assertTrue(c._lrd_local_stop_pending)
            c.toggle_control()
            self.assertFalse(c._lrd_local_stop_pending)
            # New session input must be able to queue its own stop/action.
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x09, True)
            for callback in queue:
                self.assertFalse(callback())
        self.assertEqual(commands, [('whereAmI',)])
        self.assertEqual([e for e in c.local_machine.events if e[0] == 'cancel'],
                         [('cancel',)])

    def test_braille_and_keyboard_callbacks_share_initial_session(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        commands = []
        c._linux_rdaccess_script_call = lambda *args: commands.append(args)
        with patches:
            c._on_remote_braille_input(
                scriptPath=['globalCommands', 'GlobalCommands', 'braille_scrollBack'])
            self._key(c, 0x09, True)
            for callback in queue:
                self.assertFalse(callback())
        self.assertEqual(commands, [('panBrailleLeft',)])

    def test_elements_list_prefers_native_orca_list_without_synthetic_keys(self):
        import sys
        import types

        c, _, _ = self._patched_controller()
        module = types.ModuleType("linux_rdaccess_orca_adapter")

        class Adapter:
            @staticmethod
            def show_structural_list(key):
                return key == "m"

        module.OrcaRuntimeAdapter = Adapter
        c._linux_rdaccess_send_structural_list = lambda *args: self.fail(
            "synthetic key fallback must not run"
        )
        with mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": module}):
            c._linux_rdaccess_open_structural_list("m", None)

    def test_elements_list_cancel_does_not_open_headings_fallback(self):
        import sys
        import types

        c, _, _ = self._patched_controller()
        module = types.ModuleType("linux_rdaccess_orca_adapter")
        module.show_elements_list = lambda callback: False
        calls = []
        c._linux_rdaccess_send_structural_list = lambda key, modifiers: calls.append(key)
        with mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": module}):
            c._linux_rdaccess_show_elements_list(None)
        self.assertEqual(calls, [])

    def test_elements_list_unavailable_uses_headings_fallback(self):
        import sys
        import types

        c, _, _ = self._patched_controller()
        module = types.ModuleType("linux_rdaccess_orca_adapter")
        module.show_elements_list = lambda callback: None
        calls = []
        c._linux_rdaccess_send_structural_list = lambda key, modifiers: calls.append(key)
        with mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": module}):
            c._linux_rdaccess_show_elements_list(None)
        self.assertEqual(calls, ["h"])

    def test_elements_list_injects_real_alt_shift_modifiers(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_send_structural_list("m", None)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertEqual(keys, [
            ("key", 0xA0, True),
            ("key", 0xA4, True),
            ("key", 0x4D, True),
            ("key", 0x4D, False),
            ("key", 0xA4, False),
            ("key", 0xA0, False),
        ])

    def test_structural_list_retries_failed_synthetic_modifier_release(self):
        c, _, _ = self._patched_controller()
        backend = c.local_machine.send_key
        failed = {"done": False}
        releases = []

        def flaky_send(**payload):
            if payload.get("vk_code") == 0xA4 and not payload.get("pressed"):
                releases.append(payload["vk_code"])
                if not failed["done"]:
                    failed["done"] = True
                    return False
            return backend(**payload)

        c.local_machine.send_key = flaky_send
        c._linux_rdaccess_send_structural_list("m", None)
        self.assertEqual(releases, [0xA4, 0xA4])
        self.assertNotIn((0xA4, False), c._lrd_forwarded)
        self.assertEqual(c._lrd_forwarded, {})

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

    def test_nvda_space_calls_orca_presentation_toggle_once_and_consumes_repeat(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True)
            self._key(c, 0x20, True)
            self._key(c, 0x20, True)      # auto-repeat must not toggle again
            self._key(c, 0x20, False)
        self.assertEqual(calls, [("presentation", SimpleNamespace(type='keyboard', event_string='space'))])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x20], [])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x41], [])

    def test_plain_space_then_insert_does_not_leave_space_stuck(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x20, True)      # normal Space, forwarded
        self._key(c, 0x2D, True)      # Insert pressed while Space held
        self._key(c, 0x20, False)     # release must be forwarded
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertIn(("key", 0x20, True), keys)
        self.assertIn(("key", 0x20, False), keys)

    def test_stale_nvda_modifier_is_released_when_control_changes(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True)      # Insert down, release never arrives
        c.toggle_control()            # reset must synthesize the lost key-up
        c.toggle_control()
        self._key(c, 0x20, True)
        self._key(c, 0x20, False)
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertFalse(any(k[1] == 0x2D for k in keys))
        self.assertIn(("key", 0x20, True), keys)
        self.assertFalse(any(k[1] == 0x41 for k in keys))

    def test_reset_releases_forwarded_arrow_but_not_consumed_chord_key(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x28, True, extended=True)     # ordinary Down forwarded
        c.toggle_control()
        keys = [e[:3] for e in c.local_machine.events if e[0] == "key"]
        self.assertIn(("key", 0x28, False), keys)

        c2, _, _ = self._patched_controller()
        self._key(c2, 0x2D, True)                   # NVDA
        self._key(c2, 0x20, True)                   # NVDA+Space consumed/replaced
        c2.toggle_control()
        keys2 = [e[:3] for e in c2.local_machine.events if e[0] == "key"]
        self.assertNotIn(("key", 0x20, False), keys2)
        self.assertFalse(any(k[1] == 0x2D for k in keys2))

    def test_zero_valued_braille_input_is_still_redacted(self):
        c, _, _ = self._patched_controller()
        action, record = c._linux_rdaccess_classify_braille({
            "id": "br(test):space",
            "dots": 0,
            "space": False,
            "identifiers": ["br(test):space"],
        })
        self.assertEqual(action, "keyboard")
        self.assertEqual(record["redacted"], "braille-keyboard-input")
        self.assertNotIn("id", record)
        self.assertNotIn("identifiers", record)

    def test_braille_trace_is_disabled_without_explicit_opt_in(self):
        import os
        c, _, home = self._patched_controller()
        env = {k: v for k, v in os.environ.items() if k != "LINUX_RDACCESS_BRAILLE_TRACE"}
        env["HOME"] = home
        with mock.patch.dict(os.environ, env, clear=True):
            Path(home, ".local/share/orca").mkdir(parents=True)
            c._on_remote_braille_input(
                id="br(test):backward",
                scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"],
            )
            self.assertFalse(
                Path(home, ".local/share/orca/orca-remote-braille-input.log").exists()
            )

    def test_braille_trace_is_private_bounded_and_redacts_typed_input(self):
        import os
        c, _, home = self._patched_controller()
        with mock.patch.dict(
            os.environ,
            {"HOME": home, "LINUX_RDACCESS_BRAILLE_TRACE": "1"},
            clear=True,
        ):
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
        nav = SimpleNamespace(
            toggleStructuralNavigation=lambda script_obj, ev=None: calls.append(("structural", ev)),
        )
        script = SimpleNamespace(
            panBrailleLeft=lambda ev=None: calls.append(("left", ev)),
            panBrailleRight=lambda ev=None: calls.append(("right", ev)),
            processRoutingKey=lambda ev=None: calls.append(("route", ev.event["argument"])),
            goBrailleHome=lambda ev=None: calls.append(("focus", ev)),
            bypassNextCommand=lambda ev=None: calls.append(("bypass", ev)),
            # Required inputEvent parameters match actual Orca 42 source.
            whereAmIBasic=lambda ev: calls.append(("where", ev)),
            presentTitle=lambda ev: calls.append(("title", ev)),
            presentStatusBar=lambda ev: calls.append(("status", ev)),
            sayAll=lambda ev: calls.append(("sayAll", ev)),
            togglePresentationMode=lambda ev: calls.append(("presentation", ev)),
            structuralNavigation=nav,
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

    def test_braille_to_focus_uses_orca_home_semantics(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(
                scriptPath=["globalCommands", "GlobalCommands", "braille_toFocus"])
        self.assertEqual(calls, [("focus", None)])

    def test_braille_routing_key_reaches_script_with_cell_argument(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"], routingIndex=7)
            for bad in (-1, 5000, True, "3", None):
                c._on_remote_braille_input(scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"], routingIndex=bad)
        self.assertEqual(calls, [("route", 7)])

    def test_braille_routing_without_script_metadata_is_not_dropped(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(routingIndex=4)
            c._on_remote_braille_input(cellIndexes=[6])
        self.assertEqual(calls, [("route", 4), ("route", 6)])

    def test_other_braille_cell_commands_are_not_reinterpreted_as_routing(self):
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches:
            for name in ('braille_reportFormatting', 'braille_selectRange',
                         'custom_route_action'):
                c._on_remote_braille_input(
                    scriptPath=['globalCommands', 'GlobalCommands', name],
                    routingIndex=7, cellIndexes=[7])
        self.assertEqual(calls, [])

    def test_braille_keyboard_script_metadata_is_redacted_without_dot_fields(self):
        c, _, _ = self._patched_controller()
        for name in ('kb:a', 'kb:control+a', 'braille_dots', 'script_braille_dots'):
            action, record = c._linux_rdaccess_classify_braille({
                'scriptPath': ['globalCommands', 'GlobalCommands', name],
                'id': 'driver-key', 'routingIndex': 2})
            self.assertEqual(action, 'keyboard')
            self.assertEqual(record.get('redacted'), 'braille-keyboard-input')
            self.assertNotIn('scriptPath', record)
            self.assertNotIn('id', record)

    def test_conflicting_or_ambiguous_routing_fields_are_rejected(self):
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches:
            for cells in ([1, 2], [2], [], [True], '1'):
                c._on_remote_braille_input(
                    scriptPath=['globalCommands', 'GlobalCommands', 'braille_routeTo'],
                    routingIndex=1, cellIndexes=cells)
            c._on_remote_braille_input(routingIndex=1, cellIndexes=[1])
        self.assertEqual(calls, [('route', 1)])

    def test_modern_nvda_single_cell_indexes_route_when_legacy_field_is_absent(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(
                scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"],
                cellIndexes=[9],
            )
            c._on_remote_braille_input(
                scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"],
                cellIndexes=[1, 2],
            )
        self.assertEqual(calls, [("route", 9)])

    # Real NVDA payloads: BrailleInputGesture declares class-level dots=0 and
    # space=False, and NVDA Remote adds both with hasattr(), so *every* gesture
    # from a display whose gesture class inherits it (Eurobraille, Handy Tech,
    # Freedom Scientific, HIMS...) carries them, including pan and routing keys.
    def test_dotpad_pan_ids_are_not_mistaken_for_typed_braille(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(
                id="br(dotPad):panLeft",
                identifiers=["br(dotPad):panLeft"],
                dots=0,
                space=False,
                scriptPath=["globalCommands", "GlobalCommands", "braille_scrollBack"],
            )
            c._on_remote_braille_input(
                id="br(dotPad):panRight",
                identifiers=["br(dotPad):panRight"],
                dots=0,
                space=False,
                scriptPath=["globalCommands", "GlobalCommands", "braille_scrollForward"],
            )
        self.assertEqual(calls, [("left", None), ("right", None)])

    def test_eurobraille_pan_keys_with_zero_dots_and_space_still_pan(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            for script in ("braille_scrollBack", "braille_scrollForward"):
                c._on_remote_braille_input(
                    id="backward" if script.endswith("Back") else "forward",
                    model="bnote", source="eurobraille", dots=0, space=False,
                    scriptPath=["globalCommands", "GlobalCommands", script])
        self.assertEqual(calls, [("left", None), ("right", None)])

    def test_eurobraille_routing_with_zero_dots_and_space_still_routes(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(
                id="routing", model="bnote", source="eurobraille",
                dots=0, space=False, cellIndexes=[5], routingIndex=5,
                scriptPath=["globalCommands", "GlobalCommands", "braille_routeTo"])
        self.assertEqual(calls, [("route", 5)])

    def test_zero_dots_display_gesture_is_traced_as_a_display_gesture(self):
        c, _, _ = self._patched_controller()
        action, record = c._linux_rdaccess_classify_braille({
            "id": "backward", "model": "bnote", "source": "eurobraille",
            "dots": 0, "space": False,
            "scriptPath": ["globalCommands", "GlobalCommands", "braille_scrollBack"],
        })
        self.assertEqual(action, "pan_back")
        self.assertNotIn("redacted", record)
        self.assertNotIn("dots", record)
        self.assertNotIn("space", record)

    def test_space_only_typed_braille_stays_redacted_even_as_an_integer_flag(self):
        # Eurobraille reports a lone braille-keyboard space as 0x200, dots 0.
        c, _, _ = self._patched_controller()
        action, record = c._linux_rdaccess_classify_braille({
            "id": "space", "model": "bnote", "source": "eurobraille",
            "dots": 0, "space": 0x200,
        })
        self.assertEqual(action, "keyboard")
        self.assertEqual(record["redacted"], "braille-keyboard-input")
        self.assertNotIn("id", record)

    def test_backspace_key_name_is_not_mistaken_for_typed_space(self):
        c, _, _ = self._patched_controller()
        action, _ = c._linux_rdaccess_classify_braille({
            "id": "backSpace", "dots": 0, "space": False,
        })
        self.assertNotEqual(action, "keyboard")

    # Display navigation keys (arrows, Enter, Tab, Escape ...) are bound by NVDA
    # to "kb:<key>" scripts and arrive with scriptPath [..., "kb:upArrow"]. They
    # type no characters, so they must reach Linux; character keys must not.
    def _braille_keys(self, c, home, **payload):
        import os
        calls, patches = self._with_fake_orca(c, home)
        c.local_machine.events.clear()
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            c._on_remote_braille_input(**payload)
        return [e[1:] for e in c.local_machine.events if e[0] == "key"]

    def test_display_arrow_key_is_forwarded_to_linux(self):
        c, _, home = self._patched_controller()
        keys = self._braille_keys(
            c, home, id="joystickUp", model="bnote", source="eurobraille",
            dots=0, space=False,
            scriptPath=["globalCommands", "GlobalCommands", "kb:upArrow"])
        self.assertEqual(keys, [(0x26, True, "Up"), (0x26, False, "Up")])

    def test_display_modified_key_presses_and_releases_modifiers_around_key(self):
        c, _, home = self._patched_controller()
        keys = self._braille_keys(
            c, home, id="chord", scriptPath=["globalCommands", "GlobalCommands", "kb:shift+tab"])
        self.assertEqual(keys, [
            (0xA0, True, "Shift_L"), (0x09, True, "Tab"),
            (0x09, False, "Tab"), (0xA0, False, "Shift_L")])

    def test_braille_key_retries_failed_synthetic_modifier_release(self):
        c, _, home = self._patched_controller()
        backend = c.local_machine.send_key
        failed = {"done": False}
        releases = []

        def flaky_send(**payload):
            if payload.get("vk_code") == 0xA0 and not payload.get("pressed"):
                releases.append(payload["vk_code"])
                if not failed["done"]:
                    failed["done"] = True
                    return False
            return backend(**payload)

        c.local_machine.send_key = flaky_send
        self._braille_keys(
            c, home, id="chord",
            scriptPath=["globalCommands", "GlobalCommands", "kb:shift+tab"])
        self.assertEqual(releases, [0xA0, 0xA0])
        self.assertNotIn((0xA0, False), c._lrd_forwarded)
        self.assertEqual(c._lrd_forwarded, {})

    def test_display_space_dot_chord_bound_to_a_command_key_is_forwarded(self):
        # space+dots chords are how many displays emit Escape/Enter/arrows.
        c, _, home = self._patched_controller()
        keys = self._braille_keys(
            c, home, id="space+dot1", dots=1, space=True,
            scriptPath=["globalCommands", "GlobalCommands", "kb:escape"])
        self.assertEqual(keys, [(0x1B, True, "Escape"), (0x1B, False, "Escape")])

    def test_display_character_keys_are_never_forwarded_or_traced(self):
        import os
        c, _, home = self._patched_controller()
        for name in ("kb:a", "kb:control+a", "kb:space", "kb:literal-password",
                     "kb:shift+a", "kb:control+control+tab", "kb:", "kb:windows+tab"):
            with self.subTest(name=name):
                keys = self._braille_keys(
                    c, home, scriptPath=["globalCommands", "GlobalCommands", name])
                self.assertEqual(keys, [])
        action, record = c._linux_rdaccess_classify_braille({
            "scriptPath": ["globalCommands", "GlobalCommands", "kb:a"]})
        self.assertEqual(action, "keyboard")
        self.assertEqual(record, {"redacted": "braille-keyboard-input"})

    def test_display_key_from_unexpected_script_location_is_not_forwarded(self):
        c, _, home = self._patched_controller()
        keys = self._braille_keys(
            c, home, scriptPath=["someAddon", "Commands", "kb:upArrow"])
        self.assertEqual(keys, [])

    def test_display_key_does_not_release_a_modifier_the_controller_holds(self):
        c, _, home = self._patched_controller()
        self._key(c, 0xA0, True)  # Windows Shift is physically held
        c.local_machine.events.clear()
        keys = self._braille_keys(
            c, home, scriptPath=["globalCommands", "GlobalCommands", "kb:shift+downArrow"])
        self.assertEqual(keys, [(0x28, True, "Down"), (0x28, False, "Down")])

    def test_display_key_is_traced_without_character_content(self):
        import os
        c, _, home = self._patched_controller()
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_BRAILLE_TRACE": "1"}):
            self._braille_keys(
                c, home, id="joystickUp",
                scriptPath=["globalCommands", "GlobalCommands", "kb:upArrow"])
        text = Path(home, ".local/share/orca/orca-remote-braille-input.log").read_text()
        self.assertNotIn("joystickUp", text)

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

    def test_nvda_tab_invokes_where_am_i_without_keypad_modifier_translation(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x09, True)
            self._key(c, 0x09, False)
        self.assertEqual(calls, [("where", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x09], [])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x0D], [])

    def test_capslock_nvda_tab_is_modifier_layout_independent(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0x09, True)
            self._key(c, 0x09, False)
        self.assertEqual(calls, [("where", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

    def test_nvda_input_help_uses_orca_learn_mode_instead_of_bookmark_key(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
        c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x31, True)
        self._key(c, 0x31, True)   # auto-repeat must remain consumed
        self._key(c, 0x31, False)
        self.assertEqual(calls, ["toggleInputHelp"])
        self.assertNotIn((0x31, True), self._names(c))

    def test_nvda_u_cycles_orca_progress_output_once(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
        c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x55, True)
        self._key(c, 0x55, True)
        self._key(c, 0x55, False)
        self.assertEqual(calls, ["cycleProgressBarOutput"])
        self.assertNotIn((0x55, True), self._names(c))

    def test_nvda_m_toggles_orca_mouse_review_in_both_layouts(self):
        import os
        for layout in ("desktop", "laptop"):
            with self.subTest(layout=layout):
                c, _, _ = self._patched_controller()
                calls = []
                c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
                c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    self._key(c, 0x2D, True, extended=True)
                    self._key(c, 0x4D, True)
                    self._key(c, 0x4D, True)
                    self._key(c, 0x4D, False)
                self.assertEqual(calls, ["toggleMouseReview"])
                self.assertNotIn((0x4D, True), self._names(c))

    def test_nvda_p_cycles_orca_punctuation_in_desktop_and_laptop_layouts(self):
        import os
        for layout in ("desktop", "laptop"):
            with self.subTest(layout=layout):
                c, _, _ = self._patched_controller()
                calls = []
                c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
                c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    self._key(c, 0x2D, True, extended=True)
                    self._key(c, 0x50, True)
                    self._key(c, 0x50, True)  # repeat is consumed without cycling again
                    self._key(c, 0x50, False)
                self.assertEqual(calls, ["cycleSpeakingPunctuationLevel"])
                self.assertNotIn((0x50, True), self._names(c))

    def test_unmapped_nvda_commands_do_not_fall_through_to_orca_bookmarks_or_silence(self):
        for vk, shift in (
            (0x32, False), (0x33, False), (0x34, False),
            (0x35, False), (0x36, False), (0x37, False),  # NVDA+2..7 settings
            (0x42, False), (0x42, True),   # NVDA+B / NVDA+Shift+B vs bookmarks
            (0x46, False),                 # NVDA+F formatting vs Orca char attrs
            (0x4B, False),                 # NVDA+K link URL vs Orca laptop review item
            (0x4D, False),                 # NVDA+M mouse tracking vs Orca laptop review char
            (0x50, False),                 # NVDA+P symbol level vs Orca laptop flat review
            (0x53, False),                 # NVDA+S vs Orca speech silence
            (0x55, False),                 # NVDA+U progress reporting vs Orca laptop review line
        ):
            with self.subTest(vk=vk, shift=shift):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                if shift:
                    self._key(c, 0xA0, True)
                self._key(c, vk, True)
                self._key(c, vk, True)
                self._key(c, vk, False)
                self.assertNotIn((vk, True), self._names(c))

    def test_unimplemented_nvda_table_reading_commands_do_not_reach_linux(self):
        for vk in (0x25, 0x26, 0x27, 0x28):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0xA2, True)
                self._key(c, 0xA4, True)
                self._key(c, vk, True, extended=True)
                self._key(c, vk, False, extended=True)
                self.assertNotIn((vk, True), self._names(c))

    def test_unimplemented_nvda_ctrl_settings_and_tools_do_not_reach_linux_apps(self):
        # NVDA 2026.2 global settings/tools commands. Until a proven Orca-42
        # equivalent exists, these must not become application Ctrl shortcuts.
        for vk in (0x47, 0x53, 0x56, 0x41, 0x55, 0x4B, 0x4D, 0x4F,
                   0x42, 0x44, 0x57, 0x43, 0x52, 0x5A, 0x54, 0x50):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0xA2, True)
                self._key(c, vk, True)
                self._key(c, vk, False)
                self.assertNotIn((vk, True), self._names(c))

    def test_desktop_nvda_review_page_commands_do_not_reach_linux(self):
        import os
        for vk in (0x21, 0x22):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "desktop"}):
                    self._key(c, 0x2D, True, extended=True)
                    self._key(c, vk, True, extended=True)
                    self._key(c, vk, False, extended=True)
                self.assertNotIn((vk, True), self._names(c))

    def test_nvda_selection_and_location_commands_do_not_fall_through(self):
        cases = (
            # vk, shift, ctrl, alt, extended, layout
            (0x24, False, False, True,  True,  "desktop"), # NVDA+Alt+Home selection start
            (0x23, False, False, True,  True,  "desktop"), # NVDA+Alt+End selection end
            (0x26, True,  False, False, True,  "desktop"), # NVDA+Shift+Up current selection
            (0x53, True,  False, False, False, "laptop"),  # NVDA+Shift+S current selection
            (0xBE, True,  True,  False, False, "laptop"),  # NVDA+Ctrl+Shift+. focus accelerator
        )
        for vk, shift, ctrl, alt, extended, layout in cases:
            with self.subTest(vk=vk, layout=layout):
                c, _, _ = self._patched_controller()
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    self._key(c, 0x2D, True, extended=True)
                    if shift:
                        self._key(c, 0xA0, True)
                    if ctrl:
                        self._key(c, 0xA2, True)
                    if alt:
                        self._key(c, 0xA4, True)
                    self._key(c, vk, True, extended=extended)
                    self._key(c, vk, False, extended=extended)
                self.assertNotIn((vk, True), self._names(c))

    def test_remaining_documented_nvda_global_commands_do_not_leak_to_linux(self):
        cases = (
            # vk, shift, ctrl, alt, extended, layout
            (0x44, True,  False, False, False, "desktop"), # NVDA+Shift+D audio ducking
            (0x53, True,  False, False, False, "desktop"), # desktop NVDA+Shift+S sleep
            (0x5A, True,  False, False, False, "laptop"),  # laptop NVDA+Shift+Z sleep
            (0x26, False, True,  False, True,  "desktop"), # synth ring
            (0x28, False, True,  False, True,  "desktop"),
            (0x25, False, True,  False, True,  "desktop"),
            (0x27, False, True,  False, True,  "desktop"),
            (0x21, False, True,  False, True,  "desktop"),
            (0x22, False, True,  False, True,  "desktop"),
            (0x26, True,  True,  False, True,  "laptop"),
            (0x28, True,  True,  False, True,  "laptop"),
            (0x25, True,  True,  False, True,  "laptop"),
            (0x27, True,  True,  False, True,  "laptop"),
            (0x21, True,  True,  False, True,  "laptop"),
            (0x22, True,  True,  False, True,  "laptop"),
            (0x4B, False, False, True,  False, "desktop"), # braille auto scroll
            (0x4C, False, False, True,  False, "desktop"),
            (0x4A, False, False, True,  False, "desktop"),
            (0x46, True,  False, False, False, "desktop"), # review formatting
            (0x44, False, False, False, False, "desktop"), # annotation summary
            (0x54, False, False, True,  False, "desktop"), # braille mode
            (0x4D, False, False, True,  False, "desktop"), # math interaction
            (0x71, False, True,  False, False, "desktop"), # NVDA+Ctrl+F2 display model
            (0x63, False, False, False, False, "desktop"), # NVDA+Numpad3 flattened next
            (0x69, False, False, False, False, "desktop"), # NVDA+Numpad9 flattened previous
            (0xDB, True,  False, False, False, "laptop"),  # Shift+NVDA+[ previous in flow
            (0xDD, True,  False, False, False, "laptop"),  # Shift+NVDA+] next in flow
        )
        for vk, shift, ctrl, alt, extended, layout in cases:
            with self.subTest(vk=vk, shift=shift, ctrl=ctrl, alt=alt, layout=layout):
                c, _, _ = self._patched_controller()
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": layout}):
                    self._key(c, 0x2D, True, extended=True)
                    if shift:
                        self._key(c, 0xA0, True)
                    if ctrl:
                        self._key(c, 0xA2, True)
                    if alt:
                        self._key(c, 0xA4, True)
                    self._key(c, vk, True, extended=extended)
                    self._key(c, vk, False, extended=extended)
                self.assertNotIn((vk, True), self._names(c))

    def test_other_documented_unimplemented_nvda_commands_do_not_reach_linux_apps(self):
        # Representative NVDA 2026.2 global commands which linux-rdaccess does
        # not yet emulate. They must not become ordinary Linux app shortcuts.
        cases = (
            (0x51, False, False, False, False),  # NVDA+Q quit NVDA
            (0x43, False, False, False, False),  # NVDA+C clipboard report
            (0x52, False, False, False, False),  # NVDA+R OCR
            (0x58, False, False, False, False),  # NVDA+X repeat last speech
            (0x78, False, False, False, False),  # NVDA+F9 mark review start
            (0x78, True,  False, False, False),  # NVDA+Shift+F9
            (0x79, False, False, False, False),  # NVDA+F10 review copy
            (0x72, False, True,  False, False),  # NVDA+Ctrl+F3 reload plugins
            (0x1B, False, True,  False, False),  # NVDA+Ctrl+Escape screen curtain
            (0x57, True,  False, False, False),  # NVDA+Shift+W magnifier
            (0xBB, True,  False, False, False),  # NVDA+Shift+= zoom in
            (0xBD, True,  False, False, False),  # NVDA+Shift+- zoom out
            (0x49, True,  False, False, False),  # NVDA+Shift+I filter
            (0x4C, True,  False, False, False),  # NVDA+Shift+L overview
            (0x53, False, False, True,  False),  # NVDA+Alt+S sound split
            (0x52, False, False, True,  False),  # NVDA+Alt+R remote connect
            (0x09, False, False, True,  False),  # NVDA+Alt+Tab remote-control toggle
            (0x25, False, False, True,  True),   # NVDA+Alt+Left magnifier pan
            (0x27, False, False, True,  True),
            (0x26, False, False, True,  True),
            (0x28, False, False, True,  True),
            (0x25, True,  False, True,  True),   # NVDA+Shift+Alt+Arrow edge pan
            (0x27, True,  False, True,  True),
            (0x26, True,  False, True,  True),
            (0x28, True,  False, True,  True),
            (0x54, False, True,  True,  False),  # NVDA+Ctrl+Alt+T
            (0x70, False, False, False, False),  # NVDA+F1 developer info
            (0x70, False, True,  False, False),  # NVDA+Ctrl+F1 speech mode/settings
            (0x70, True,  True,  False, False),  # NVDA+Ctrl+Shift+F1
        )
        for vk, shift, ctrl, alt, extended in cases:
            with self.subTest(vk=vk, shift=shift, ctrl=ctrl, alt=alt):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                if shift:
                    self._key(c, 0xA0, True)
                if ctrl:
                    self._key(c, 0xA2, True)
                if alt:
                    self._key(c, 0xA4, True)
                self._key(c, vk, True, extended=extended)
                self._key(c, vk, False, extended=extended)
                self.assertNotIn((vk, True), self._names(c))

    def test_nvda_ctrl_settings_chords_do_not_run_orca_laptop_review_commands(self):
        for vk in (0x55, 0x4B, 0x4D, 0x4F):  # U/K/M/O
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0xA2, True)
                self._key(c, vk, True)
                self._key(c, vk, True)
                self._key(c, vk, False)
                self.assertNotIn((vk, True), self._names(c))

    def test_nvda_ctrl_u_with_both_physical_ctrl_keys_is_still_consumed(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA2, True)
        self._key(c, 0xA3, True)
        self._key(c, 0x55, True)
        self._key(c, 0x55, False)
        self.assertNotIn((0x55, True), self._names(c))

    def test_nvda_shift_b_with_both_physical_shift_keys_is_still_consumed(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA0, True)
        self._key(c, 0xA1, True)
        self._key(c, 0x42, True)
        self._key(c, 0x42, True)   # repeat
        self._key(c, 0x42, False)
        self.assertNotIn((0x42, True), self._names(c))

    def test_nvda_ctrl_space_does_not_open_orca_app_preferences_or_toggle_caps(self):
        for nvda_vk, nvda_extended in ((0x2D, True), (0x14, False)):
            with self.subTest(nvda_vk=nvda_vk):
                c, _, _ = self._patched_controller()
                self._key(c, nvda_vk, True, extended=nvda_extended)
                self._key(c, 0xA2, True)
                self._key(c, 0x20, True)
                self._key(c, 0x20, True)
                self._key(c, 0x20, False)
                self._key(c, 0xA2, False)
                self._key(c, nvda_vk, False, extended=nvda_extended)
                names = self._names(c)
                self.assertNotIn((0x20, True), names)
                if nvda_vk == 0x14:
                    self.assertNotIn((0x14, True), names)

    def test_nvda_say_all_calls_orca_directly_and_consumes_repeat(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x28, True, extended=True)    # NVDA+Down
            self._key(c, 0x28, True, extended=True)    # auto-repeat consumed
            self._key(c, 0x28, False, extended=True)
        self.assertEqual(calls, [("sayAll", None)])
        self.assertEqual(self._names(c), [])

    def test_laptop_layout_uses_exact_caret_reading_aliases(self):
        import os
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
        c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "laptop"}):
            self._key(c, 0x2D, True, extended=True)   # NVDA
            self._key(c, 0x41, True); self._key(c, 0x41, False)  # NVDA+A: caret Say All
            self._key(c, 0x4C, True); self._key(c, 0x4C, False)  # NVDA+L: current line
            self._key(c, 0xA0, True)                 # Shift
            self._key(c, 0x23, True, extended=True)
            self._key(c, 0x23, False, extended=True) # NVDA+Shift+End: status
            self._key(c, 0xA0, False)
        self.assertEqual(calls, ["sayAll", "presentCurrentLine", "presentStatusBar"])
        names = self._names(c)
        self.assertNotIn((0x41, True), names)
        self.assertNotIn((0x4C, True), names)
        self.assertNotIn((0x23, True), names)

    def test_laptop_review_gestures_do_not_run_desktop_commands(self):
        import os
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
        c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "laptop"}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x26, True, extended=True)
            self._key(c, 0x26, False, extended=True) # NVDA+Up: review previous line
            self._key(c, 0x28, True, extended=True)
            self._key(c, 0x28, False, extended=True) # NVDA+Down: review next line
            self._key(c, 0x23, True, extended=True)
            self._key(c, 0x23, False, extended=True) # NVDA+End: review line end
        self.assertEqual(calls, [])
        names = self._names(c)
        self.assertNotIn((0x26, True), names)
        self.assertNotIn((0x28, True), names)
        self.assertNotIn((0x23, True), names)

    def test_laptop_unimplemented_nvda_object_review_commands_do_not_run_orca_commands(self):
        import os
        cases = (
            (0x0D, False, False),  # NVDA+Enter: activate navigator object, Orca+Return Where Am I
            (0x08, False, False),  # NVDA+Backspace: navigator to focus, Orca+Backspace bypass next
            (0x26, True, True),    # NVDA+Shift+Up: parent object, Orca+Shift+Up selection report
            (0x27, True, True),    # NVDA+Shift+Right: next object
            (0x25, True, True),    # NVDA+Shift+Left: previous object
            (0x28, True, True),    # NVDA+Shift+Down: first child
            (0x4F, True, False),   # NVDA+Shift+O: report navigator object
            (0x4D, True, False),   # NVDA+Shift+M: move mouse to navigator object
            (0x4E, True, False),   # NVDA+Shift+N: navigator object to mouse
            (0xDB, False, False),  # NVDA+[: left click, Orca find
            (0xDD, False, False),  # NVDA+]: right click, Orca find next
        )
        for vk, shift, extended in cases:
            with self.subTest(vk=vk, shift=shift):
                c, _, _ = self._patched_controller()
                calls = []
                c._linux_rdaccess_run_main = lambda func: (func(), True)[1]
                c._linux_rdaccess_script_call = lambda method, *args: calls.append(method) or True
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "laptop"}):
                    self._key(c, 0x2D, True, extended=True)
                    if shift:
                        self._key(c, 0xA0, True)
                    self._key(c, vk, True, extended=extended)
                    self._key(c, vk, False, extended=extended)
                self.assertEqual(calls, [])
                self.assertNotIn((vk, True), self._names(c))

    def test_laptop_ctrl_brackets_do_not_run_orca_find_commands(self):
        import os
        for vk in (0xDB, 0xDD):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "laptop"}):
                    self._key(c, 0x2D, True, extended=True)
                    self._key(c, 0xA2, True)
                    self._key(c, vk, True)
                    self._key(c, vk, False)
                self.assertNotIn((vk, True), self._names(c))

    def test_laptop_shift_page_review_commands_are_consumed(self):
        import os
        for vk in (0x21, 0x22):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_LAYOUT": "laptop"}):
                    self._key(c, 0x2D, True, extended=True)
                    self._key(c, 0xA0, True)
                    self._key(c, vk, True, extended=True)
                    self._key(c, vk, False, extended=True)
                self.assertNotIn((vk, True), self._names(c))

    def test_direct_say_all_does_not_swallow_nonextended_key_with_same_vk(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)      # NVDA
            self._key(c, 0x28, True, extended=True)     # NVDA+Down -> direct Say All
            self._key(c, 0x28, True, extended=False)    # keypad form: distinct physical key
            self._key(c, 0x28, False, extended=False)
            self._key(c, 0x28, False, extended=True)    # translated release consumed
        self.assertEqual(calls, [("sayAll", None)])
        names = self._names(c)
        self.assertEqual(names.count((0x28, True)), 1)
        self.assertEqual(names.count((0x28, False)), 1)
        self.assertNotIn((0x6B, True), names)

    def test_ambiguous_nonextended_arrow_payload_is_preserved(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x28, True, extended=True)    # no NVDA key: plain Down
        self._key(c, 0x28, False, extended=True)
        self._key(c, 0x2D, True, extended=True)
        # With no key_name/scan_code, non-extended VK_DOWN is not sufficient
        # proof that this was physical Numpad2 rather than a legacy nav payload.
        self._key(c, 0x28, True, extended=False)
        self._key(c, 0x28, False, extended=False)
        self.assertEqual(
            self._names(c),
            [(0x28, True), (0x28, False), (0x2D, True), (0x28, True), (0x28, False)],
        )

    def test_desktop_unimplemented_nvda_object_commands_do_not_run_orca_keypad_commands(self):
        cases = (
            (0x0C, False),  # NVDA+Numpad5 / VK_CLEAR
            (0x6D, False),  # NVDA+NumpadMinus: navigator to focus
            (0x6F, True),   # NVDA+NumpadDivide: mouse to navigator
            (0x6A, False),  # NVDA+NumpadMultiply: navigator to mouse
        )
        for vk, extended in cases:
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                self._key(c, vk, True, extended=extended)
                self._key(c, vk, False, extended=extended)
                self.assertNotIn((vk, True), self._names(c))

    def test_desktop_shift_numpad_object_commands_are_intercepted(self):
        for vk, extended in ((0x6D, False),):
            with self.subTest(vk=vk):
                c, _, _ = self._patched_controller()
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0xA0, True)
                self._key(c, vk, True, extended=extended)
                self._key(c, vk, False, extended=extended)
                self.assertNotIn((vk, True), self._names(c))

    def test_desktop_nvda_numpad_enter_does_not_run_orca_title_command(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x0D, True, extended=True)
        self._key(c, 0x0D, False, extended=True)
        self.assertNotIn((0x0D, True), self._names(c))

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

    def test_releasing_one_of_two_nvda_modifiers_keeps_the_other_active(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)      # Insert
            self._key(c, 0x14, True)                     # CapsLock
            self._key(c, 0x14, False)                    # release only CapsLock
            self._key(c, 0x20, True)                     # NVDA+Space still translates
        self.assertEqual(calls, [("presentation", SimpleNamespace(type='keyboard', event_string='space'))])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

    def test_say_all_with_both_nvda_modifiers_never_releases_either(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)                     # CapsLock first
            self._key(c, 0x2D, True, extended=True)      # Insert also held
            self._key(c, 0x28, True, extended=True)      # NVDA+Down
        self.assertEqual(calls, [("sayAll", None)])
        names = self._names(c)
        self.assertNotIn((0x2D, False), names)
        self.assertNotIn((0x14, False), names)
        self.assertNotIn((0x6B, True), names)

    def test_standalone_capslock_is_forwarded_as_one_press_release(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        self._key(c, 0x14, False)
        self.assertEqual(
            [k for k in self._names(c) if k[0] == 0x14],
            [(0x14, True), (0x14, False)],
        )

    def test_numlock_repeat_is_consumed_and_announced_once(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_read_lock_state = lambda vk: True
        presented = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: presented.append((method, args)) or True
        )
        self._key(c, 0x90, True)
        self._key(c, 0x90, True)   # Windows auto-repeat
        self._key(c, 0x90, True)   # another auto-repeat
        self.assertEqual(presented, [])  # XKB may not unlock before release
        self._key(c, 0x90, False)
        self.assertEqual(
            [k for k in self._names(c) if k[0] == 0x90],
            [(0x90, True), (0x90, False)],
        )
        self.assertEqual(presented, [("presentLockState", (0x90, True))])

    def test_scrolllock_repeat_is_consumed_and_announced_once(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_read_lock_state = lambda vk: True
        presented = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: presented.append((method, args)) or True
        )
        self._key(c, 0x91, True)
        self._key(c, 0x91, True)
        self._key(c, 0x91, True)
        self._key(c, 0x91, False)
        self.assertEqual(
            [k for k in self._names(c) if k[0] == 0x91],
            [(0x91, True), (0x91, False)],
        )
        self.assertEqual(presented, [("presentLockState", (0x91, True))])

    def test_fresh_numlock_presses_each_toggle_and_announce(self):
        c, _, _ = self._patched_controller()
        states = iter((True, False))
        c._linux_rdaccess_read_lock_state = lambda vk: next(states)
        presented = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: presented.append((method, args)) or True
        )
        for _ in range(2):
            self._key(c, 0x90, True)
            self._key(c, 0x90, False)
        self.assertEqual(
            [k for k in self._names(c) if k[0] == 0x90],
            [(0x90, True), (0x90, False), (0x90, True), (0x90, False)],
        )
        self.assertEqual(
            presented,
            [("presentLockState", (0x90, True)), ("presentLockState", (0x90, False))],
        )

    def test_failed_numlock_injection_never_announces(self):
        c, _, _ = self._patched_controller()
        presented = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: presented.append((method, args)) or True
        )
        c.local_machine.send_key = lambda **kwargs: False
        self._key(c, 0x90, True)
        self._key(c, 0x90, False)
        self.assertEqual(presented, [])

    def test_plain_capslock_announces_only_when_physical_toggle_is_forwarded(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_read_lock_state = lambda vk: True
        presented = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: presented.append((method, args)) or True
        )
        self._key(c, 0x14, True)
        self._key(c, 0x14, False)
        self.assertEqual(presented, [("presentLockState", (0x14, True))])

    def test_plain_capslock_preserves_original_remote_key_payload(self):
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_read_lock_state = lambda vk: True
        presented = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: presented.append((method, args)) or True
        )
        c._on_remote_key(
            key_name="Caps_Lock", pressed=True, modifiers=7,
            vk_code=0x14, scan_code=58, extended=False,
        )
        c._on_remote_key(
            key_name="Caps_Lock", pressed=False, modifiers=7,
            vk_code=0x14, scan_code=58, extended=False,
        )
        caps = [event for event in c.local_machine.events
                if event[0] == "key" and event[1] == 0x14]
        self.assertEqual(
            caps,
            [("key", 0x14, True, "Caps_Lock"),
             ("key", 0x14, False, "Caps_Lock")],
        )
        self.assertEqual(presented, [("presentLockState", (0x14, True))])

    def test_capslock_used_as_nvda_modifier_does_not_announce_lock_state(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        presented = []
        original = c._linux_rdaccess_script_call

        def record(method, *args):
            if method == "presentLockState":
                presented.append((method, args))
                return True
            return original(method, *args)

        c._linux_rdaccess_script_call = record
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0x54, True)   # CapsLock+T
            self._key(c, 0x54, False)
            self._key(c, 0x14, False)
        self.assertEqual(calls, [("title", None)])
        self.assertEqual(presented, [])

    def test_capslock_nvda_modifier_is_never_forwarded_for_translated_command(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0x28, True, extended=True)
            self._key(c, 0x28, False, extended=True)
            self._key(c, 0x14, False)
        self.assertEqual(calls, [("sayAll", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

    def test_pending_capslock_is_not_released_on_reset_before_forwarding(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])
        c.toggle_control()
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

    def test_unhandled_capslock_chord_flushes_modifier_before_target_key(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        self._key(c, 0x74, True)   # CapsLock+F5 is not translated yet
        self._key(c, 0x74, False)
        self._key(c, 0x14, False)
        self.assertEqual(
            self._names(c),
            [(0x14, True), (0x74, True), (0x74, False), (0x14, False)],
        )

    def test_capslock_nvda_key_supports_direct_say_all_without_toggling_capslock(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0x28, True, extended=True)
            self._key(c, 0x28, False, extended=True)
            self._key(c, 0x20, True)                   # direct presentation toggle
        self._key(c, 0x14, False)
        self.assertEqual(calls, [("sayAll", None),
                                 ("presentation", SimpleNamespace(type='keyboard', event_string='space'))])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x28], [])

    def test_nvda_n_is_consumed_without_opening_unrelated_orca_preferences(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: calls.append((method, args)) or True
        )
        self._key(c, 0x2D, True, extended=True)  # Insert/NVDA
        self._key(c, 0x4E, True)                 # NVDA+N: NVDA menu
        self._key(c, 0x4E, False)
        self.assertEqual(calls, [])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x4E], [])

    def test_capslock_nvda_n_is_consumed_without_toggling_capslock(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: calls.append((method, args)) or True
        )
        self._key(c, 0x14, True)                 # CapsLock/NVDA
        self._key(c, 0x4E, True)
        self._key(c, 0x4E, False)
        self._key(c, 0x14, False)
        self.assertEqual(calls, [])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x4E], [])

    def test_plain_n_is_not_consumed_as_preferences(self):
        c, _, _ = self._patched_controller()
        calls = []
        c._linux_rdaccess_script_call = (
            lambda method, *args: calls.append((method, args)) or True
        )
        self._key(c, 0x4E, True)
        self._key(c, 0x4E, False)
        self.assertEqual(calls, [])
        self.assertEqual(
            [k for k in self._names(c) if k[0] == 0x4E],
            [(0x4E, True), (0x4E, False)],
        )

    def test_title_and_status_use_direct_orca_apis_without_keypad_sequences(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x54, True); self._key(c, 0x54, False)           # NVDA+T
            self._key(c, 0x23, True, extended=True); self._key(c, 0x23, False, extended=True)  # NVDA+End
        self.assertEqual(calls, [("title", None), ("status", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x0D], [])
        self.assertEqual([k for k in self._names(c) if k[0] in (0x54, 0x23)], [])

    def test_nonextended_end_with_nvda_is_not_mistaken_for_status_command(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x23, True, extended=False)
        self.assertEqual(calls, [])
        self.assertIn((0x23, True), self._names(c))

    def test_capslock_title_and_status_are_modifier_layout_independent(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0x54, True); self._key(c, 0x54, False)
            self._key(c, 0x23, True, extended=True); self._key(c, 0x23, False, extended=True)
            self._key(c, 0x14, False)
        self.assertEqual(calls, [("title", None), ("status", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

    def test_v46_patch_is_replaced_from_backup_with_braille_handoff_lock(self):
        c, path, _ = self._patched_controller()
        previous = path.read_text(encoding="utf-8").replace(
            remote_access.LEGACY_COMPAT_MARKER,
            remote_access.LEGACY_COMPAT_MARKER_V46,
        )
        # Recreate the ineffective v46 generated hook: braille input was not
        # included in the ownership-lock wrapper tuple.
        previous = previous.replace(
            'for _lrd_name in ("_on_remote_key", "_on_remote_braille_input",\n'
            '                  "_linux_rdaccess_reset_keys",\n'
            '                  "_linux_rdaccess_send_structural_list"):',
            'for _lrd_name in ("_on_remote_key", "_linux_rdaccess_reset_keys",\n'
            '                  "_linux_rdaccess_send_structural_list"):',
        )
        path.write_text(previous, encoding="utf-8")
        self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
        result = path.read_text(encoding="utf-8")
        self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
        self.assertIn(
            'for _lrd_name in ("_on_remote_key", "_on_remote_braille_input",',
            result,
        )
        self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))

    def test_v28_patch_is_upgraded_to_current(self):
        c, path, _ = self._patched_controller()
        previous = path.read_text(encoding='utf-8').replace(
            remote_access.LEGACY_COMPAT_MARKER, remote_access.LEGACY_COMPAT_MARKER_V28)
        path.write_text(previous, encoding='utf-8')
        self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
        result = path.read_text(encoding='utf-8')
        self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V28 + '\n', result)
        self.assertEqual(result.count('    def _linux_rdaccess_filter_key('), 1)
        self.assertIn('Joined remote channel', result)
        self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))

    def test_v27_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(
                self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V27 + "\n",
                encoding="utf-8",
            )
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_CONTROLLER, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V27 + "\n", result)

    def test_v26_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V26 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V26 + "\n", result)

    def test_v25_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V25 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V25 + "\n", result)

    def test_v24_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V24 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V24 + "\n", result)

    def test_v23_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V23 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V23 + "\n", result)

    def test_v22_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V22 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V22 + "\n", result)

    def test_v21_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V21 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V21 + "\n", result)

    def test_v20_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V20 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V20 + "\n", result)

    def test_v19_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V19 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V19 + "\n", result)

    def test_v18_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V18 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V18 + "\n", result)

    def test_v17_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V17 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V17 + "\n", result)

    def test_v16_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V16 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V16 + "\n", result)

    def test_v15_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V15 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V15 + "\n", result)

    def test_v14_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V14 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V14 + "\n", result)

    def test_v13_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V13 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V13 + "\n", result)

    def test_v12_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V12 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V12 + "\n", result)

    def test_v11_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V11 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V11 + "\n", result)

    def test_v10_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V10 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V10 + "\n", result)

    def test_v9_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V9 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V9 + "\n", result)

    def test_v8_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V8 + "\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, result)
            self.assertNotIn(remote_access.LEGACY_COMPAT_MARKER_V8 + "\n", result)

    def test_v2_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "remote_controller.py"
            path.write_text(self.UPSTREAM_CONTROLLER + "\n" + remote_access.LEGACY_COMPAT_MARKER_V1 + " v2\n", encoding="utf-8")
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(self.UPSTREAM_CONTROLLER, encoding="utf-8")
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, path.read_text(encoding="utf-8"))

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

    @staticmethod
    def _resolve_key(key_name, vk_code, extended):
        # Legacy resolver ignores extended for navigation/keypad VKs.
        if key_name:
            return key_name
        return {0x21: 'Prior', 0x22: 'Next', 0x23: 'End', 0x24: 'Home',
                0x25: 'Left', 0x26: 'Up', 0x27: 'Right', 0x28: 'Down',
                0x2D: 'Insert', 0x2E: 'Delete', 0x0C: None}.get(vk_code)
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

    def test_keypad_and_dedicated_navigation_keys_resolve_separately(self):
        module, _, _ = self._patched_local()
        resolve = module.LocalMachine._resolve_key
        for vk, name in ((0x21, 'Prior'), (0x22, 'Next'), (0x23, 'End'),
                         (0x24, 'Home'), (0x25, 'Left'), (0x26, 'Up'),
                         (0x27, 'Right'), (0x28, 'Down'), (0x2D, 'Insert'),
                         (0x2E, 'Delete')):
            with self.subTest(vk=vk):
                self.assertEqual(resolve(None, vk, False), 'KP_' + name)
                self.assertEqual(resolve(None, vk, True), name)
                # Older key-name peers and missing flags preserve priority.
                self.assertEqual(resolve(name, vk, False), name)
                self.assertEqual(resolve(None, vk, None), name)
        self.assertEqual(resolve(None, 0x0C, False), 'KP_Begin')

    def test_lock_vks_resolve_when_remote_key_name_is_missing(self):
        module, _, _ = self._patched_local()
        resolve = module.LocalMachine._resolve_key
        self.assertEqual(resolve(None, 0x14, False), 'Caps_Lock')
        self.assertEqual(resolve(None, 0x14, True), 'Caps_Lock')
        self.assertEqual(resolve(None, 0x90, False), 'Num_Lock')
        self.assertEqual(resolve(None, 0x90, True), 'Num_Lock')
        self.assertEqual(resolve(None, 0x91, False), 'Scroll_Lock')
        self.assertEqual(resolve(None, 0x91, True), 'Scroll_Lock')
        # An explicit peer-provided key name still has priority.
        self.assertEqual(resolve('PeerCaps', 0x14, False), 'PeerCaps')

    def test_local_machine_v11_patch_is_upgraded_to_current(self):
        module, path, _ = self._patched_local()
        path.write_text(path.read_text(encoding='utf-8').replace(
            remote_access.LOCAL_MACHINE_MARKER, remote_access.LOCAL_MACHINE_MARKER_V11),
            encoding='utf-8')
        self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
        result = path.read_text(encoding='utf-8')
        self.assertIn(remote_access.LOCAL_MACHINE_MARKER, result)
        self.assertNotIn(remote_access.LOCAL_MACHINE_MARKER_V11 + '\n', result)
        self.assertFalse(remote_access.patch_legacy_orca_local_machine(path))

    def test_local_machine_v5_patch_is_upgraded_to_current(self):
        module, path, _ = self._patched_local()
        path.write_text(path.read_text(encoding='utf-8').replace(
            remote_access.LOCAL_MACHINE_MARKER, remote_access.LOCAL_MACHINE_MARKER_V5),
            encoding='utf-8')
        self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
        result = path.read_text(encoding='utf-8')
        self.assertNotIn(remote_access.LOCAL_MACHINE_MARKER_V5 + '\n', result)
        self.assertEqual(result.count('class _LrdXTest:'), 1)
        self.assertFalse(remote_access.patch_legacy_orca_local_machine(path))

    def test_local_machine_v4_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local_machine.py"
            path.write_text(
                self.UPSTREAM_LOCAL + "\n" + remote_access.LOCAL_MACHINE_MARKER_V4 + "\n",
                encoding="utf-8",
            )
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_LOCAL, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LOCAL_MACHINE_MARKER, result)
            self.assertNotIn(remote_access.LOCAL_MACHINE_MARKER_V4 + "\n", result)

    def test_local_machine_v3_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local_machine.py"
            path.write_text(
                self.UPSTREAM_LOCAL + "\n" + remote_access.LOCAL_MACHINE_MARKER_V3 + "\n",
                encoding="utf-8",
            )
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_LOCAL, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LOCAL_MACHINE_MARKER, result)
            self.assertNotIn(remote_access.LOCAL_MACHINE_MARKER_V3 + "\n", result)

    def test_local_machine_v2_patch_is_upgraded_to_current(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local_machine.py"
            path.write_text(
                self.UPSTREAM_LOCAL + "\n" + remote_access.LOCAL_MACHINE_MARKER_V2 + "\n",
                encoding="utf-8",
            )
            path.with_name(path.name + ".linux-rdaccess-backup").write_text(
                self.UPSTREAM_LOCAL, encoding="utf-8"
            )
            self.assertTrue(remote_access.patch_legacy_orca_local_machine(path))
            result = path.read_text(encoding="utf-8")
            self.assertIn(remote_access.LOCAL_MACHINE_MARKER, result)
            self.assertNotIn(remote_access.LOCAL_MACHINE_MARKER_V2 + "\n", result)

    def test_xtest_re_resolves_keycode_after_keyboard_layout_change(self):
        module, _, _ = self._patched_local()
        calls = []

        class FakeX11:
            def __init__(self):
                self.codes = iter((38, 52))

            def XStringToKeysym(self, name):
                return 97

            def XKeysymToKeycode(self, display, sym):
                return next(self.codes)

            def XFlush(self, display):
                return 0

        class FakeXt:
            def XTestFakeKeyEvent(self, display, code, pressed, delay):
                calls.append((code, bool(pressed)))
                return 1

        helper = module._LrdXTest()
        helper._x11 = FakeX11()
        helper._xt = FakeXt()
        helper._dpy = object()

        # A layout change while the key is held must not move the release to
        # the new keycode. The next fresh press should use the new mapping.
        self.assertTrue(helper.key("a", True))
        self.assertTrue(helper.key("a", False))
        self.assertTrue(helper.key("a", True))
        self.assertTrue(helper.key("a", False))
        self.assertEqual(
            calls,
            [(38, True), (38, False), (52, True), (52, False)],
        )

    def test_non_ascii_fallback_does_not_disable_xtest_for_later_keys(self):
        module, _, _ = self._patched_local()
        calls = []

        class FakeX11:
            def XStringToKeysym(self, name):
                return 1

            def XKeysymToKeycode(self, display, sym):
                return 42

            def XFlush(self, display):
                return 0

        class FakeXt:
            def XTestFakeKeyEvent(self, display, code, pressed, delay):
                calls.append((code, bool(pressed)))
                return 1

        helper = module._LrdXTest()
        helper._x11 = FakeX11()
        helper._xt = FakeXt()
        helper._dpy = object()
        self.assertFalse(helper.key("é", True))
        self.assertFalse(helper._failed)
        self.assertTrue(helper.key("Down", True))
        self.assertEqual(calls, [(42, True)])

    def test_xtest_failed_release_forgets_held_mapping_before_fallback(self):
        module, _, _ = self._patched_local()
        calls = []

        class FakeX11:
            def __init__(self):
                self.codes = iter((38, 52))

            def XStringToKeysym(self, name):
                return 97

            def XKeysymToKeycode(self, display, sym):
                return next(self.codes)

            def XFlush(self, display):
                return 0

        class FakeXt:
            def __init__(self):
                self.results = iter((1, 0, 1))

            def XTestFakeKeyEvent(self, display, code, pressed, delay):
                calls.append((code, bool(pressed)))
                return next(self.results)

        helper = module._LrdXTest()
        helper._x11 = FakeX11()
        helper._xt = FakeXt()
        helper._dpy = object()

        self.assertTrue(helper.key("a", True))
        self.assertFalse(helper.key("a", False))  # fallback handles this release
        self.assertNotIn("a", helper._down_codes)
        self.assertTrue(helper.key("a", True))
        self.assertEqual(calls, [(38, True), (38, False), (52, True)])

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

    def test_per_keypress_debug_log_stays_disabled_when_debugging(self):
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
            module._dbg("key=SECRET")
        self.assertFalse(log.exists())

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
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_DEBUG": "1"}):
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
        glib = SimpleNamespace(idle_add=lambda fn: queue.append(fn))
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

    def test_queued_clipboard_write_is_discarded_after_generation_invalidation(self):
        import threading
        module, _, _ = self._patched_local()
        queue, patches = self._fake_glib()
        machine = module.LocalMachine()
        with patches:
            worker = threading.Thread(
                target=lambda: machine.set_clipboard_text(text="stale"), name="net")
            worker.start()
            worker.join()
            self.assertEqual(len(queue), 1)
            machine._linux_rdaccess_invalidate_pending()
            queue.pop()()
        self.assertEqual(module.LocalMachine.clip_threads, [])

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
    A_CODE, F_CODE, M_CODE, N_CODE, O_CODE, W_CODE, D_CODE = 38, 41, 58, 57, 32, 25, 40
    LEFT, RIGHT, UP, DOWN = 113, 114, 111, 116
    KP_DOWN = 88

    def _orca_env(self, browse=True, in_document=True):
        """Fake Orca 42 pieces with the same shouldConsume order as the real one."""
        import sys, types
        test = self
        # This fixture is reused by tests/test_pass_next.py; keep added browse
        # keycodes self-contained instead of requiring every borrowing class
        # to duplicate these constants.
        a_code = getattr(self, "A_CODE", 38)
        f_code = getattr(self, "F_CODE", 41)
        n_code = getattr(self, "N_CODE", 57)
        o_code = getattr(self, "O_CODE", 32)
        w_code = getattr(self, "W_CODE", 25)
        f10_code = getattr(self, "F10_CODE", 76)
        kb = types.ModuleType("orca.keybindings")
        kb.SHIFT_MODIFIER_MASK, kb.CTRL_MODIFIER_MASK = self.SHIFT, self.CTRL
        kb.ALT_MODIFIER_MASK, kb.ORCA_MODIFIER_MASK = self.ALT, self.ORCA
        kb.getKeycode = lambda key: {
            "a": a_code, "f": f_code, "m": self.M_CODE, "n": n_code,
            "o": o_code, "w": w_code, "d": self.D_CODE,
            "7": 17, "8": 18, "9": 19,
            "Home": 110, "End": 115, "Page_Up": 112, "Page_Down": 117,
            "F3": 69, "F10": 76, "v": 55,
            "Left": self.LEFT, "Right": self.RIGHT,
            "Up": self.UP, "Down": self.DOWN, "F10": 76,
        }.get(key)

        landmark_next = SimpleNamespace(function="landmark_next")
        landmark_prev = SimpleNamespace(function="landmark_prev")
        live_region = SimpleNamespace(function="live_region")
        clickable_next = SimpleNamespace(function="clickable_next")
        clickable_prev = SimpleNamespace(function="clickable_prev")
        chunk_next = SimpleNamespace(function="chunk_next")
        chunk_prev = SimpleNamespace(function="chunk_prev")
        cell_left = SimpleNamespace(function="cell_left")
        cell_right = SimpleNamespace(function="cell_right")
        cell_up = SimpleNamespace(function="cell_up")
        cell_down = SimpleNamespace(function="cell_down")
        other_nav = SimpleNamespace(function="other_nav")
        verbosity = SimpleNamespace(function="verbosity")
        form_calls = []
        form_field = SimpleNamespace(
            goNext=lambda script, event: form_calls.append("next"),
            goPrevious=lambda script, event: form_calls.append("previous"),
            functions=[],
        )
        heading_calls = []
        heading = SimpleNamespace(
            goNextAtLevelFactory=lambda level: (
                lambda script, event: heading_calls.append(("next", level))),
            goPreviousAtLevelFactory=lambda level: (
                lambda script, event: heading_calls.append(("previous", level))),
            functions=[],
        )

        class Bindings:
            table = {
                (test.M_CODE, 0): landmark_next,
                (test.M_CODE, test.SHIFT): landmark_prev,
                (test.D_CODE, 0): live_region,
                (test.D_CODE, test.SHIFT): live_region,
                # These are intentionally different from NVDA browse-mode
                # semantics: A=annotation there, O=embedded object there.
                (a_code, 0): clickable_next,
                (a_code, test.SHIFT): clickable_prev,
                (o_code, 0): chunk_next,
                (o_code, test.SHIFT): chunk_prev,
                # Orca 42 binds table cell navigation to Shift+Alt+Arrow.
                (test.LEFT, test.SHIFT | test.ALT): cell_left,
                (test.RIGHT, test.SHIFT | test.ALT): cell_right,
                (test.UP, test.SHIFT | test.ALT): cell_up,
                (test.DOWN, test.SHIFT | test.ALT): cell_down,
                # An unrelated structural command on the same chord shape.
                (test.KP_DOWN, test.SHIFT | test.ALT): other_nav,
                (55, test.ORCA): verbosity,
            }

            def getInputHandler(self, event):
                # Orca keybindings match the full modifier state, not just Shift.
                return self.table.get((event.hw_code, event.modifiers))

        class Script:
            keyBindings = Bindings()
            structuralNavigation = SimpleNamespace(
                functions=["landmark_next", "landmark_prev", "cell_left",
                           "cell_right", "cell_up", "cell_down", "other_nav"],
                enabledObjects={"tableCell": SimpleNamespace(
                    functions=["cell_left", "cell_right", "cell_up", "cell_down"])})
            state = {"browse": browse}

            def useStructuralNavigationModel(self):
                return self.state["browse"]

        script = Script()
        script.structuralNavigation.enabledObjects["formField"] = form_field
        script.structuralNavigation.enabledObjects["heading"] = heading
        script.form_calls = form_calls
        script.heading_calls = heading_calls
        script.layout_calls = []
        script.toggleLayoutMode = lambda event=None: script.layout_calls.append("toggle")
        script.table_edge_calls = []
        script.utilities = types.SimpleNamespace(
            getCaretContext=lambda: ("caret", 0),
            rowAndColumnCount=lambda table, include_layout: (5, 6),
        )
        script.structuralNavigation.getCellForObj = lambda obj: "cell"
        script.structuralNavigation.getCellCoordinates = (
            lambda cell, prefer_attribute=False: [2, 3])
        script.structuralNavigation.getTableForCell = lambda cell: "table"
        script.structuralNavigation.goCell = (
            lambda cell_object, cell, current, desired:
                script.table_edge_calls.append(tuple(desired)))
        script.find_calls = []
        script.findNext = lambda event=None: script.find_calls.append("next")
        script.findPrevious = lambda event=None: script.find_calls.append("previous")
        script.inputEventHandlers = {
            "findHandler": SimpleNamespace(
                function=lambda script_arg, event=None: script.find_calls.append("find"))
        }
        script.layout_calls = []
        script.toggleLayoutMode = lambda event: script.layout_calls.append("toggle")
        script.utilities = SimpleNamespace(
            inDocumentContent=lambda obj=None: in_document,
        )

        class KeyboardEvent:
            def __init__(self, string, hw_code, modifiers=0, pressed=True):
                self.event_string, self.hw_code = string, hw_code
                self.modifiers, self._pressed, self._script = modifiers, pressed, script
                self._handler = None
                self._consumer = None
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

    def _hooked(self, browse=True, in_document=True):
        c, _, _ = self._patched_controller()
        KeyboardEvent, script, patches = self._orca_env(browse, in_document)
        patches.start()
        self.addCleanup(patches.stop)
        self.assertTrue(c._module._lrd_install_orca_hook())
        return c, KeyboardEvent, script

    def _remote_d(self, c, shift=False):
        if shift:
            self._key(c, 0xA0, True)
        self._key(c, 0x44, True)

    @staticmethod
    def _expire_navigation_markers(marker):
        marker["pending"][:] = [(timestamp - 5.0, key, identity)
                                for timestamp, key, identity in marker["pending"]]

    def _remote_browse_letter(self, c, vk, shift=False):
        if shift:
            self._key(c, 0xA0, True)
        self._key(c, vk, True)

    def _remote_browse_command(self, c, vk, *, shift=False, alt=False, extended=False, nvda=False):
        if nvda:
            self._key(c, 0x2D, True, extended=True)
        if shift:
            self._key(c, 0xA0, True)
        if alt:
            self._key(c, 0xA4, True)
        self._key(c, vk, True, extended=extended)

    def test_remote_mismatched_browse_letters_are_consumed_not_misrouted(self):
        cases = (
            ("a", self.A_CODE, 0x41),
            ("f", self.F_CODE, 0x46),
            ("m", self.M_CODE, 0x4D),
            ("n", self.N_CODE, 0x4E),
            ("o", self.O_CODE, 0x4F),
            ("w", self.W_CODE, 0x57),
        )
        for letter, code, vk in cases:
            for shift in (False, True):
                with self.subTest(letter=letter, shift=shift):
                    c, KE, _ = self._hooked()
                    self._remote_browse_letter(c, vk, shift=shift)
                    ev = KE(letter.upper() if shift else letter, code,
                            modifiers=self.SHIFT if shift else 0)
                    self.assertIsNotNone(
                        getattr(ev, "_consumer", None),
                        "remote mismatched NVDA browse command must be consumed",
                    )
                    self.assertIsNone(ev._handler)

    def test_remote_f_uses_native_orca_form_field_navigation(self):
        for shift, expected in ((False, "next"), (True, "previous")):
            with self.subTest(shift=shift):
                c, KE, script = self._hooked()
                self._remote_browse_letter(c, 0x46, shift=shift)
                ev = KE("F" if shift else "f", self.F_CODE,
                        modifiers=self.SHIFT if shift else 0)
                consumer = getattr(ev, "_consumer", None)
                self.assertIsNotNone(consumer)
                consumer(ev)
                self.assertEqual(script.form_calls, [expected])

    def test_remote_heading_levels_7_to_9_use_native_orca_heading_factories(self):
        for level, vk, code in ((7, 0x37, 17), (8, 0x38, 18), (9, 0x39, 19)):
            for shift, direction in ((False, "next"), (True, "previous")):
                with self.subTest(level=level, shift=shift):
                    c, KE, script = self._hooked()
                    if shift:
                        self._key(c, 0xA0, True)
                    self._key(c, vk, True)
                    ev = KE(str(level), code, modifiers=self.SHIFT if shift else 0)
                    consumer = getattr(ev, "_consumer", None)
                    self.assertIsNotNone(consumer)
                    consumer(ev)
                    self.assertEqual(script.heading_calls, [(direction, level)])

    def test_remote_nvda_v_works_in_document_focus_mode_without_orca_verbosity(self):
        for browse in (True, False):
            with self.subTest(browse=browse):
                c, KE, script = self._hooked(browse=browse, in_document=True)
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0x56, True)
                ev = KE("v", 55, modifiers=self.ORCA)
                consumer = getattr(ev, "_consumer", None)
                self.assertIsNotNone(consumer)
                consumer(ev)
                self.assertEqual(script.layout_calls, ["toggle"])
                self.assertIsNone(ev._handler)

    def test_remote_nvda_v_in_browser_chrome_never_runs_orca_verbosity(self):
        c, KE, script = self._hooked(browse=False, in_document=False)
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x56, True)
        ev = KE("v", 55, modifiers=self.ORCA)
        self.assertIsNotNone(getattr(ev, "_consumer", None))
        self.assertIsNone(ev._handler)
        self.assertEqual(script.layout_calls, [])

    def test_caps_nvda_v_never_toggles_caps_while_browse_context_is_decided(self):
        c, KE, script = self._hooked(browse=True)
        self._key(c, 0x14, True)
        self._key(c, 0x56, True)
        ev = KE("v", 55)
        self.assertIsNotNone(getattr(ev, "_consumer", None))
        self._key(c, 0x56, False)
        self._key(c, 0x14, False)
        self.assertNotIn((0x14, True), self._names(c))

    def test_remote_nvda_shift_f10_is_consumed_in_document_browse_or_focus_mode(self):
        for browse in (True, False):
            with self.subTest(browse=browse):
                c, KE, _ = self._hooked(browse=browse, in_document=True)
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0xA0, True)
                self._key(c, 0x79, True)
                ev = KE("F10", 76, modifiers=self.SHIFT | self.ORCA)
                self.assertIsNotNone(getattr(ev, "_consumer", None))
                self.assertIsNone(ev._handler)

    def test_remote_nvda_ctrl_f_opens_orca_find_in_document_browse_or_focus_mode(self):
        for browse in (True, False):
            with self.subTest(browse=browse):
                c, KE, script = self._hooked(browse=browse, in_document=True)
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0xA2, True)
                self._key(c, 0x46, True)
                ev = KE("f", self.F_CODE, modifiers=self.ORCA | self.CTRL)
                consumer = getattr(ev, "_consumer", None)
                self.assertIsNotNone(consumer)
                consumer(ev)
                self.assertEqual(script.find_calls, ["find"])
                self.assertIsNone(ev._handler)

    def test_remote_nvda_ctrl_f_in_browser_chrome_does_not_open_app_find(self):
        c, KE, script = self._hooked(browse=False, in_document=False)
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0xA2, True)
        self._key(c, 0x46, True)
        ev = KE("f", self.F_CODE, modifiers=self.ORCA | self.CTRL)
        self.assertIsNotNone(getattr(ev, "_consumer", None))
        self.assertIsNone(ev._handler)
        self.assertEqual(script.find_calls, [])

    def test_remote_nvda_f3_find_commands_work_in_document_browse_or_focus_mode(self):
        for shift, expected in ((False, "next"), (True, "previous")):
            for browse in (True, False):
                with self.subTest(shift=shift, browse=browse):
                    c, KE, script = self._hooked(browse=browse, in_document=True)
                    self._key(c, 0x2D, True, extended=True)
                    if shift:
                        self._key(c, 0xA0, True)
                    self._key(c, 0x72, True)
                    mods = self.ORCA | (self.SHIFT if shift else 0)
                    ev = KE("F3", 69, modifiers=mods)
                    consumer = getattr(ev, "_consumer", None)
                    self.assertIsNotNone(consumer)
                    consumer(ev)
                    self.assertEqual(script.find_calls, [expected])

    def test_caps_nvda_f3_never_toggles_caps_during_browse_context_decision(self):
        c, KE, _ = self._hooked(browse=True)
        self._key(c, 0x14, True)
        self._key(c, 0x72, True)
        ev = KE("F3", 69)
        self.assertIsNotNone(getattr(ev, "_consumer", None))
        self._key(c, 0x72, False)
        self._key(c, 0x14, False)
        self.assertNotIn((0x14, True), self._names(c))

    def test_browse_only_nvda_modifier_commands_are_consumed_without_app_fallthrough(self):
        cases = (
            ("v", 0x56, 55, dict(nvda=True)),               # NVDA+V screen layout
            ("F10", 0x79, 76, dict(nvda=True, shift=True)), # NVDA+Shift+F10 native selection
        )
        for event_string, vk, code, kwargs in cases:
            for browse in (True, False):
                with self.subTest(event=event_string, browse=browse):
                    c, KE, _ = self._hooked(browse=browse)
                    self._remote_browse_command(c, vk, **kwargs)
                    modifiers = self.ORCA | (self.SHIFT if kwargs.get("shift") else 0)
                    ev = KE(event_string, code, modifiers=modifiers)
                    self.assertIsNotNone(getattr(ev, "_consumer", None))
                    self.assertIsNone(ev._handler)

    def test_alt_arrow_collapse_expand_is_consumed_only_in_browse_mode(self):
        for event_string, vk, code in (
            ("Up", 0x26, self.UP),
            ("Down", 0x28, self.DOWN),
        ):
            with self.subTest(event=event_string, browse=True):
                c, KE, _ = self._hooked(browse=True)
                self._remote_browse_command(c, vk, alt=True, extended=True)
                ev = KE(event_string, code, modifiers=self.ALT)
                self.assertIsNotNone(getattr(ev, "_consumer", None))
                self.assertIsNone(ev._handler)
            with self.subTest(event=event_string, browse=False):
                c, KE, _ = self._hooked(browse=False)
                self._remote_browse_command(c, vk, alt=True, extended=True)
                ev = KE(event_string, code, modifiers=self.ALT)
                self.assertIsNone(getattr(ev, "_consumer", None))

    def test_local_mismatched_browse_letters_are_never_suppressed(self):
        cases = (
            ("a", self.A_CODE),
            ("f", self.F_CODE),
            ("m", self.M_CODE),
            ("n", self.N_CODE),
            ("o", self.O_CODE),
            ("w", self.W_CODE),
        )
        for letter, code in cases:
            with self.subTest(letter=letter):
                _c, KE, _ = self._hooked()
                ev = KE(letter, code)
                self.assertIsNone(getattr(ev, "_consumer", None))

    def test_remote_mismatched_browse_letter_types_normally_in_focus_mode(self):
        c, KE, _ = self._hooked(browse=False)
        self._remote_browse_letter(c, 0x4E)  # N has no conflicting Orca handler.
        ev = KE("n", self.N_CODE)
        self.assertIsNone(getattr(ev, "_consumer", None))
        self.assertFalse(ev.consume)
        # The refused marker is consumed and cannot suppress a later local N.
        self.assertEqual(c._module._LRD_BROWSE_UNSUPPORTED["pending"], [])

    def test_suppressed_browse_letter_release_follows_press_decision(self):
        c, KE, script = self._hooked()
        self._remote_browse_letter(c, 0x4D)
        down = KE("m", self.M_CODE)
        self.assertIsNotNone(getattr(down, "_consumer", None))
        script.state["browse"] = False
        up = KE("m", self.M_CODE, pressed=False)
        self.assertIsNotNone(getattr(up, "_consumer", None))
        self.assertEqual(c._module._LRD_BROWSE_UNSUPPORTED["held"], {})

    def test_browse_suppression_state_is_cleared_on_control_reset(self):
        c, KE, _ = self._hooked()
        self._remote_browse_letter(c, 0x4D)
        self.assertTrue(c._module._LRD_BROWSE_UNSUPPORTED["pending"])
        c.toggle_control()
        self.assertEqual(c._module._LRD_BROWSE_UNSUPPORTED["pending"], [])
        self.assertEqual(c._module._LRD_BROWSE_UNSUPPORTED["held"], {})
        local = KE("m", self.M_CODE)
        self.assertIsNone(getattr(local, "_consumer", None))

    def test_queued_remote_d_presses_each_keep_their_landmark_marker(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        self._remote_d(c)
        for _ in range(2):
            self.assertEqual(KE("d", self.D_CODE)._handler.function, "landmark_next")
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_queued_ctrl_d_cannot_steal_a_later_plain_d_landmark_marker(self):
        c, KE, _ = self._hooked()
        self._key(c, 0xA2, True)
        self._key(c, 0x44, True)
        self._key(c, 0x44, False)
        self._key(c, 0xA2, False)
        self._remote_d(c)
        self.assertIsNone(KE("d", self.D_CODE, modifiers=self.CTRL)._handler)
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "landmark_next")
        self.assertEqual(c._module._LRD_D["pending"], [])

    def test_failed_d_injection_cannot_translate_a_later_local_d(self):
        for failure in (False, RuntimeError("synthetic backend failure")):
            with self.subTest(failure=type(failure).__name__):
                c, KE, _ = self._hooked()
                c.local_machine.send_key = mock.Mock(return_value=failure)
                if isinstance(failure, Exception):
                    c.local_machine.send_key.side_effect = failure
                self._remote_d(c)
                self.assertEqual(c._module._LRD_D["pending"], [])
                self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

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

    def test_remote_d_marker_is_cleared_on_control_reset(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        self.assertTrue(c._module._LRD_D["pending"])
        c.toggle_control()
        self.assertEqual(c._module._LRD_D["pending"], [])
        self.assertFalse(c._module._LRD_D["swapped"])
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")

    def test_stale_remote_marker_expires(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        self._expire_navigation_markers(c._module._LRD_D)
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

    def test_rejected_landmark_translation_restores_hw_code_and_modifiers(self):
        c, KE, script = self._hooked()
        script.structuralNavigation.functions = []  # M is no longer a structural command
        self._remote_d(c)
        ev = KE("d", self.D_CODE, modifiers=self.SHIFT)
        self.assertEqual(ev.hw_code, self.D_CODE)
        self.assertEqual(ev.modifiers, self.SHIFT)
        self.assertEqual(ev._handler.function, "live_region")

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
            c._module._lrd_publish_navigation_marker(c._module._LRD_D, "d")
            ev = KE("d", self.D_CODE, modifiers=mod)
            self.assertNotEqual(getattr(ev._handler, "function", None), "landmark_next", mod)
            self.assertEqual(ev.hw_code, self.D_CODE)
            c._module._lrd_clear_navigation_markers(c._module._LRD_D)
        # NVDA key held: remote side never marks the D
        c3, KE3, _ = self._hooked()
        self._key(c3, 0x2D, True)
        self._key(c3, 0x44, True)
        self.assertEqual(c3._module._LRD_D["pending"], [])
        self.assertEqual(KE3("d", self.D_CODE)._handler.function, "live_region")

    def test_remote_ctrl_d_does_not_mark_the_key(self):
        c, KE, _ = self._hooked()
        self._key(c, 0xA2, True)
        self._key(c, 0x44, True)
        self.assertEqual(c._module._LRD_D["pending"], [])

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

    def test_landmark_release_reuses_press_keycode_if_lookup_changes(self):
        c, KE, _ = self._hooked()
        import orca.keybindings as kb
        self._remote_d(c)
        press = KE("d", self.D_CODE)
        self.assertEqual(press._handler.function, "landmark_next")
        kb.getKeycode = lambda key: None
        rel = KE("d", self.D_CODE, pressed=False)
        self.assertEqual(rel._handler.function, "landmark_next")
        self.assertFalse(c._module._LRD_D["swapped"])
        self.assertIsNone(c._module._LRD_D["code"])

    def test_landmark_release_keeps_translated_identity_if_modifiers_change(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        KE("d", self.D_CODE)  # translated press -> M
        rel = KE("d", self.D_CODE, modifiers=self.CTRL, pressed=False)
        self.assertEqual(rel._handler.function, "landmark_next")
        self.assertEqual(rel.modifiers, self.CTRL)  # restored after Orca matched plain M-up
        self.assertFalse(c._module._LRD_D["swapped"])

    def test_landmark_release_keeps_translated_identity_if_browse_mode_changes(self):
        c, KE, script = self._hooked()
        self._remote_d(c)
        KE("d", self.D_CODE)  # translated press -> M
        script.state["browse"] = False
        rel = KE("d", self.D_CODE, pressed=False)
        self.assertEqual(rel._handler.function, "landmark_next")
        self.assertFalse(c._module._LRD_D["swapped"])

    def test_other_keys_pass_through_untouched(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        ev = KE("m", self.M_CODE)
        self.assertEqual(ev._handler.function, "landmark_next")
        self.assertEqual(ev.hw_code, self.M_CODE)

    # ---- NVDA table commands: Ctrl+Alt+Arrow -> Orca Shift+Alt+Arrow ------

    CTRL_ALT = CTRL | ALT
    LCTRL, LALT, LSHIFT, LWIN, INSERT = 0xA2, 0xA4, 0xA0, 0x5B, 0x2D
    ARROWS = ((0x25, "Left", LEFT, "cell_left"), (0x27, "Right", RIGHT, "cell_right"),
              (0x26, "Up", UP, "cell_up"), (0x28, "Down", DOWN, "cell_down"))

    def _remote_table_key(self, c, vk=0x28, extended=True, held=(0xA2, 0xA4)):
        for mod in held:
            self._key(c, mod, True)
        self._key(c, vk, True, extended=extended)

    def test_queued_different_table_arrows_each_keep_their_remote_marker(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c, 0x28)
        self._key(c, 0x27, True, extended=True)
        self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function,
                         "cell_down")
        self.assertEqual(KE("Right", self.RIGHT, modifiers=self.CTRL_ALT)._handler.function,
                         "cell_right")
        self.assertEqual(c._module._LRD_T["pending"], [])

    def test_queued_plain_arrow_cannot_steal_a_later_table_arrow_marker(self):
        c, KE, _ = self._hooked()
        self._key(c, 0x28, True, extended=True)
        self._key(c, 0x28, False, extended=True)
        self._remote_table_key(c)
        self.assertIsNone(KE("Down", self.DOWN)._handler)
        self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function,
                         "cell_down")
        self.assertEqual(c._module._LRD_T["pending"], [])

    def test_queued_table_arrow_repeats_each_keep_their_remote_marker(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        self._key(c, 0x28, True, extended=True)
        for _ in range(2):
            self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function,
                             "cell_down")
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_unrelated_local_arrow_cannot_take_remote_arrow_provenance(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        self.assertIsNone(KE("Right", self.RIGHT, modifiers=self.CTRL_ALT)._handler)
        self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function,
                         "cell_down")

    def test_failed_table_send_removes_only_its_own_token(self):
        for failure in (False, RuntimeError("synthetic backend failure")):
            with self.subTest(failure=type(failure).__name__):
                c, KE, _ = self._hooked()
                self._remote_table_key(c, 0x27)
                c.local_machine.send_key = mock.Mock(return_value=failure)
                if isinstance(failure, Exception):
                    c.local_machine.send_key.side_effect = failure
                self._key(c, 0x28, True, extended=True)
                self.assertEqual([token[1] for token in c._module._LRD_T["pending"]], ["Right"])
                self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)
                self.assertEqual(KE("Right", self.RIGHT, modifiers=self.CTRL_ALT)._handler.function,
                                 "cell_right")

    def test_failed_repeat_preserves_an_earlier_successful_same_key_token(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        c.local_machine.send_key = mock.Mock(return_value=False)
        self._key(c, 0x28, True, extended=True)
        self.assertEqual(len(c._module._LRD_T["pending"]), 1)
        self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function,
                         "cell_down")
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_marker_exists_when_injection_dispatches_before_backend_returns(self):
        for kind in ("landmark", "table"):
            with self.subTest(kind=kind):
                c, KE, _ = self._hooked()
                handlers = []

                def dispatch(**payload):
                    if payload["vk_code"] == 0x44:
                        handlers.append(KE("d", self.D_CODE)._handler.function)
                    elif payload["vk_code"] == 0x28:
                        handlers.append(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function)
                    return True

                c.local_machine.send_key = dispatch
                if kind == "landmark":
                    self._remote_d(c)
                    self.assertEqual(handlers, ["landmark_next"])
                else:
                    self._remote_table_key(c)
                    self.assertEqual(handlers, ["cell_down"])

    def test_pending_navigation_tokens_are_bounded_and_expire_as_a_group(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        for _ in range(c._module._LRD_NAV_MAX_PENDING + 4):
            self._key(c, 0x28, True, extended=True)
        self.assertEqual(len(c._module._LRD_T["pending"]), c._module._LRD_NAV_MAX_PENDING)
        self._expire_navigation_markers(c._module._LRD_T)
        self._key(c, 0x27, True, extended=True)
        self.assertEqual([token[1] for token in c._module._LRD_T["pending"]], ["Right"])
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)
        self.assertEqual(KE("Right", self.RIGHT, modifiers=self.CTRL_ALT)._handler.function,
                         "cell_right")

    def test_transport_reconnect_discards_all_pending_navigation_tokens(self):
        c, KE, _ = self._hooked()
        self._remote_d(c)
        self._remote_table_key(c)
        c.transport = self.FakeTransport()
        c._linux_rdaccess_sync_state()
        self.assertEqual(c._module._LRD_D["pending"], [])
        self.assertEqual(c._module._LRD_T["pending"], [])
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "live_region")
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_remote_ctrl_alt_arrows_become_orca_table_cell_navigation(self):
        for vk, name, code, handler in self.ARROWS:
            with self.subTest(arrow=name):
                c, KE, _ = self._hooked()
                self._remote_table_key(c, vk)
                ev = KE(name, code, modifiers=self.CTRL_ALT)
                self.assertTrue(ev.consume)
                self.assertEqual(ev._handler.function, handler)
                self.assertEqual(ev.modifiers, self.CTRL_ALT)   # real chord restored
                self.assertEqual(ev.hw_code, code)

    def test_lock_state_bits_do_not_block_translation(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        ev = KE("Down", self.DOWN, modifiers=self.CTRL_ALT | 16)   # Num Lock bit
        self.assertEqual(ev.modifiers, self.CTRL_ALT | 16)

    def test_arrow_without_the_remote_marker_is_never_translated(self):
        c, KE, _ = self._hooked()
        ev = KE("Down", self.DOWN, modifiers=self.CTRL_ALT)       # local keyboard
        self.assertIsNone(ev._handler)

    def test_focus_mode_or_non_document_keeps_ctrl_alt_arrow(self):
        c, KE, script = self._hooked(browse=False)
        self._remote_table_key(c)
        ev = KE("Down", self.DOWN, modifiers=self.CTRL_ALT)
        self.assertIsNone(ev._handler)
        self.assertEqual(ev.modifiers, self.CTRL_ALT)
        # The refused marker must not tag a later local chord.
        script.state["browse"] = True
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_only_exact_ctrl_alt_is_translated(self):
        for mods in (self.CTRL, self.ALT, self.CTRL_ALT | self.SHIFT,
                     self.CTRL_ALT | self.ORCA, 0):
            with self.subTest(mods=mods):
                c, KE, _ = self._hooked()
                c._module._lrd_publish_navigation_marker(c._module._LRD_T, "Down")
                ev = KE("Down", self.DOWN, modifiers=mods)
                self.assertNotEqual(getattr(ev._handler, "function", None), "cell_down")
                self.assertEqual(ev.modifiers, mods)

    def test_remote_marker_requires_extended_arrow_with_only_ctrl_and_alt(self):
        cases = {
            "keypad arrow": dict(extended=False),
            "ctrl only": dict(held=(0xA2,)),
            "alt only": dict(held=(0xA4,)),
            "shift": dict(held=(0xA2, 0xA4, 0xA0)),
            "win": dict(held=(0xA2, 0xA4, 0x5B)),
            "insert nvda key": dict(held=(0x2D, 0xA2, 0xA4)),
            "capslock nvda key": dict(held=(0x14, 0xA2, 0xA4)),
            "non arrow": dict(vk=0x41),
        }
        for label, kwargs in cases.items():
            with self.subTest(case=label):
                c, KE, _ = self._hooked()
                self._remote_table_key(c, **kwargs)
                self.assertEqual(c._module._LRD_T["pending"], [])

    def test_release_follows_the_translated_press_even_if_modifiers_or_mode_change(self):
        c, KE, script = self._hooked()
        self._remote_table_key(c)
        press = KE("Down", self.DOWN, modifiers=self.CTRL_ALT)
        self.assertEqual(press._handler.function, "cell_down")
        script.state["browse"] = False                    # mode changed while held
        release = KE("Down", self.DOWN, modifiers=self.ALT, pressed=False)   # Ctrl up first
        self.assertEqual(release._handler.function, "cell_down")
        self.assertEqual(release.modifiers, self.ALT)     # restored afterwards
        again = KE("Down", self.DOWN, modifiers=self.ALT, pressed=False)
        self.assertIsNone(again._handler)                 # state cleared
        self.assertEqual(c._module._LRD_T["held"], {})

    def test_other_key_releases_never_inherit_the_table_translation(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        KE("Down", self.DOWN, modifiers=self.CTRL_ALT)
        other = KE("Left", self.LEFT, modifiers=self.ALT, pressed=False)
        self.assertIsNone(other._handler)
        self.assertIn(self.DOWN, c._module._LRD_T["held"])   # Down's release still pending

    def test_stray_release_does_not_translate(self):
        c, KE, _ = self._hooked()
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.ALT, pressed=False)._handler)

    def test_remote_table_edge_commands_preserve_row_or_column(self):
        cases = (
            ("firstRow", 0x21, "Page_Up", 112, [0, 3]),
            ("lastRow", 0x22, "Page_Down", 117, [4, 3]),
            ("firstColumn", 0x24, "Home", 110, [2, 0]),
            ("lastColumn", 0x23, "End", 115, [2, 5]),
        )
        for name, vk, event_name, code, expected in cases:
            with self.subTest(name=name):
                c, KE, script = self._hooked()
                cell, table, caret = object(), object(), object()
                calls = []
                nav = script.structuralNavigation
                nav.getCellForObj = lambda obj, cell=cell: cell
                nav.getCellCoordinates = lambda obj, prefer, cell=cell: [2, 3]
                nav.getTableForCell = lambda obj, table=table: table
                nav.goCell = lambda objtype, this, current, desired: calls.append(
                    (this, list(current), list(desired)))
                script.utilities = SimpleNamespace(
                    getCaretContext=lambda: (caret, 0),
                    rowAndColumnCount=lambda obj, prefer: (5, 6),
                )
                self._key(c, 0xA2, True)
                self._key(c, 0xA4, True)
                self._key(c, vk, True, extended=True)
                ev = KE(event_name, code, modifiers=self.CTRL | self.ALT)
                consumer = getattr(ev, "_consumer", None)
                self.assertIsNotNone(consumer)
                consumer(ev)
                self.assertEqual(calls, [(cell, [2, 3], expected)])

    def test_table_edge_rechecks_caret_when_delayed_consumer_runs(self):
        c, KE, script = self._hooked()
        old_cell, new_cell, table = object(), object(), object()
        old_caret, new_caret = object(), object()
        state = {"caret": old_caret}
        calls = []
        nav = script.structuralNavigation

        def cell_for(obj):
            return old_cell if obj is old_caret else new_cell

        def coords(cell, prefer):
            return [1, 1] if cell is old_cell else [3, 4]

        nav.getCellForObj = cell_for
        nav.getCellCoordinates = coords
        nav.getTableForCell = lambda cell: table
        nav.goCell = lambda objtype, this, current, desired: calls.append(
            (this, list(current), list(desired)))
        script.utilities = SimpleNamespace(
            getCaretContext=lambda: (state["caret"], 0),
            rowAndColumnCount=lambda obj, prefer: (6, 7),
            inDocumentContent=lambda obj=None: True,
        )

        self._key(c, 0xA2, True)
        self._key(c, 0xA4, True)
        self._key(c, 0x23, True, extended=True)  # Ctrl+Alt+End
        ev = KE("End", 115, modifiers=self.CTRL | self.ALT)
        consumer = getattr(ev, "_consumer", None)
        self.assertIsNotNone(consumer)

        # Orca schedules consumers after shouldConsume(). A focus/caret event
        # may arrive in that interval; navigation must use the new context.
        state["caret"] = new_caret
        consumer(ev)
        self.assertEqual(calls, [(new_cell, [3, 4], [3, 6])])

    def test_remote_table_edge_command_outside_table_is_not_consumed(self):
        c, KE, script = self._hooked()
        nav = script.structuralNavigation
        nav.getCellForObj = lambda obj: None
        script.utilities = SimpleNamespace(getCaretContext=lambda: (object(), 0))
        self._key(c, 0xA2, True)
        self._key(c, 0xA4, True)
        self._key(c, 0x21, True, extended=True)
        ev = KE("Page_Up", 112, modifiers=self.CTRL | self.ALT)
        self.assertIsNone(getattr(ev, "_consumer", None))
        self.assertFalse(ev.consume)

    def test_native_shift_alt_arrow_is_left_to_orca_untranslated(self):
        c, KE, _ = self._hooked()
        c._module._lrd_publish_navigation_marker(c._module._LRD_T, "Down")
        ev = KE("Down", self.DOWN, modifiers=self.SHIFT | self.ALT)
        self.assertEqual(ev._handler.function, "cell_down")     # Orca's own binding
        self.assertEqual(ev.modifiers, self.SHIFT | self.ALT)
        self.assertEqual(c._module._LRD_T["held"], {})

    def test_one_remote_arrow_marks_exactly_one_orca_arrow(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function, "cell_down")
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_stale_table_marker_expires_and_control_reset_clears_it(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        self._expire_navigation_markers(c._module._LRD_T)
        self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)
        c2, KE2, _ = self._hooked()
        self._remote_table_key(c2)
        self.assertTrue(c2._module._LRD_T["pending"])
        c2.toggle_control()
        self.assertEqual(c2._module._LRD_T["pending"], [])
        self.assertEqual(c2._module._LRD_T["held"], {})
        self.assertIsNone(KE2("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_only_orca_table_cell_handlers_are_accepted(self):
        c, KE, script = self._hooked()
        script.structuralNavigation.enabledObjects["tableCell"].functions = ["cell_up"]
        self._remote_table_key(c)
        ev = KE("Down", self.DOWN, modifiers=self.CTRL_ALT)   # Shift+Alt+Down is cell_down
        self.assertEqual(ev.modifiers, self.CTRL_ALT)
        self.assertIsNone(ev._handler)
        c3, KE3, script3 = self._hooked()
        del script3.structuralNavigation.enabledObjects["tableCell"]   # no table support
        self._remote_table_key(c3)
        self.assertIsNone(KE3("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)

    def test_keypad_arrow_is_never_translated(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        ev = KE("KP_Down", self.KP_DOWN, modifiers=self.CTRL_ALT)
        self.assertIsNone(ev._handler)

    def test_table_translation_can_be_disabled_and_errors_do_not_break_keys(self):
        c, KE, script = self._hooked()
        self._remote_table_key(c)
        with mock.patch.dict(os.environ, {"LINUX_RDACCESS_NVDA_TABLE_KEYS": "0"}):
            self.assertIsNone(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler)
        c2, KE2, script2 = self._hooked()
        script2.useStructuralNavigationModel = mock.Mock(side_effect=RuntimeError("secret"))
        self._remote_table_key(c2)
        ev = KE2("Down", self.DOWN, modifiers=self.CTRL_ALT)       # must not raise
        self.assertEqual(ev.modifiers, self.CTRL_ALT)

    def test_rolling_between_table_keys_keeps_each_release_translated(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c, 0x28)
        self.assertEqual(KE("Down", self.DOWN, modifiers=self.CTRL_ALT)._handler.function, "cell_down")
        self._key(c, 0x27, True, extended=True)           # Right pressed while Down is held
        self.assertEqual(KE("Right", self.RIGHT, modifiers=self.CTRL_ALT)._handler.function, "cell_right")
        down_up = KE("Down", self.DOWN, modifiers=self.CTRL_ALT, pressed=False)
        self.assertEqual(down_up._handler.function, "cell_down")      # was stranded before
        right_up = KE("Right", self.RIGHT, modifiers=self.CTRL_ALT, pressed=False)
        self.assertEqual(right_up._handler.function, "cell_right")
        self.assertEqual(c._module._LRD_T["held"], {})

    def test_untranslated_repeat_drops_the_earlier_translation_of_that_key(self):
        c, KE, script = self._hooked()
        self._remote_table_key(c)
        KE("Down", self.DOWN, modifiers=self.CTRL_ALT)
        script.state["browse"] = False                    # mode changes during auto-repeat
        self._key(c, 0x28, True, extended=True)
        KE("Down", self.DOWN, modifiers=self.CTRL_ALT)
        self.assertEqual(c._module._LRD_T["held"], {})

    def test_orca_lookup_failure_never_leaves_the_event_rewritten(self):
        def fail_once(script):
            real, calls = script.keyBindings.getInputHandler, []

            def lookup(event):
                calls.append(1)
                if len(calls) == 1:             # the hook's own lookup, after the rewrite
                    raise RuntimeError("secret")
                return real(event)
            script.keyBindings.getInputHandler = lookup
        c, KE, script = self._hooked()
        fail_once(script)
        self._remote_table_key(c)
        ev = KE("Down", self.DOWN, modifiers=self.CTRL_ALT)
        self.assertEqual(ev.modifiers, self.CTRL_ALT)
        self.assertEqual(c._module._LRD_T["held"], {})
        c2, KE2, script2 = self._hooked()
        fail_once(script2)
        self._remote_d(c2)
        ev2 = KE2("d", self.D_CODE, modifiers=self.SHIFT)
        self.assertEqual((ev2.hw_code, ev2.modifiers), (self.D_CODE, self.SHIFT))
        self.assertEqual(ev2._handler.function, "live_region")

    def test_remote_ctrl_alt_arrow_does_not_disturb_the_d_translation(self):
        c, KE, _ = self._hooked()
        self._remote_table_key(c)
        for vk, ext in ((0x28, True), (0xA2, False), (0xA4, False)):
            self._key(c, vk, False, extended=ext)
        c._module._lrd_clear_navigation_markers(c._module._LRD_T)
        self._remote_d(c)
        self.assertEqual(KE("d", self.D_CODE)._handler.function, "landmark_next")

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

    def test_nvda_shift_space_calls_structural_navigation_directly(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0xA0, True)
            self._key(c, 0x20, True)
        self.assertEqual(calls, [("structural", None)])
        self.assertEqual(self._names(c), [(0xA0, True)])

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

    def test_both_shift_keys_stay_physically_held_during_direct_structural_toggle(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0xA0, True)
            self._key(c, 0xA1, True)
            self._key(c, 0x20, True)
        self.assertEqual(calls, [("structural", None)])
        self.assertEqual(self._names(c), [(0xA0, True), (0xA1, True)])

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
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x20, True)
        self.assertEqual(calls, [("presentation", SimpleNamespace(type='keyboard', event_string='space'))])
        self.assertEqual(self._names(c), [])

    def test_shift_released_before_space_does_not_confuse_the_release(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0xA0, True)
            self._key(c, 0x20, True)
            self._key(c, 0xA0, False)
            self._key(c, 0x20, False)
        self.assertEqual(calls, [("structural", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x20], [])
        names = self._names(c)
        self.assertEqual(names.count((0xA0, True)), 1)
        self.assertEqual(names.count((0xA0, False)), 1)

    def test_nvda_f2_invokes_orca_bypass_directly_without_modifier_layout_dependency(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x71, True)
            self._key(c, 0x71, False)
        self.assertEqual(calls, [("bypass", None)])
        self.assertNotIn((0x08, True), self._names(c))
        self.assertNotIn((0x08, False), self._names(c))
        self.assertEqual([k for k in self._names(c) if k[0] == 0x71], [])

    def test_capslock_nvda_f2_does_not_require_capslock_to_be_orca_modifier(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0x71, True)
            self._key(c, 0x71, False)
        self.assertEqual(calls, [("bypass", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

    def test_plain_f2_and_shift_f2_rename_keys_are_untouched(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0x71, True); self._key(c, 0x71, False)          # Thunar F2 rename
        self._key(c, 0xA0, True); self._key(c, 0x71, True)
        self.assertEqual(self._names(c), [(0x71, True), (0x71, False), (0xA0, True), (0x71, True)])

    def test_capslock_as_nvda_key_still_gets_the_shift_space_chord(self):
        import os
        c, _, home = self._patched_controller()
        calls, patches = self._with_fake_orca(c, home)
        with patches, mock.patch.dict(os.environ, {"HOME": home}):
            self._key(c, 0x14, True)
            self._key(c, 0xA0, True)
            self._key(c, 0x20, True)
        self.assertEqual(calls, [("structural", None)])
        self.assertEqual([k for k in self._names(c) if k[0] == 0x14], [])

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
