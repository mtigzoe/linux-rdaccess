"""Metadata-only input trace (LINUX_RDACCESS_TRACE=1) regressions.

The trace exists so a live NVDA -> NVDA Remote -> Orca failure can be proven
without logging typed text, passwords, speech, clipboard data or braille input.
These tests pin both halves: the facts it must expose, and what it must never
record.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock

import remote_access
from tests import test_remote_access as fixtures
from tests.test_compat_lifecycle import Harness

TRACE_NAME = 'orca-remote-input-trace.log'


class TraceCase(Harness, unittest.TestCase):
    SHIFT, CTRL, ALT, ORCA = 1, 4, 8, 256
    A_CODE, F_CODE, M_CODE, N_CODE, O_CODE, W_CODE, D_CODE = 38, 41, 58, 57, 32, 25, 40
    LEFT, RIGHT, UP, DOWN, KP_DOWN = 113, 114, 111, 116, 88
    _orca_env = fixtures.LegacyConfigTests._orca_env
    _hooked = fixtures.LegacyConfigTests._hooked

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        (self.home / '.local' / 'share' / 'orca').mkdir(parents=True)
        env = mock.patch.dict(os.environ, {'HOME': home.name}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('LINUX_RDACCESS_TRACE', None)
        os.environ.pop('LINUX_RDACCESS_NVDA_LAYOUT', None)

    def enable(self):
        os.environ['LINUX_RDACCESS_TRACE'] = '1'
        self.addCleanup(os.environ.pop, 'LINUX_RDACCESS_TRACE', None)

    @property
    def trace_path(self):
        return self.home / '.local' / 'share' / 'orca' / TRACE_NAME

    def records(self, kind=None):
        if not self.trace_path.exists():
            return []
        rows = [json.loads(line) for line in
                self.trace_path.read_text(encoding='utf-8').splitlines()]
        return [row for row in rows if kind is None or row['kind'] == kind]

    def last(self, kind):
        return self.records(kind)[-1]


class DefaultsAndPrivacyTests(TraceCase):
    def test_trace_is_off_by_default_and_creates_no_file(self):
        c, _, _ = self._patched_controller()
        self._key(c, 0xA0, True)
        self._key(c, 0xA0, False)
        self.assertFalse(self.trace_path.exists())

    def test_trace_file_is_private_and_sequenced(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0xA0, True)
        self._key(c, 0xA0, False)
        self.assertEqual(stat.S_IMODE(self.trace_path.stat().st_mode), 0o600)
        seqs = [row['seq'] for row in self.records()]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(seqs), len(set(seqs)))

    def test_character_keys_never_expose_an_identity(self):
        self.enable()
        c, _, _ = self._patched_controller()
        for vk in (0x50, 0x41, 0x53, 0x53, 0x31, 0x20, 0x6D, 0x60):
            self._key(c, vk, True)
            self._key(c, vk, False)
        rows = self.records('key')
        self.assertEqual(len(rows), 16)
        for row in rows:
            self.assertEqual(row['id'], 'char')
            for field in ('vk', 'scan', 'ext'):
                self.assertNotIn(field, row)
        for row in self.records('forward'):
            self.assertEqual(row['id'], 'char')

    def test_character_keys_are_unidentified_even_with_shift_and_ctrl(self):
        self.enable()
        c, _, _ = self._patched_controller()
        for modifier in (0xA0, 0xA2):
            self._key(c, modifier, True)
            self._key(c, 0x41, True)
            self._key(c, 0x41, False)
            self._key(c, modifier, False)
        chars = [row for row in self.records('key') if row['id'] == 'char']
        self.assertEqual(len(chars), 4)
        self.assertTrue(all('vk' not in row for row in chars))

    def test_nvda_command_keys_are_identified_only_while_nvda_is_held(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x4E, True)                         # plain n: typed text
        self._key(c, 0x4E, False)
        self._key(c, 0x2D, True, extended=True)          # NVDA modifier
        self._key(c, 0x4E, True)                         # NVDA+N command
        self._key(c, 0x4E, False)
        rows = [row for row in self.records('key') if row.get('vk') == 0x4E
                or row['id'] == 'char']
        self.assertEqual([row['id'] for row in rows[:2]], ['char', 'char'])
        command = [row for row in rows if row.get('vk') == 0x4E]
        self.assertEqual({row['vk'] for row in command}, {0x4E})
        self.assertEqual(command[0]['why'], 'unsupported_nvda_command')

    def test_no_typed_text_appears_anywhere_in_the_trace(self):
        self.enable()
        c, _, _ = self._patched_controller()
        secret = 'hunter2'
        for ch in secret:
            self._key(c, ord(ch.upper()), True)
            self._key(c, ord(ch.upper()), False)
        c._on_remote_key(key_name='q', pressed=True, extended=False)
        c._on_remote_key(key_name='q', pressed=False, extended=False)
        text = self.trace_path.read_text(encoding='utf-8')
        values = set()

        def collect(value):
            if isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, str):
                values.add(value.lower())

        for row in self.records():
            collect(row)
        for ch in set(secret) | {'q'}:
            self.assertNotIn(ch, values)
        self.assertNotIn(secret, text)
        self.assertNotIn('key_name', text)

    def test_sanitizer_reduces_arbitrary_strings_to_a_placeholder(self):
        c, _, _ = self._patched_controller()
        clean = c._module._lrd_trace_clean
        self.assertEqual(clean('my password is swordfish'), '?')
        self.assertEqual(clean('a' * 41), '?')
        self.assertEqual(clean('firstRow'), 'firstRow')
        self.assertEqual(clean({'key words': ['x y', 3, True, None]}),
                         {'?': ['?', 3, True, None]})
        self.assertEqual(clean(object()), '?')
        self.assertIsNone(clean(2 ** 40))

    def test_trace_rotates_privately_at_the_size_limit(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self.trace_path.write_text('x' * (c._module._LRD_TRACE_LIMIT + 1))
        os.chmod(self.trace_path, 0o644)
        self._key(c, 0xA0, True)
        rotated = self.trace_path.with_name(TRACE_NAME + '.1')
        self.assertTrue(rotated.exists())
        self.assertEqual(stat.S_IMODE(rotated.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.trace_path.stat().st_mode), 0o600)
        self.assertNotIn('xxxx', self.trace_path.read_text())

    def test_unwritable_trace_never_disturbs_input(self):
        self.enable()
        c, _, _ = self._patched_controller()
        with mock.patch.object(os, 'open', side_effect=OSError('read-only')):
            self._key(c, 0x41, True)
        self.assertIn(('key', 0x41, True, None), c.local_machine.events)

    def test_trace_failure_never_changes_the_filter_result(self):
        self.enable()
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_trace_key = mock.Mock(side_effect=RuntimeError('boom'))
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x51, True)                         # NVDA+Q: consumed
        self.assertNotIn(('key', 0x51, True, None), c.local_machine.events)


class KeyDispositionTests(TraceCase):
    def test_modifier_ownership_distinguishes_left_and_right_keys(self):
        self.enable()
        c, _, _ = self._patched_controller()
        for vk in (0xA0, 0xA3, 0xA4, 0xA1, 0xA2, 0xA5):
            self._key(c, vk, True)
        # Ownership is the state when the filter decided: the key being
        # decided is "down" but not yet injected ("fwd").
        own = self.last('key')['own']
        self.assertEqual(own['down'], ['LAlt', 'LCtrl', 'LShift', 'RAlt', 'RCtrl', 'RShift'])
        self.assertEqual(own['fwd'], ['LAlt', 'LCtrl', 'LShift', 'RCtrl', 'RShift'])
        self._key(c, 0x5B, True)
        own = self.last('key')['own']
        self.assertEqual(own['fwd'], ['LAlt', 'LCtrl', 'LShift', 'RAlt', 'RCtrl', 'RShift'])
        self._key(c, 0xA3, False)
        own = self.last('key')['own']
        self.assertNotIn('RCtrl', own['down'])
        self.assertIn('LCtrl', own['down'])
        self._key(c, 0x5C, True)                      # next decision sees the release
        own = self.last('key')['own']
        self.assertNotIn('RCtrl', own['fwd'])
        self.assertIn('LCtrl', own['fwd'])

    def test_generic_modifier_vks_are_not_guessed_to_be_left_or_right(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x10, True)
        self._key(c, 0x11, True)
        self._key(c, 0x12, True)
        self.assertEqual(self.last('key')['own']['down'], ['Alt', 'Ctrl', 'Shift'])

    def test_insert_and_capslock_ownership_and_nvda_key(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x14, True)
        row = self.last('key')
        self.assertEqual(row['disp'], 'caps_deferred')
        self.assertTrue(row['own']['caps_pending'])
        self.assertEqual(row['own']['nvda'], 'CapsLock')
        self.assertEqual(row['own']['fwd'], [])           # nothing injected yet
        self._key(c, 0x2D, True, extended=True)
        row = self.last('key')
        self.assertEqual(row['own']['nvda'], 'Insert/ext')
        self.assertEqual(row['own']['down'], ['CapsLock', 'Insert/ext'])
        self.assertTrue(row['own']['caps_pending'])
        self.assertTrue(row['own']['insert_pending'])

    def test_nonextended_insert_is_not_labelled_as_the_keypad(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=False)
        row = self.last('key')
        self.assertEqual(row['id'], 'Insert/nonext')
        self.assertNotIn('umpad', json.dumps(row))
        self.assertNotIn('umpad', json.dumps(self.records()))

    def test_navigation_vks_report_the_extended_bit_without_interpretation(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x24, True, extended=False)
        self.assertEqual(self.last('key')['id'], 'Home/nonext')
        self._key(c, 0x24, False, extended=False)
        self._key(c, 0x24, True, extended=True)
        self.assertEqual(self.last('key')['id'], 'Home/ext')

    def test_ordinary_forward_unsupported_and_translated_dispositions(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x28, True, extended=True)
        self.assertEqual(self.last('key')['disp'], 'forwarded')
        self._key(c, 0x28, False, extended=True)
        calls = []
        c._linux_rdaccess_script_call = lambda method, *a: calls.append(method)
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x28, True, extended=True)          # desktop NVDA+Down
        row = self.last('key')
        self.assertEqual((row['disp'], row['why']), ('translated', 'translate:sayAll'))
        self.assertEqual(calls, ['sayAll'])
        self._key(c, 0x28, True, extended=True)          # autorepeat
        self.assertEqual(self.last('key')['disp'], 'owned_press')
        self._key(c, 0x28, False, extended=True)
        self.assertEqual(self.last('key')['disp'], 'owned_release')
        self._key(c, 0x51, True)                         # NVDA+Q: unsupported
        row = self.last('key')
        self.assertEqual((row['disp'], row['why']),
                         ('suppressed', 'unsupported_nvda_command'))

    def test_unsupported_object_review_is_distinguished_from_other_suppression(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x0C, True)                          # NVDA+Numpad5
        row = self.last('key')
        self.assertEqual((row['disp'], row['why']),
                         ('suppressed', 'unsupported_object_review'))
        self.assertEqual(row['vk'], 0x0C)
        self.assertEqual(row['ext'], False)

    def test_read_row_and_column_remain_consumed_and_traced_as_unsupported(self):
        self.enable()
        c, _, _ = self._patched_controller()
        for vk in (0x25, 0x26, 0x27, 0x28):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0xA2, True)
            self._key(c, 0xA4, True)
            self._key(c, vk, True, extended=True)
            row = self.last('key')
            self.assertEqual((row['disp'], row['why']),
                             ('suppressed', 'unsupported_nvda_command'))
            self.assertNotIn('claim', row)
            for held in (vk, 0xA4, 0xA2, 0x2D):
                self._key(c, held, False, extended=held in (vk, 0x2D))
        self.assertEqual([e for e in c.local_machine.events
                          if e[0] == 'key' and e[1] in (0x25, 0x26, 0x27, 0x28)], [])

    def test_pass_next_is_reported(self):
        self.enable()
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_script_call = lambda method, *a: True
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x71, True)                          # NVDA+F2
        self._key(c, 0x71, False)
        self._key(c, 0x2D, False, extended=True)
        self.assertEqual(self.records('key')[1]['why'], 'translate:pass_next')
        self._key(c, 0x41, True)                          # the passed-through key
        row = self.last('key')
        self.assertEqual(row['disp'], 'pass_next')
        self.assertEqual(row['id'], 'char')

    def test_navigation_claims_are_reported_without_naming_letters(self):
        self.enable()
        c, _, _ = self._patched_controller()
        for vk in (0x46, 0x44, 0x37):                     # F, D, 7
            self._key(c, vk, True)
            row = self.last('key')
            self.assertEqual(row['claim'], 'letter')
            self.assertNotIn('claim_cmd', row)
            self.assertEqual(row['id'], 'char')
            self._key(c, vk, False)
        self._key(c, 0xA2, True)
        self._key(c, 0xA4, True)
        self._key(c, 0x24, True, extended=True)           # Ctrl+Alt+Home
        row = self.last('key')
        self.assertEqual((row['claim'], row['claim_cmd']), ('table_edge', 'firstColumn'))
        self._key(c, 0x24, False, extended=True)
        self._key(c, 0x26, True, extended=True)           # Ctrl+Alt+Up
        row = self.last('key')
        self.assertEqual((row['claim'], row['claim_cmd']), ('table_arrow', 'Up'))
        text = self.trace_path.read_text(encoding='utf-8')
        for letter in ('"f"', '"d"', '"7"'):
            self.assertNotIn(letter, text)

    def test_nvda_browse_claims_name_the_command(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x2D, True, extended=True)
        self._key(c, 0x56, True)                          # NVDA+V
        row = self.last('key')
        self.assertEqual((row['disp'], row['claim'], row['claim_cmd']),
                         ('forwarded', 'nvda_browse', 'layout'))


class LockAndResetTests(TraceCase):
    def lock_reader(self, c, states):
        states = list(states)
        c._linux_rdaccess_read_lock_state = lambda vk: states.pop(0) if states else None

    def test_lock_transitions_record_before_and_after_for_each_direction(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self.lock_reader(c, [False, True, True, True, True, False])
        self._key(c, 0x90, True)
        self._key(c, 0x90, False)
        locks = self.records('lock')
        self.assertEqual([(r['id'], r['down'], r['before'], r['after'], r['changed'])
                          for r in locks],
                         [('NumLock', True, False, True, True),
                          ('NumLock', False, True, True, False)])

    def test_caps_lock_toggle_is_recorded_once_after_the_deferred_release(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self.lock_reader(c, [False, False, False, True, True])
        self._key(c, 0x14, True)                          # deferred: nothing forwarded
        self.assertEqual(self.records('lock'), [])
        self._key(c, 0x14, False)                         # flush press, then release
        locks = self.records('lock')
        self.assertEqual([r['down'] for r in locks], [True, False])
        self.assertEqual([r['id'] for r in locks], ['CapsLock', 'CapsLock'])
        self.assertEqual(sum(1 for r in locks if r['changed']), 1)

    def test_caps_lock_used_as_nvda_modifier_records_no_lock_change(self):
        self.enable()
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_script_call = lambda method, *a: True
        self.lock_reader(c, [])
        self._key(c, 0x14, True)
        self._key(c, 0x28, True, extended=True)           # CapsLock+Down: command
        self._key(c, 0x28, False, extended=True)
        self._key(c, 0x14, False)
        self.assertEqual(self.records('lock'), [])
        self.assertNotIn(('key', 0x14, True, None), c.local_machine.events)

    def test_num_lock_autorepeat_is_one_forward(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self.lock_reader(c, [])
        for _ in range(4):
            self._key(c, 0x90, True)
        presses = [r for r in self.records('key') if r['id'] == 'NumLock']
        self.assertEqual([r['disp'] for r in presses],
                         ['forwarded', 'suppressed', 'suppressed', 'suppressed'])
        self.assertEqual(presses[1]['why'], 'lock_repeat')
        self.assertEqual(presses[1]['press'], 'repeat')
        self.assertEqual(len(self.records('forward')), 1)

    def test_failed_release_during_reset_is_reported_as_still_owned(self):
        self.enable()
        c, _, _ = self._patched_controller()
        results = {'fail': True}

        def send(**kw):
            if not kw['pressed'] and results['fail']:
                return False
            return True

        c.local_machine.send_key = send
        self._key(c, 0xA2, True)
        self._key(c, 0x41, True)
        c.toggle_control()
        row = self.last('reset')
        self.assertEqual(row['reason'], 'toggle_control')
        self.assertEqual(row['held'], ['LCtrl', 'char'])
        self.assertEqual(row['failed'], ['LCtrl', 'char'])
        results['fail'] = False
        c.toggle_control()
        self.assertEqual(self.last('reset')['failed'], [])

    def test_reset_reasons_cover_disconnect_and_reconnect(self):
        self.enable()
        c, _, _ = self._patched_controller()
        for method, reason in (('disconnect', 'disconnect'),
                               ('_on_transport_disconnected', '_on_transport_disconnected')):
            if not hasattr(c, method):
                continue
            self._key(c, 0xA0, True)
            getattr(c, method)()
            self.assertEqual(self.last('reset')['reason'], reason)

    def test_state_change_reports_the_session_and_bumps_the_generation(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0xA0, True)
        first = self.last('key')['gen']
        c.control_state = 0
        self._key(c, 0xA0, False)
        rows = self.records('session')
        self.assertTrue(rows)
        self.assertEqual(rows[-1]['controlling'], False)
        self.assertEqual(rows[-1]['role'], 'slave')
        self.assertGreater(self.last('key')['gen'], first)
        self.assertEqual(self.last('reset')['reason'], 'state_change')

    def test_forward_failures_are_reported(self):
        self.enable()
        c, _, _ = self._patched_controller()
        c.local_machine.send_key = lambda **kw: False
        self._key(c, 0xA2, True)
        row = self.last('forward')
        self.assertEqual((row['id'], row['result'], row['owned']),
                         ('LCtrl', 'rejected', False))

        def raising(**kw):
            raise OSError('xtest unavailable')

        c.local_machine.send_key = raising
        self._key(c, 0xA2, False)
        self._key(c, 0xA0, True)
        self.assertEqual(self.last('forward')['result'], 'raised')


class SpeechAndCallbackTests(TraceCase):
    def test_ctrl_cancels_nvda_once_and_repeat_does_not_resend(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0xA3, True)
        self._key(c, 0xA3, True)                          # autorepeat
        sent = [r['what'] for r in self.records('speech')]
        self.assertEqual(sent.count('nvda_cancel_sent'), 1)
        self.assertEqual(c.transport.sent.count('cancel'), 1)
        self.assertIn('local_stop_requested', sent)

    def test_cancel_not_applicable_is_reported_for_a_master_transport(self):
        self.enable()
        c, _, _ = self._patched_controller()
        c.transport.connection_type = 'master'
        self._key(c, 0xA2, True)
        self.assertIn('nvda_cancel_not_applicable',
                      [r['what'] for r in self.records('speech')])
        self.assertEqual(c.transport.sent, [])

    def test_autorepeat_cancel_throttling_is_reported(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x28, True, extended=True)
        self._key(c, 0x28, True, extended=True)
        self.assertIn('cancel_throttled', [r['what'] for r in self.records('speech')])

    def test_stale_main_loop_callbacks_are_reported_not_run(self):
        self.enable()
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        calls = []
        c._linux_rdaccess_script_call = lambda method, *a: calls.append(method)
        with patches:
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x28, True, extended=True)       # NVDA+Down: Say All queued
            scheduled = self.records('main')
            self.assertEqual(scheduled[-1]['state'], 'scheduled')
            c.toggle_control()                           # generation changes
            for callback in list(queue):
                callback()
        states = [(r['state']) for r in self.records('main')]
        self.assertIn('stale_skipped', states)
        self.assertEqual(calls, [])
        self.assertEqual(self.records('script'), [])
        stale = [r for r in self.records('main') if r['state'] == 'stale_skipped'][-1]
        self.assertLess(stale['sched_gen'], stale['gen'])

    def test_live_main_loop_callback_reports_the_orca_operation(self):
        self.enable()
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        module = types.ModuleType('linux_rdaccess_orca_adapter')
        module.OrcaRuntimeAdapter = types.SimpleNamespace(say_all=lambda: True)
        with patches, mock.patch.dict('sys.modules', {'linux_rdaccess_orca_adapter': module}):
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x28, True, extended=True)
            for callback in list(queue):
                callback()
        self.assertEqual([r['state'] for r in self.records('main')][-1], 'ran')
        self.assertEqual(self.last('script')['method'], 'sayAll')


class BrailleTraceTests(TraceCase):
    def send(self, c, **kwargs):
        c._on_remote_braille_input(**kwargs)

    def test_pan_route_and_to_focus_are_classified(self):
        self.enable()
        c, _, _ = self._patched_controller()
        c._linux_rdaccess_script_call = lambda method, *a: True
        gc = ['globalCommands', 'GlobalCommands']
        self.send(c, scriptPath=gc + ['script_braille_scrollBack'])
        self.send(c, scriptPath=gc + ['script_braille_scrollForward'])
        self.send(c, scriptPath=gc + ['script_braille_toFocus'])
        self.send(c, routingIndex=12)
        rows = self.records('braille')
        self.assertEqual([r['cls'] for r in rows],
                         ['pan_back', 'pan_forward', 'to_focus', 'route'])
        self.assertNotIn('12', self.trace_path.read_text())
        self.assertNotIn('routingIndex', self.trace_path.read_text())

    def test_braille_keyboard_input_is_never_recorded(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self.send(c, dots=0b1011, space=False, id='bk:dots', identifiers=['bk:dot1+dot2+dot4'])
        self.send(c, space=True, id='bk:space', identifiers=['bk:space'])
        rows = self.records('braille')
        self.assertEqual([r['cls'] for r in rows], ['keyboard', 'keyboard'])
        text = self.trace_path.read_text()
        for secret in ('dot1', 'bk:', 'dots', 'identifiers', '1011'):
            self.assertNotIn(secret, text)
        self.assertEqual({r['record'] for r in rows}, {'braille-keyboard-input'})

    def test_emulated_navigation_key_reports_its_canonical_name_only(self):
        self.enable()
        c, _, _ = self._patched_controller()
        gc = ['globalCommands', 'GlobalCommands']
        self.send(c, scriptPath=gc + ['kb:shift+downArrow'],
                  id='eurobraille.bnote:k1', identifiers=['eurobraille.bnote:k1'])
        row = self.last('braille')
        self.assertEqual(row['cls'], 'key')
        self.assertEqual(row['emulated'], {'mods': ['shift'], 'key': 'downArrow'})
        self.assertNotIn('eurobraille', self.trace_path.read_text())

    def test_unknown_and_malformed_braille_input_is_not_described(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self.send(c, id='secret-driver-id', identifiers=['secret-driver-id'])
        self.send(c, identifiers='not-a-list')
        rows = self.records('braille')
        self.assertEqual([r['cls'] for r in rows], ['unclassified', 'unclassified'])
        self.assertEqual([r['record'] for r in rows],
                         ['unknown-braille-input', 'invalid-braille-input'])
        self.assertNotIn('secret', self.trace_path.read_text())


class OrcaHookTraceTests(TraceCase):
    def hooked(self, browse=True, in_document=True, focus=None):
        c, KE, script = self._hooked(browse=browse, in_document=in_document)
        script.inFocusMode = lambda: (not browse) if focus is None else focus
        return c, KE, script

    def hooks(self):
        return self.records('hook')

    def test_letter_refused_in_focus_mode_records_context_but_no_letter(self):
        self.enable()
        c, KE, _ = self.hooked(browse=False, in_document=True)
        self._key(c, 0x46, True)
        ev = KE('f', self.F_CODE)
        self.assertIsNone(ev._consumer)
        row = self.hooks()[-1]
        self.assertEqual((row['hook'], row['decision'], row['ctx']),
                         ('letter_nav', 'refused_not_browse', 'document_focus'))
        self.assertNotIn('cmd', row)
        self.assertNotIn('"f"', self.trace_path.read_text())

    def test_letter_refused_in_browser_chrome_is_reported_as_non_document(self):
        self.enable()
        c, KE, _ = self.hooked(browse=False, in_document=False)
        self._key(c, 0x46, True)
        ev = KE('f', self.F_CODE)
        self.assertIsNone(ev._consumer)
        self.assertEqual(self.hooks()[-1]['ctx'], 'chrome_or_non_document')

    def test_form_field_and_heading_navigation_in_browse_mode_are_named(self):
        self.enable()
        c, KE, _ = self.hooked()
        self._key(c, 0x46, True)
        KE('f', self.F_CODE)
        row = self.hooks()[-1]
        self.assertEqual((row['decision'], row['cmd'], row['ctx']),
                         ('native', 'form_field', 'document_browse'))
        self._key(c, 0xA0, True)
        self._key(c, 0x38, True)
        KE('8', 18, modifiers=self.SHIFT)
        row = self.hooks()[-1]
        self.assertEqual((row['cmd'], row['level'], row['reverse']),
                         ('heading_level', 8, True))

    def test_mismatched_browse_letters_are_reported_without_the_letter(self):
        self.enable()
        c, KE, _ = self.hooked()
        self._key(c, 0x4E, True)
        KE('n', self.N_CODE)
        row = self.hooks()[-1]
        self.assertEqual((row['decision'], row['cmd']), ('consumed_unsupported', 'browse_letter'))
        self.assertNotIn('"n"', self.trace_path.read_text())

    def test_d_landmark_translation_is_reported_as_orca_consumed(self):
        self.enable()
        c, KE, _ = self.hooked()
        self._key(c, 0x44, True)
        KE('d', self.D_CODE)
        decisions = [(r['hook'], r['decision']) for r in self.hooks()]
        self.assertEqual(decisions, [('letter_nav', 'translated'),
                                     ('orca_native', 'consumed')])
        self.assertNotIn('"d"', self.trace_path.read_text())

    def test_nvda_browse_commands_report_mode_specific_decisions(self):
        self.enable()
        for browse, in_document, decision in (
                (True, True, 'native'), (False, True, 'native'),
                (True, False, 'consumed_outside_document')):
            with self.subTest(browse=browse, in_document=in_document):
                c, KE, _ = self.hooked(browse=browse, in_document=in_document)
                self._key(c, 0x2D, True, extended=True)
                self._key(c, 0x56, True)
                KE('v', 55)
                row = self.hooks()[-1]
                self.assertEqual((row['hook'], row['cmd'], row['decision']),
                                 ('nvda_browse', 'layout', decision))

    def test_table_arrow_and_edge_translation_and_refusal(self):
        self.enable()
        c, KE, _ = self.hooked()
        self._key(c, 0xA2, True)
        self._key(c, 0xA4, True)
        self._key(c, 0x25, True, extended=True)
        KE('Left', self.LEFT, modifiers=self.CTRL | self.ALT)
        row = [r for r in self.hooks() if r['hook'] == 'table'][-1]
        self.assertEqual((row['decision'], row['cmd']), ('translated_arrow', 'Left'))
        c2, KE2, _ = self.hooked(browse=False, in_document=True)
        self._key(c2, 0xA2, True)
        self._key(c2, 0xA4, True)
        self._key(c2, 0x25, True, extended=True)
        KE2('Left', self.LEFT, modifiers=self.CTRL | self.ALT)
        row = [r for r in self.hooks() if r['hook'] == 'table'][-1]
        self.assertEqual((row['decision'], row['ctx']),
                         ('refused_not_browse', 'document_focus'))

    def test_table_edge_reports_translation_and_stale_delayed_consumer(self):
        self.enable()
        c, KE, script = self.hooked()
        cell, table, caret = object(), object(), object()
        nav = script.structuralNavigation
        state = {'cell': cell}
        nav.getCellForObj = lambda obj: state['cell']
        nav.getCellCoordinates = lambda obj, prefer: [2, 3]
        nav.getTableForCell = lambda obj: table
        nav.goCell = lambda *args: None
        script.utilities = types.SimpleNamespace(
            getCaretContext=lambda: (caret, 0),
            rowAndColumnCount=lambda obj, prefer: (5, 6),
            inDocumentContent=lambda obj=None: True)
        self._key(c, 0xA2, True)
        self._key(c, 0xA4, True)
        self._key(c, 0x24, True, extended=True)
        ev = KE('Home', 110, modifiers=self.CTRL | self.ALT)
        row = [r for r in self.hooks() if r['hook'] == 'table'][-1]
        self.assertEqual((row['decision'], row['cmd']), ('translated_edge', 'firstColumn'))
        state['cell'] = None                          # focus left the table
        ev._consumer(ev)
        row = [r for r in self.hooks() if r['hook'] == 'table'][-1]
        self.assertEqual(row['decision'], 'consumer_stale')

    def test_context_reports_stale_editable_and_application_widgets(self):
        self.enable()
        c, KE, script = self.hooked(browse=False, in_document=True)
        locus = types.SimpleNamespace(getState=lambda: types.SimpleNamespace(
            contains=lambda state: state == 'editable'))
        orca_state = types.SimpleNamespace(locusOfFocus=locus)
        atspi = types.ModuleType('pyatspi')
        atspi.STATE_EDITABLE = 'editable'
        script.utilities.isWebAppDescendant = lambda obj: True
        script.utilities.isZombie = lambda obj: True
        with mock.patch.dict('sys.modules', {'pyatspi': atspi}):
            import sys
            sys.modules['orca'].orca_state = orca_state
            self._key(c, 0x46, True)
            KE('f', self.F_CODE)
        row = self.hooks()[-1]
        self.assertEqual((row['editable'], row['web_app'], row['stale']),
                         (True, True, True))

    def test_context_failure_never_breaks_hook_handling(self):
        self.enable()
        c, KE, script = self.hooked()
        script.utilities.inDocumentContent = mock.Mock(side_effect=RuntimeError('gone'))
        self._key(c, 0x46, True)
        ev = KE('f', self.F_CODE)
        self.assertIsNotNone(ev._consumer)

    def test_hooks_write_nothing_when_tracing_is_off(self):
        c, KE, _ = self.hooked()
        self._key(c, 0x46, True)
        KE('f', self.F_CODE)
        self.assertFalse(self.trace_path.exists())


class UpgradeTests(TraceCase):
    def test_v79_controller_upgrades_to_the_trace_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'remote_controller.py'
            path.write_text(self.UPSTREAM_CONTROLLER)
            self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
            current = path.read_text()
            self.assertIn(remote_access.LEGACY_COMPAT_MARKER, current)
            for older in (remote_access.LEGACY_COMPAT_MARKER_V79,
                          remote_access.LEGACY_COMPAT_MARKER_V80):
                with self.subTest(previous=older):
                    previous = current.replace(remote_access.LEGACY_COMPAT_MARKER, older)
                    path.write_text(previous)
                    self.assertFalse(remote_access.legacy_controller_patch_current(previous))
                    self.assertTrue(remote_access.patch_legacy_orca_remote_controller(path))
                    upgraded = path.read_text()
                    self.assertTrue(remote_access.legacy_controller_patch_current(upgraded))
                    self.assertNotIn(older + '\n', upgraded)
                    self.assertEqual(upgraded.count('def _lrd_trace_write('), 1)
                    self.assertFalse(remote_access.patch_legacy_orca_remote_controller(path))

    def test_trace_writer_is_defined_once_and_source_has_no_content_logging(self):
        source = remote_access._LEGACY_HELPERS + remote_access._LEGACY_ORCA_D_HOOK
        self.assertEqual(source.count('def _lrd_trace_write('), 1)
        for forbidden in ('event_string', 'key_name=key_name', 'text=', 'clipboard'):
            traced = [line for line in source.splitlines()
                      if '_lrd_trace_hook(' in line or '.trace(' in line
                      or '_linux_rdaccess_trace(' in line]
            self.assertFalse([line for line in traced if forbidden in line], forbidden)


if __name__ == '__main__':
    unittest.main()


class SummarizerTests(TraceCase):
    def run_tool(self, *args):
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location(
            'summarize_input_trace',
            Path(__file__).resolve().parent.parent / 'tools' / 'summarize_input_trace.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = module.main(list(args))
        return code, out.getvalue()

    def test_clean_trace_has_no_findings(self):
        self.enable()
        c, _, _ = self._patched_controller()
        self._key(c, 0x28, True, extended=True)
        self._key(c, 0x28, False, extended=True)
        code, text = self.run_tool(str(self.trace_path))
        self.assertEqual(code, 0)
        self.assertIn('findings: 0', text)
        self.assertIn('forwarded=2', text)

    def test_stuck_keys_stale_callbacks_and_refusals_are_flagged(self):
        self.enable()
        c, _, _ = self._patched_controller(inline=False)
        queue, patches = self._fake_glib()
        c.local_machine.send_key = lambda **kw: kw['pressed'] or False
        c._linux_rdaccess_script_call = lambda *a: True
        with patches:
            # Hold an ordinary forwarded key so reset has a genuine injected
            # key whose release can fail. Insert itself is now deferred and
            # must not be treated as forwarded ownership.
            self._key(c, 0x25, True, extended=True)
            self._key(c, 0x2D, True, extended=True)
            self._key(c, 0x28, True, extended=True)
            c.toggle_control()
            for callback in list(queue):
                callback()
        with self.trace_path.open('a') as handle:
            handle.write('not json\n')
        code, text = self.run_tool(str(self.trace_path), '--timeline')
        self.assertEqual(code, 1)
        self.assertIn('could not release', text)
        self.assertIn('skipped, generation', text)
        self.assertIn('not valid JSON', text)
        self.assertIn('timeline:', text)

    def test_missing_trace_reports_without_a_traceback(self):
        code, _ = self.run_tool(str(self.home / 'absent.log'))
        self.assertEqual(code, 2)
