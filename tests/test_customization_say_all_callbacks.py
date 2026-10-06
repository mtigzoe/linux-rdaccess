"""Native Orca 42 callbacks advance remote Say All without local audio."""

import ast
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

import remote_access


class Voice(dict):
    RATE, AVERAGE_PITCH, GAIN, FAMILY = 'rate', 'average-pitch', 'gain', 'family'


class CommunicationError(Exception):
    pass


class NativeClient:
    def __init__(self, volume=40):
        self.volume = volume
        self.queued = []
        self.volume_changes = []
        self.fail_once = False

    def get_volume(self):
        return str(self.volume)

    def set_volume(self, value):
        self.volume_changes.append(value)
        self.volume = value

    def speak(self, text, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise CommunicationError('synthetic connection reset')
        self.queued.append((self.volume, text, kwargs))


class SayAllCallbacksTests(unittest.TestCase):
    def native(self):
        idle = []
        constants = SimpleNamespace(PROGRESS=0, INTERRUPTED=1, COMPLETED=2)
        namespace = {
            '__name__': 'orca.speechdispatcherfactory',
            'ACSS': Voice,
            'settings': SimpleNamespace(DEFAULT_VOICE='default',
                voices={'default': Voice(gain=5, rate=50, **{'average-pitch': 5})}),
            'orca_state': SimpleNamespace(activeScript=None),
            'debug': SimpleNamespace(LEVEL_INFO=1, LEVEL_WARNING=2, println=lambda *a: None),
            'speechserver': SimpleNamespace(SayAllContext=constants),
            'speechd': SimpleNamespace(SSIPCommunicationError=CommunicationError),
            'GLib': SimpleNamespace(idle_add=lambda func, *args: idle.append((func, args)) or 1),
        }
        fixture = Path(__file__).parent / 'fixtures/orca42-speechdispatcher-methods.py'
        exec(compile(fixture.read_text(), str(fixture), 'exec'), namespace)
        cls = namespace['SpeechServer']
        cls._SpeechServer__addVerbalizedPunctuation = lambda self, text: text
        cls._debug_sd_values = lambda self, *a: None
        cls._set_rate = cls._set_pitch = cls._set_family = lambda self, value: None
        server = cls()
        server._client = NativeClient()
        server._current_voice_properties = {'gain': 5}
        server._acss_manipulators = (
            ('rate', server._set_rate), ('average-pitch', server._set_pitch),
            ('gain', server._set_volume), ('family', server._set_family))
        server._CALLBACK_TYPE_MAP = {'BEGIN': 0, 'CANCEL': 1, 'END': 2, 'INDEX_MARK': 0}
        native_speak = cls._speak
        return namespace, server, native_speak, idle

    def hooked(self):
        native, server, original, idle = self.native()
        messages = []
        namespace = {
            'SpeechServer': type(server), 'old_speak': original,
            'LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH': True,
            'transport': SimpleNamespace(connected=True, connection_type='slave',
                                         send=lambda **kw: messages.append(kw)),
            '_want_cancel': False,
        }
        text = remote_access._CUSTOMIZATION_SPEECH_FORWARD_SOURCE
        text = remote_access._patch_legacy_customization_speech_sequence(text)
        text += '\n' + remote_access._LOCAL_SPEECH_PREF_HOOK
        text = remote_access._patch_legacy_customization_say_all_callbacks(text)
        exec(compile(text, 'patched-say-all-customization', 'exec'), namespace)
        type(server)._speak = namespace['my_speak']
        return namespace, server, original, idle, messages

    def test_callback_utterance_is_silent_with_real_native_marks_and_unmodified_voice(self):
        namespace, server, _original, _idle, messages = self.hooked()
        voice = Voice(gain=8, rate=60, **{'average-pitch': 6})
        original_voice = voice.copy()
        callback = lambda *a, **kw: None
        server._speak('TEST WORDS', voice, callback=callback, event_types=['END'])
        self.assertEqual(messages, [{'type': 'speak', 'sequence': ['TEST WORDS']}])
        self.assertEqual(len(server._client.queued), 1)
        volume, ssml, kwargs = server._client.queued[0]
        self.assertEqual(volume, -100)
        self.assertIn('<mark name="0:4"/>', ssml)
        self.assertIs(kwargs['callback'], callback)
        self.assertEqual(kwargs['event_types'], ['END'])
        self.assertEqual(voice, original_voice)
        self.assertEqual(server._client.volume, 40)
        self.assertNotIn('gain', server._current_voice_properties)
        self.assertNotIn('_send_command', server.__dict__)

    def test_cached_gain_still_forces_mute_and_next_local_speech_sets_correct_volume(self):
        _namespace, server, original, _idle, _messages = self.hooked()
        voice = Voice(gain=5)
        server._speak('TEST', voice, callback=lambda *a: None)
        self.assertEqual(server._client.queued[0][0], -100)
        self.assertEqual(server._client.volume, 40)
        original(server, 'LOCAL TEST', Voice(gain=8))
        self.assertEqual(server._client.queued[-1][0], 85)

    def test_ordinary_remote_speech_is_not_synthesized_locally(self):
        _namespace, server, _original, _idle, messages = self.hooked()
        server._speak('TEST', None)
        self.assertEqual(len(messages), 1)
        self.assertEqual(server._client.queued, [])
        self.assertEqual(server._client.volume_changes, [])

    def test_native_end_advances_iterator_without_manufacturing_callbacks(self):
        _namespace, server, _original, idle, messages = self.hooked()
        contexts = [SimpleNamespace(utterance='FIRST', startOffset=0, endOffset=5),
                    SimpleNamespace(utterance='SECOND', startOffset=5, endOffset=11)]
        consumed, progress = [], []

        def iterator():
            for context in contexts:
                consumed.append(context)
                yield context, Voice(gain=5)

        server._say_all(iterator(), lambda context, kind: progress.append((context, kind)))
        self.assertEqual(len(consumed), 1)
        self.assertEqual(idle, [])
        callback = server._client.queued[0][2]['callback']
        callback('END')
        while idle:
            func, args = idle.pop(0)
            func(*args)
        self.assertEqual(len(consumed), 2)
        self.assertEqual(len(messages), 2)
        self.assertTrue(all(item[0] == -100 for item in server._client.queued))
        self.assertEqual(progress, [(contexts[0], 2)])
        self.assertEqual(contexts[0].currentOffset, 5)

    def test_native_cancel_reports_interruption_without_advancing(self):
        _namespace, server, _original, idle, messages = self.hooked()
        context = SimpleNamespace(utterance='FIRST', startOffset=0, endOffset=5)
        progress = []
        server._say_all(iter([(context, Voice(gain=5)), (context, Voice(gain=5))]),
                        lambda context, kind: progress.append(kind))
        server._client.queued[0][2]['callback']('CANCEL')
        while idle:
            func, args = idle.pop(0)
            func(*args)
        self.assertEqual(progress, [1])
        self.assertEqual(len(messages), 1)

    def test_native_index_mark_updates_caret_offsets(self):
        _namespace, server, _original, idle, _messages = self.hooked()
        context = SimpleNamespace(utterance='FIRST', startOffset=10, endOffset=15)
        server._say_all(iter([(context, Voice(gain=5))]), lambda *a: None)
        server._client.queued[0][2]['callback']('INDEX_MARK', index_mark='1:4')
        while idle:
            func, args = idle.pop(0)
            func(*args)
        self.assertEqual((context.currentOffset, context.currentEndOffset), (11, 14))

    def test_backend_reset_mutes_and_restores_both_clients(self):
        _namespace, server, _original, _idle, _messages = self.hooked()
        first, replacement = server._client, NativeClient(volume=25)

        def reset_during_native_speak(*args):
            server._client = replacement
            server._current_voice_properties = {'gain': 8}
            server._send_command(replacement.set_volume, 85)

        server._debug_sd_values = reset_during_native_speak
        server._speak('TEST', Voice(gain=8), callback=lambda *a: None)
        self.assertEqual(replacement.queued[0][0], -100)
        self.assertEqual(first.volume, 40)
        self.assertEqual(replacement.volume, 25)
        self.assertNotIn('gain', server._current_voice_properties)
        self.assertNotIn('_send_command', server.__dict__)

    def test_native_exception_restores_volume_and_existing_instance_method(self):
        _namespace, server, _original, _idle, _messages = self.hooked()
        previous = server._send_command
        server._send_command = previous

        def fail(*args):
            raise RuntimeError('synthetic failure')

        server._debug_sd_values = fail
        server._speak('TEST', Voice(gain=8), callback=lambda *a: None)
        self.assertIs(server.__dict__['_send_command'], previous)
        self.assertEqual(server._client.volume, 40)
        self.assertEqual(server._client.queued, [])

    def test_native_send_command_reset_keeps_old_and_new_clients_silent(self):
        _namespace, server, _original, _idle, messages = self.hooked()
        first, replacement = server._client, NativeClient(volume=25)
        first.fail_once = True

        def reset():
            server._client = replacement
            server._current_voice_properties = {}
            server._send_command(replacement.set_volume, 85)

        server.reset = reset
        server._speak('TEST', Voice(gain=8), callback=lambda *a: None)
        self.assertEqual(len(messages), 1)
        self.assertEqual(first.queued[0][0], -100)
        self.assertEqual(first.volume, 40)
        self.assertEqual(replacement.volume, 25)
        self.assertNotIn('gain', server._current_voice_properties)
        self.assertNotIn('_send_command', server.__dict__)

    def test_volume_failure_has_no_audible_fallback_or_fabricated_events(self):
        _namespace, server, _original, idle, _messages = self.hooked()
        calls, native_entered = [], []
        server._debug_sd_values = lambda *args: native_entered.append(True)

        def fail_mute(value):
            calls.append(value)
            if value == -100:
                raise RuntimeError('synthetic mute failure')
            server._client.volume = value

        server._client.set_volume = fail_mute
        server._speak('TEST', None, callback=lambda *a: self.fail('fabricated callback'))
        self.assertEqual(calls, [-100, 40])
        self.assertEqual(server._client.queued, [])
        self.assertEqual(idle, [])
        self.assertEqual(native_entered, [])
        self.assertNotIn('_send_command', server.__dict__)

    def test_restore_failure_invalidates_gain_for_the_next_local_utterance(self):
        _namespace, server, original, _idle, _messages = self.hooked()
        native_set_volume = server._client.set_volume

        def fail_restore(value):
            if value == 40:
                raise RuntimeError('synthetic restoration failure')
            native_set_volume(value)

        server._client.set_volume = fail_restore
        server._speak('TEST', Voice(gain=8), callback=lambda *a: None)
        self.assertEqual(server._client.queued[0][0], -100)
        self.assertEqual(server._client.volume, -100)
        self.assertNotIn('gain', server._current_voice_properties)
        self.assertNotIn('_send_command', server.__dict__)
        original(server, 'LOCAL TEST', Voice(gain=8))
        self.assertEqual(server._client.queued[-1][0], 85)

    def test_native_exception_after_client_swap_restores_both_clients(self):
        _namespace, server, _original, idle, _messages = self.hooked()
        first, replacement = server._client, NativeClient(volume=25)

        def fail_after_reset(*args):
            server._client = replacement
            server._current_voice_properties = {'gain': 8}
            server._send_command(replacement.set_volume, 85)
            raise RuntimeError('synthetic failure after reset')

        server._debug_sd_values = fail_after_reset
        server._speak('TEST', Voice(gain=8), callback=lambda *a: self.fail('fabricated event'))
        self.assertEqual(first.volume, 40)
        self.assertEqual(replacement.volume, 25)
        self.assertEqual(first.queued, [])
        self.assertEqual(replacement.queued, [])
        self.assertEqual(idle, [])
        self.assertNotIn('gain', server._current_voice_properties)
        self.assertNotIn('_send_command', server.__dict__)

    def test_worker_thread_and_unknown_native_api_are_not_synthesized(self):
        namespace, server, original, _idle, _messages = self.hooked()
        helper = namespace['_linux_rdaccess_silent_callback_speech']
        worker = threading.Thread(target=lambda: helper(
            original, server, 'TEST', None, callback=lambda *a: self.fail('unexpected callback')))
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(server._client.queued, [])
        self.assertEqual(server._client.volume_changes, [])
        self.assertNotIn('_send_command', server.__dict__)
        helper(lambda *a, **kw: self.fail('unknown backend invoked'), server,
               'TEST', None, callback=lambda *a: None)
        server._client.get_volume = lambda: None
        helper(original, server, 'TEST', None, callback=lambda *a: None)
        self.assertEqual(server._client.queued, [])

    def test_pref_upgrade_and_both_markers_are_validated_and_idempotent(self):
        source = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "old-key"
connection_type = "slave"
LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH = True
''' + remote_access._CUSTOMIZATION_SPEECH_FORWARD_SOURCE + remote_access._LOCAL_SPEECH_PREF_HOOK_V3
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orca-customizations.py'
            path.write_text(source)
            config = remote_access.RemoteAccessConfig(key='new-key')
            remote_access.update_legacy_orca_customizations(config, path)
            text = path.read_text()
            self.assertTrue(remote_access.legacy_customization_say_all_callback_patch_current(text))
            self.assertTrue(remote_access.legacy_customization_speech_sequence_patch_current(text))
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), text)
            for tampered in (text.replace('current.set_volume(-100)', 'current.set_volume(-35)'),
                             text.replace(remote_access._LOCAL_SPEECH_PREF_HOOK,
                                          remote_access._LOCAL_SPEECH_PREF_HOOK_V3),
                             text.replace('if not callable(kw.get("callback")):', 'if True:')):
                self.assertFalse(remote_access.legacy_customization_say_all_callback_patch_current(tampered))
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    remote_access._patch_legacy_customization_say_all_callbacks(tampered)


if __name__ == '__main__':
    unittest.main()
