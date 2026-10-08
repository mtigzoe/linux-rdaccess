"""Privacy, key ownership, and real-XKB checks for the diagnostic tool."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest import mock

from diagnostics.x11 import live_x11 as live


class LiveDiagnosticTests(unittest.TestCase):
    @staticmethod
    def focus_tree():
        focus = object.__new__(live.Focus)
        roles = types.SimpleNamespace(APPLICATION=object(), PASSWORD_TEXT=object())
        focused, active = (types.SimpleNamespace(value_nick=name) for name in ('focused', 'active'))
        focus.atspi = types.SimpleNamespace(Role=roles,
            StateType=types.SimpleNamespace(FOCUSED=focused, ACTIVE=active))

        def node(role, states=(), children=(), pid=10):
            obj = mock.Mock()
            obj.get_role.return_value = roles.APPLICATION if role == 'application' else types.SimpleNamespace(value_nick=role)
            obj.get_process_id.return_value = pid
            obj.get_name.return_value = 'private focus name'
            state_set = obj.get_state_set.return_value
            state_set.contains.side_effect = lambda state: state.value_nick in states
            state_set.get_states.return_value = [types.SimpleNamespace(value_nick=state) for state in states]
            obj.get_child_count.return_value = len(children)
            obj.get_child_at_index.side_effect = lambda index: children[index]
            return obj

        return focus, node

    def test_focused_descendant_wins_over_focused_window_and_panel(self):
        focus, node = self.focus_tree()
        target = node('check-box', ('focused',))
        panel = node('panel', ('focused',), [target])
        frame = node('frame', ('active', 'focused'), [panel])
        desktop = node('desktop', children=[node('application', children=[frame])])
        focus.atspi.get_desktop = lambda _: desktop
        self.assertIs(focus.read(10)['object'], target)
        frame.get_name.assert_not_called()
        panel.get_name.assert_not_called()

    def test_active_window_focus_wins_over_an_inactive_windows_stale_focus(self):
        focus, node = self.focus_tree()
        active = node('frame', ('active', 'focused'))
        stale = node('entry', ('focused',))
        inactive = node('frame', children=[stale])
        desktop = node('desktop', children=[node('application', children=[active, inactive])])
        focus.atspi.get_desktop = lambda _: desktop
        self.assertIs(focus.read(10)['object'], active)
        stale.get_name.assert_not_called()

    def test_target_application_filter_excludes_another_process(self):
        focus, node = self.focus_tree()
        target = node('entry', ('focused',))
        other = node('entry', ('focused', 'active'))
        desktop = node('desktop', children=[
            node('application', children=[node('frame', children=[target])], pid=10),
            node('application', children=[node('frame', children=[other])], pid=20)])
        focus.atspi.get_desktop = lambda _: desktop
        self.assertIs(focus.read(10)['object'], target)
        other.get_state_set.assert_not_called()
        other.get_name.assert_not_called()

    def test_cyclic_provider_tree_does_not_loop(self):
        focus, node = self.focus_tree()
        target = node('entry', ('focused',))
        desktop = node('desktop', children=[node('application', children=[target])])
        target.get_child_count.return_value = 1
        target.get_child_at_index.side_effect = lambda _: desktop
        focus.atspi.get_desktop = lambda _: desktop
        self.assertIs(focus.read()['object'], target)
        desktop.get_child_count.assert_called_once()
        target.get_child_count.assert_called_once()

    def test_disappearing_focus_provider_returns_unavailable(self):
        for method in ('get_name', 'get_states'):
            with self.subTest(method=method):
                focus, node = self.focus_tree()
                target = node('entry', ('focused',))
                desktop = node('desktop', children=[node('application', children=[target])])
                focus.atspi.get_desktop = lambda _: desktop
                provider = target if method == 'get_name' else target.get_state_set.return_value
                getattr(provider, method).side_effect = RuntimeError('provider disappeared')
                self.assertIsNone(focus.read())

    def test_default_display_uses_discovered_graphical_session(self):
        output = io.StringIO()
        environment = {'DISPLAY': ':1', 'XDG_SESSION_TYPE': 'x11'}
        with mock.patch('linux_rdaccess_core.cli.graphical_session_env', return_value=environment), \
             mock.patch.object(live, 'Xkb') as xkb, \
             mock.patch.dict(os.environ), contextlib.redirect_stdout(output):
            xkb.return_value.snapshot.return_value = {}
            self.assertEqual(live.main([]), 0)
        xkb.assert_called_once_with(':1')
        self.assertEqual(json.loads(output.getvalue())['display'], ':1')

    def test_explicit_display_mismatch_never_opens_x11(self):
        output = io.StringIO()
        with mock.patch('linux_rdaccess_core.cli.graphical_session_env', return_value={'DISPLAY': ':1'}), \
             mock.patch.object(live, 'Xkb') as xkb, contextlib.redirect_stdout(output):
            self.assertEqual(live.main(['--display', ':0']), 1)
        xkb.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['error'],
                         'Requested X11 session does not match detected session')

    def test_selected_session_removes_stale_graphical_variables_before_x11_opens(self):
        output = io.StringIO()
        environment = {'DISPLAY': ':1', 'XDG_SESSION_TYPE': 'x11'}
        stale = {'AT_SPI_BUS_ADDRESS': 'unix:path=/ssh/a11y',
                 'XAUTHORITY': '/tmp/ssh-authority', 'WAYLAND_DISPLAY': 'wayland-0',
                 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/ssh/bus',
                 'XDG_RUNTIME_DIR': '/tmp/ssh-runtime', 'LRD_TEST_UNRELATED': 'preserve'}

        def opened(display):
            self.assertEqual(display, ':1')
            for key in stale:
                if key != 'LRD_TEST_UNRELATED':
                    self.assertNotIn(key, os.environ)
            self.assertEqual(os.environ['LRD_TEST_UNRELATED'], 'preserve')
            instance = mock.Mock()
            instance.snapshot.return_value = {}
            return instance

        with mock.patch('linux_rdaccess_core.cli.graphical_session_env', return_value=environment), \
             mock.patch.object(live, 'Xkb', side_effect=opened), \
             mock.patch.dict(os.environ, stale), contextlib.redirect_stdout(output):
            self.assertEqual(live.main([]), 0)

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

    def test_ctrl_c_exits_cleanly_without_traceback(self):
        output = io.StringIO()
        with mock.patch.object(live, 'PrivateParser') as parser_cls:
            parser = parser_cls.return_value
            parser.parse_args.side_effect = KeyboardInterrupt
            with contextlib.redirect_stdout(output):
                self.assertEqual(live.main([]), 130)
        self.assertEqual(json.loads(output.getvalue()), {"status": "stopped"})

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


def _isolated_xvfb():
    display = re.fullmatch(r':(\d+)(?:\.\d+)?', os.environ.get('DISPLAY', ''))
    if not display:
        return False
    try:
        pid = int(Path(f'/tmp/.X{display[1]}-lock').read_text().strip())
        return Path(f'/proc/{pid}/comm').read_text().strip() == 'Xvfb'
    except (OSError, ValueError):
        return False


class LiveXkbDisplaySafetyTests(unittest.TestCase):
    def test_desktop_at_nonzero_display_is_rejected(self):
        with mock.patch.dict(os.environ, DISPLAY=':1'), \
             mock.patch.object(Path, 'read_text', side_effect=['123', 'Xorg\n']):
            self.assertFalse(_isolated_xvfb())

    def test_unverifiable_display_is_rejected(self):
        with mock.patch.dict(os.environ, DISPLAY=':99'), \
             mock.patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            self.assertFalse(_isolated_xvfb())


@unittest.skipUnless(_isolated_xvfb(), 'needs a private Xvfb server (run under xvfb-run)')
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
