"""Privacy, key ownership, and real-XKB checks for the diagnostic tool."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from diagnostics import live_x11 as live


class LiveDiagnosticTests(unittest.TestCase):
    def test_password_field_name_is_never_queried(self):
        focus = object.__new__(live.Focus)
        password_role = types.SimpleNamespace(value_nick='password-text')
        focus.atspi = types.SimpleNamespace(
            Role=types.SimpleNamespace(APPLICATION=object(), PASSWORD_TEXT=password_role),
            StateType=types.SimpleNamespace(FOCUSED=object()))
        desktop, password = mock.Mock(), mock.Mock()
        focus.atspi.get_desktop = lambda _: desktop
        desktop.get_child_count.return_value = 1
        desktop.get_child_at_index.return_value = password
        password.get_role.return_value = password_role
        states = password.get_state_set.return_value
        states.contains.return_value = True
        states.get_states.return_value = [types.SimpleNamespace(value_nick='focused')]
        result = focus.read()
        self.assertIsNone(result['name'])
        password.get_name.assert_not_called()
        self.assertEqual(focus.public(result)['name'], '[redacted]')

    def test_normal_output_never_serializes_accessible_names(self):
        private = 'password clipboard typed text secret channel key'
        snapshot = {"object": object(), "name": private, "role": "text",
                    "states": ["focused", "editable"]}
        result = live.Focus.public(snapshot)
        self.assertNotIn(private, json.dumps(result))
        self.assertEqual(result["name"], "[redacted]")
        self.assertEqual(result["role"], "text")

    def test_invalid_arguments_and_inputs_do_not_echo_private_values(self):
        for argv in (["--key", "private-sentinel"], ["--private-sentinel"],
                     ["--timeout", "private-sentinel"], ["--watch-locks", "nan"]):
            with self.subTest(argv=argv), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(live.main(argv), 1)
                self.assertNotIn('private-sentinel', output.getvalue())
                self.assertEqual(json.loads(output.getvalue())["error"], "Invalid diagnostic arguments")

    def test_failed_chord_down_releases_its_successful_modifier(self):
        backend = mock.Mock()
        backend.key.side_effect = [True, False, True]
        with self.assertRaisesRegex(live.DiagnosticError, 'injection failed'):
            live.inject(backend, 'Shift+Tab')
        self.assertEqual(backend.key.call_args_list, [mock.call('Shift_L', True),
                                                   mock.call('Tab', True), mock.call('Shift_L', False)])

    def test_failed_release_does_not_skip_other_owned_releases(self):
        backend = mock.Mock()
        backend.key.side_effect = [True, True, RuntimeError('private-sentinel'), True]
        with self.assertRaisesRegex(live.DiagnosticError, 'release failed'):
            live.inject(backend, 'Shift+Tab')
        self.assertEqual(backend.key.call_args_list[-1], mock.call('Shift_L', False))

    def test_unfocused_window_never_receives_input(self):
        backend = mock.Mock()
        with mock.patch.object(live, 'command', return_value='2'):
            with self.assertRaisesRegex(live.DiagnosticError, 'not active'):
                live.exercise({'window_id': 1, 'pid': 10}, 'Tab', mock.Mock(), backend, 0.1)
        backend.key.assert_not_called()

    def test_unknown_indicator_is_unknown_not_off(self):
        xkb = object.__new__(live.Xkb)
        xkb.display = 1
        xkb.lib = mock.Mock()
        xkb.lib.XkbGetIndicatorState.return_value = 0
        xkb.lib.XInternAtom.return_value = 0
        states = xkb.snapshot()
        self.assertEqual(states['Num Lock'], {'available': False, 'on': None, 'index': None,
                                             'physical_indicator': None})
        xkb.lib.XkbGetNamedIndicator.assert_not_called()

    def test_failed_xkb_query_does_not_report_a_state(self):
        xkb = object.__new__(live.Xkb)
        xkb.display = 1
        xkb.lib = mock.Mock()
        xkb.lib.XkbGetIndicatorState.return_value = 1
        with self.assertRaisesRegex(live.DiagnosticError, 'query failed'):
            xkb.snapshot()

    def test_screenshot_is_private_and_replaces_a_symlink_without_following_it(self):
        gi = types.ModuleType('gi')
        gi.require_version = mock.Mock()
        repository = types.ModuleType('gi.repository')
        repository.Gdk, repository.GdkX11 = mock.Mock(), mock.Mock()
        pixbuf = mock.Mock()
        def save(path, *args):
            Path(path).write_bytes(b'synthetic PNG')
            return True
        pixbuf.savev.side_effect = save
        repository.Gdk.pixbuf_get_from_window.return_value = pixbuf
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'original'
            original.write_bytes(b'preserve')
            destination = Path(directory) / 'screenshot.png'
            destination.symlink_to(original)
            with mock.patch.dict('sys.modules', {'gi': gi, 'gi.repository': repository}):
                live.screenshot(123, destination)
            self.assertEqual(original.read_bytes(), b'preserve')
            self.assertFalse(destination.is_symlink())
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)


@unittest.skipUnless(os.environ.get('DISPLAY') and os.environ['DISPLAY'].split('.')[0] != ':0',
                     'needs an isolated X server (run under xvfb-run)')
class LiveXkbIntegrationTests(unittest.TestCase):
    def test_held_modifier_is_refused_and_remains_held(self):
        backend = live.injection_backend()
        self.addCleanup(backend.close)
        self.assertTrue(backend.key('Shift_L', True))
        try:
            with self.assertRaisesRegex(live.DiagnosticError, 'already held'):
                live.require_released(backend, 'Tab')
            self.assertIn('Shift_L', backend._down_codes)
        finally:
            self.assertTrue(backend.key('Shift_L', False))

    def test_production_injection_changes_real_named_indicator_and_restores_it(self):
        xkb = live.Xkb(os.environ['DISPLAY'])
        self.addCleanup(xkb.close)
        backend = live.injection_backend()
        self.addCleanup(backend.close)
        initial = xkb.snapshot()['Num Lock']
        self.assertTrue(initial['available'])
        try:
            live.require_released(backend, 'Num_Lock')
            live.inject(backend, 'Num_Lock')
            after = xkb.snapshot()['Num Lock']
            self.assertTrue(after['available'])
            self.assertNotEqual(after['on'], initial['on'])
            self.assertFalse(backend._down_codes)
        finally:
            if xkb.snapshot()['Num Lock']['on'] != initial['on']:
                live.inject(backend, 'Num_Lock')
        self.assertEqual(xkb.snapshot()['Num Lock']['on'], initial['on'])

    def test_failed_release_keeps_original_production_keycode(self):
        backend = live.injection_backend()
        self.addCleanup(backend.close)
        self.assertTrue(backend.key('Down', True))
        self.addCleanup(backend.key, 'Down', False)
        code = backend._down_codes['Down']
        with mock.patch.object(backend._xt, 'XTestFakeKeyEvent', return_value=0):
            self.assertFalse(backend.key('Down', False))
        self.assertEqual(backend._down_codes['Down'], code)
        self.assertTrue(backend.key('Down', False))


if __name__ == '__main__':
    unittest.main()
