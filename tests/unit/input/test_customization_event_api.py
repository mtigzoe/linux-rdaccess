"""Exercise the frozen legacy process wrapper with both Orca event APIs."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest import mock

import remote_access
from tests import test_remote_access as fixtures


UPSTREAM = (Path(__file__).resolve().parents[2] / 'fixtures/legacy-patches/customization-keyboard-hook.txt').read_text()


class CustomizationEventApiTests(unittest.TestCase):
    def patched(self):
        native, forwarded, shortcuts = [], [], []
        namespace = {
            '_original_process_key': lambda event: native.append(event) or 'native-result',
            '_dbg': lambda *args: None,
            '_direct_shortcut_keys_down': set(),
            '_forwarded_keys_down': set(),
            '_get_remote_shortcut_match': lambda event: None,
            '_get_effective_modifiers': lambda event: event.modifiers,
            '_release_all_forwarded_keys': lambda: None,
            '_key_to_vk': lambda name: {'Up': (0x26, 72, True), 'Down': (0x28, 80, True)}.get(name),
            'keybindings': SimpleNamespace(ORCA_MODIFIER_MASK=256, ALT_MODIFIER_MASK=8),
            'controller': SimpleNamespace(
                controlling_remote=False,
                transport=SimpleNamespace(connected=True, send=lambda **kw: forwarded.append(kw))),
        }
        text = remote_access._patch_legacy_customization_event_api(UPSTREAM)
        exec(compile(text, '<legacy-keyboard-hook>', 'exec'), namespace)
        return namespace, native, forwarded, shortcuts

    def event(self, api, *, pressed=True, name='Down'):
        event = SimpleNamespace(id=65364 if name == 'Down' else 65362,
                                hw_code=116 if name == 'Down' else 111,
                                keyval_name=name, modifiers=0)
        setattr(event, 'isPressedKey' if api == 'camel' else 'is_pressed_key', lambda: pressed)
        return event

    def no_marker(self):
        module = ModuleType('local_machine')
        module.is_injected_event = lambda *args: False
        return mock.patch.dict(sys.modules, {'local_machine': module})

    def test_plain_arrows_reach_existing_native_handler_with_both_event_apis(self):
        for api in ('camel', 'snake'):
            for name in ('Up', 'Down'):
                with self.subTest(api=api, name=name), self.no_marker():
                    ns, native, forwarded, _ = self.patched()
                    for pressed in (True, False):
                        event = self.event(api, pressed=pressed, name=name)
                        self.assertEqual(ns['_patched_process_key'](event), 'native-result')
                        self.assertIs(native[-1], event)
                    self.assertEqual(forwarded, [])

    def test_injection_marker_consumes_only_owned_event_then_preserves_native_chain(self):
        for api in ('camel', 'snake'):
            with self.subTest(api=api):
                ns, native, _, _ = self.patched()
                event = self.event(api)
                tokens = {(event.id, True): 1, (event.id, False): 1}
                marker_calls = []
                def injected(keysym, pressed):
                    token = (keysym, pressed)
                    marker_calls.append(token)
                    if tokens.get(token):
                        tokens[token] -= 1
                        return True
                    return False
                module = ModuleType('local_machine')
                module.is_injected_event = injected
                with mock.patch.dict(sys.modules, {'local_machine': module}):
                    for pressed in (True, False):
                        event = self.event(api, pressed=pressed)
                        self.assertIs(ns['_patched_process_key'](event), False)
                    self.assertEqual(native, [])
                    self.assertEqual(ns['_patched_process_key'](self.event(api)), 'native-result')
                self.assertEqual(marker_calls, [(65364, True), (65364, False), (65364, True)])

    def test_direct_management_shortcut_owns_matching_release_without_native_processing(self):
        for api in ('camel', 'snake'):
            with self.subTest(api=api), self.no_marker():
                ns, native, forwarded, shortcuts = self.patched()
                shortcut = {'id': 'connect', 'handler': lambda script, event: shortcuts.append(event)}
                ns['_get_remote_shortcut_match'] = lambda event: shortcut
                press = self.event(api)
                self.assertIs(ns['_patched_process_key'](press), True)
                self.assertIs(ns['_patched_process_key'](self.event(api, pressed=False)), True)
                self.assertEqual(shortcuts, [press])
                self.assertEqual(native, [])
                self.assertEqual(forwarded, [])
                self.assertEqual(ns['_direct_shortcut_keys_down'], set())

    def test_master_forwarding_preserves_press_release_payload_and_ownership(self):
        for api in ('camel', 'snake'):
            with self.subTest(api=api), self.no_marker():
                ns, native, forwarded, _ = self.patched()
                ns['controller'].controlling_remote = True
                for pressed in (True, False):
                    self.assertIs(ns['_patched_process_key'](self.event(api, pressed=pressed)), True)
                self.assertEqual([event['pressed'] for event in forwarded], [True, False])
                self.assertTrue(all(event['vk_code'] == 0x28 and event['extended'] for event in forwarded))
                self.assertEqual(ns['_forwarded_keys_down'], set())
                self.assertEqual(native, [])

    def test_marker_patch_preserves_other_code_and_is_idempotent(self):
        original = UPSTREAM + '\nexample = "event_self.is_pressed_key()"\n'
        updated = remote_access._patch_legacy_customization_event_api(original)
        self.assertTrue(remote_access.legacy_customization_event_api_patch_current(updated))
        self.assertIn('example = "event_self.is_pressed_key()"', updated)
        self.assertEqual(remote_access._patch_legacy_customization_event_api(updated), updated)
        self.assertFalse(remote_access.legacy_customization_event_api_patch_current(original))

    def test_newly_reachable_debug_calls_never_open_raw_keyboard_log(self):
        ns, _, _, _ = self.patched()
        ns['controller'].controlling_remote = True
        ns['_DBG_LOG'] = '/tmp/private-keyboard-log'
        with self.no_marker(), mock.patch('builtins.open') as opened:
            self.assertIs(ns['_patched_process_key'](self.event('camel')), True)
            ns['_dbg']('private keyboard input')
        opened.assert_not_called()

    def test_validator_rejects_incomplete_helper_and_reintroduced_unsafe_call(self):
        updated = remote_access._patch_legacy_customization_event_api(UPSTREAM)
        for corrupt in (
            updated.replace('return bool(method())', 'return False'),
            updated.replace('_linux_rdaccess_event_is_pressed(event_self)', 'event_self.is_pressed_key()', 1),
            updated.replace('_linux_rdaccess_event_is_pressed(event_self)', 'event_self.isPressedKey()', 1),
            updated.replace('def _patched_process_key(event_self):',
                            'def _patched_process_key(event_self):\n'
                            '        _linux_rdaccess_event_is_pressed = lambda event: False'),
            updated + '\n_linux_rdaccess_event_is_pressed = None\n',
        ):
            with self.subTest(corrupt=corrupt[-80:]):
                self.assertFalse(remote_access.legacy_customization_event_api_patch_current(corrupt))
                with self.assertRaises(ValueError):
                    remote_access._patch_legacy_customization_event_api(corrupt)

    def test_reenabled_debug_logger_is_detected_and_safely_disabled_on_update(self):
        updated = remote_access._patch_legacy_customization_event_api(UPSTREAM)
        unsafe = updated.replace(remote_access._DBG_GUARD, '')
        self.assertFalse(remote_access.legacy_customization_event_api_patch_current(unsafe))
        self.assertEqual(remote_access._patch_legacy_customization_event_api(unsafe), updated)

    def test_updater_publishes_current_event_api_patch_and_keeps_original_private_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'orca-customizations.py'
            original = fixtures.LegacyConfigTests.CONFIG_SOURCE + UPSTREAM
            path.write_text(original)
            config = remote_access.RemoteAccessConfig(key='synthetic')
            remote_access.update_legacy_orca_customizations(config, path)
            updated = path.read_text()
            self.assertTrue(remote_access.legacy_customization_event_api_patch_current(updated))
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), updated)
            backup = path.with_name(path.name + '.linux-rdaccess-backup')
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_ambiguous_or_argument_bearing_event_calls_are_refused(self):
        for original in (
            UPSTREAM + '\ndef _patched_process_key(event_self):\n    return False\n',
            UPSTREAM.replace('event_self.is_pressed_key()', 'event_self.is_pressed_key(True)', 1),
        ):
            with self.assertRaises(ValueError):
                remote_access._patch_legacy_customization_event_api(original)

    def test_camel_calls_are_normalized_when_patching_older_customizations(self):
        source = UPSTREAM.replace('event_self.is_pressed_key()', 'event_self.isPressedKey()')
        updated = remote_access._patch_legacy_customization_event_api(source)
        self.assertTrue(remote_access.legacy_customization_event_api_patch_current(updated))
        self.assertNotIn('event_self.isPressedKey()', updated)

    def test_local_helper_shadow_is_refused_before_adding_patch(self):
        source = UPSTREAM.replace('def _patched_process_key(event_self):',
                                  'def _patched_process_key(event_self):\n'
                                  '        _linux_rdaccess_event_is_pressed = lambda event: False')
        with self.assertRaises(ValueError):
            remote_access._patch_legacy_customization_event_api(source)
