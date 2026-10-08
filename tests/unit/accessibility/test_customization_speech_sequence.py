"""Orca speech reaches NVDA as utterances rather than a scalar character stream."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import remote_access


UPSTREAM_SPEAK = '''
def my_speak(self, text, acss, **kw):
    # Forward Orca's own speech only while acting as the controlled machine.
    global _want_cancel
    if text and transport.connected and transport.connection_type == "slave":
        if _want_cancel:
            transport.send(type="cancel")
            _want_cancel = False
        transport.send(type="speak", sequence=text)
        return None
    return old_speak(self, text, acss, **kw)
'''


class SpeechSequenceTests(unittest.TestCase):
    def patched(self, *, connected=True, role='slave', pending_cancel=False):
        messages, local = [], []

        def original(*args, **kwargs):
            local.append((args, kwargs))
            return 42

        namespace = {
            'transport': SimpleNamespace(connected=connected, connection_type=role,
                                         send=lambda **kw: messages.append(kw)),
            '_want_cancel': pending_cancel,
            'old_speak': original,
        }
        text = remote_access._patch_legacy_customization_speech_sequence(UPSTREAM_SPEAK)
        exec(compile(text, 'patched-speech-fixture', 'exec'), namespace)
        return namespace, messages, local

    def test_nvda_wire_decoder_receives_one_complete_utterance(self):
        namespace, messages, local = self.patched()
        namespace['my_speak'](None, 'TEST', None)
        packet = json.loads(json.dumps(messages[0]))
        # NVDA's asSequence iterates the wire sequence to reconstruct items.
        decoded_items = [item for item in packet['sequence']]
        self.assertEqual(decoded_items, ['TEST'])
        self.assertEqual(local, [])

    def test_unicode_spaces_and_punctuation_are_preserved(self):
        namespace, messages, _ = self.patched()
        utterance = 'Test café.  αβ\nsecond line!'
        namespace['my_speak'](None, utterance, None)
        self.assertEqual(messages, [{'type': 'speak', 'sequence': [utterance]}])

    def test_existing_sequence_and_commands_are_preserved(self):
        for sequence in (['TEST', ['CharacterModeCommand', {'state': True}], 'A'],
                         ('TEST', 'SECOND')):
            with self.subTest(sequence_type=type(sequence).__name__):
                namespace, messages, _ = self.patched()
                namespace['my_speak'](None, sequence, None)
                self.assertIs(messages[0]['sequence'], sequence)

    def test_pending_cancel_precedes_utterance_and_is_cleared_once(self):
        namespace, messages, _ = self.patched(pending_cancel=True)
        namespace['my_speak'](None, 'FIRST', None)
        namespace['my_speak'](None, 'SECOND', None)
        self.assertEqual([message['type'] for message in messages], ['cancel', 'speak', 'speak'])
        self.assertFalse(namespace['_want_cancel'])

    def test_disconnected_master_and_empty_utterances_preserve_local_call(self):
        callback = lambda: None
        for connected, role, text in ((False, 'slave', 'TEST'),
                                     (True, 'master', 'TEST'),
                                     (True, 'slave', '')):
            with self.subTest(connected=connected, role=role, empty=not text):
                namespace, messages, local = self.patched(connected=connected, role=role)
                server, voice = object(), object()
                self.assertEqual(namespace['my_speak'](server, text, voice, callback=callback), 42)
                self.assertEqual(messages, [])
                self.assertEqual(local, [((server, text, voice), {'callback': callback})])

    def test_idempotent_and_already_list_wrapped_source_is_supported(self):
        for source in (UPSTREAM_SPEAK, UPSTREAM_SPEAK.replace('sequence=text', 'sequence=[text]')):
            result = remote_access._patch_legacy_customization_speech_sequence(source)
            self.assertTrue(remote_access.legacy_customization_speech_sequence_patch_current(result))
            self.assertEqual(remote_access._patch_legacy_customization_speech_sequence(result), result)

    def test_unrelated_calls_comments_and_unicode_are_unchanged(self):
        prefix = '# café sequence=text\n'
        suffix = '\ndef untouched(text):\n    transport.send(sequence=text)\n'
        result = remote_access._patch_legacy_customization_speech_sequence(prefix + UPSTREAM_SPEAK + suffix)
        self.assertTrue(result.startswith(prefix))
        self.assertIn(suffix, result)

    def test_no_wrapper_is_preserved(self):
        source = 'configuration_only = True\n'
        self.assertEqual(remote_access._patch_legacy_customization_speech_sequence(source), source)
        self.assertFalse(remote_access.legacy_customization_speech_sequence_patch_current(source))

    def test_unknown_duplicate_or_shadowed_wrapper_is_refused(self):
        for source in (UPSTREAM_SPEAK.replace('sequence=text', 'sequence=custom(text)'),
                       UPSTREAM_SPEAK + UPSTREAM_SPEAK,
                       UPSTREAM_SPEAK + '\nmy_speak = another_handler\n',
                       UPSTREAM_SPEAK + '\n_linux_rdaccess_speech_sequence = custom\n'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    remote_access._patch_legacy_customization_speech_sequence(source)

    def test_marker_does_not_accept_tampered_helper_or_wrapper(self):
        result = remote_access._patch_legacy_customization_speech_sequence(UPSTREAM_SPEAK)
        for changed in (result.replace('return [text] if isinstance(text, str) else text', 'return text'),
                        result.replace('sequence=_linux_rdaccess_speech_sequence(text)', 'sequence=text'),
                        result + '\n_linux_rdaccess_speech_sequence = lambda text: text\n'):
            self.assertFalse(remote_access.legacy_customization_speech_sequence_patch_current(changed))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                remote_access._patch_legacy_customization_speech_sequence(changed)

    def test_updater_preserves_private_original_backup_and_is_idempotent(self):
        source = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "old-key"
connection_type = "slave"
''' + UPSTREAM_SPEAK
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'orca-customizations.py'
            path.write_text(source)
            config = remote_access.RemoteAccessConfig(key='new-key')
            remote_access.update_legacy_orca_customizations(config, path)
            patched = path.read_text()
            self.assertTrue(remote_access.legacy_customization_speech_sequence_patch_current(patched))
            backup = path.with_name(path.name + '.linux-rdaccess-backup')
            self.assertEqual(backup.read_text(), source)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(backup).st_mode & 0o777, 0o600)
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(), patched)


if __name__ == '__main__':
    unittest.main()
