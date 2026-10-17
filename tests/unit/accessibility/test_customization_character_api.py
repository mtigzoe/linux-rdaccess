"""Legacy customization startup and character forwarding across Orca APIs."""
from pathlib import Path
import tempfile
import unittest

from linux_rdaccess_core.connection import remote_access


# The two hook statements and wrapper call from pinned Orca Remote d273e82.
CHARACTER_HOOK = '''old_speakCharacter = SpeechServer.speak_character
def my_speak_character(self, character, acss=None, *args, **kw):
    forwarded.append(character)
    return old_speakCharacter(self, character, acss, *args, **kw)
SpeechServer.speak_character = my_speak_character
'''
CONFIG = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "host"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "key"
connection_type = "slave"
'''


class CustomizationCharacterApiTests(unittest.TestCase):
    def patched(self, source=CHARACTER_HOOK):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "orca-customizations.py"
            path.write_text(CONFIG + source, encoding="utf-8")
            config = remote_access.RemoteAccessConfig(host="host", key="key")
            remote_access.update_legacy_orca_customizations(config, path)
            first = path.read_text(encoding="utf-8")
            remote_access.update_legacy_orca_customizations(config, path)
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertEqual(path.with_name(path.name + ".linux-rdaccess-backup")
                             .read_text(encoding="utf-8"), CONFIG + source)
            return first

    def test_orca42_startup_hooks_the_native_camel_case_method(self):
        native = []
        class SpeechServer:
            def speakCharacter(self, character, acss=None):
                native.append((character, acss))
                return "native-result"
        namespace = {"SpeechServer": SpeechServer, "forwarded": []}
        exec(self.patched(), namespace)
        self.assertEqual(SpeechServer().speakCharacter("\U0001f642", "voice"), "native-result")
        self.assertEqual(namespace["forwarded"], ["\U0001f642"])
        self.assertEqual(native, [("\U0001f642", "voice")])
        self.assertFalse(hasattr(SpeechServer, "speak_character"))

    def test_modern_orca_prefers_snake_case_without_evaluating_camel_case(self):
        native = []
        class SpeechServer:
            def speak_character(self, character, acss=None):
                native.append((character, acss))
                return "native-result"
        namespace = {"SpeechServer": SpeechServer, "forwarded": []}
        exec(self.patched(), namespace)
        self.assertEqual(SpeechServer().speak_character("a"), "native-result")
        self.assertEqual(namespace["forwarded"], ["a"])
        self.assertEqual(native, [("a", None)])
        self.assertFalse(hasattr(SpeechServer, "speakCharacter"))

    def test_existing_camel_case_hook_is_preserved(self):
        source = CHARACTER_HOOK.replace("SpeechServer.speak_character", "SpeechServer.speakCharacter")
        self.assertIn(source, self.patched(source))

    def test_both_api_names_hook_only_the_preferred_snake_case_method(self):
        native = []
        class SpeechServer:
            def speak_character(self, character, acss=None):
                native.append("modern:" + character)
            def speakCharacter(self, character, acss=None):
                native.append("legacy:" + character)
        namespace = {"SpeechServer": SpeechServer, "forwarded": []}
        exec(self.patched(), namespace)
        SpeechServer().speak_character("a")
        SpeechServer().speakCharacter("b")
        self.assertEqual(namespace["forwarded"], ["a"])
        self.assertEqual(native, ["modern:a", "legacy:b"])

    def test_unicode_comments_and_string_literals_are_not_rewritten(self):
        prefix = '# \U0001f642 SpeechServer.speak_character\nlabel = "SpeechServer.speak_character"\n'
        patched = self.patched(prefix + CHARACTER_HOOK)
        self.assertIn(prefix, patched)
        self.assertEqual(remote_access._patch_legacy_customization_character_api(patched), patched)

    def test_unsupported_character_hook_is_rejected_before_writing(self):
        for source in (
            CHARACTER_HOOK.replace("= my_speak_character", "= different_wrapper"),
            CHARACTER_HOOK.replace("old_speakCharacter =", "different_original ="),
            CHARACTER_HOOK + "extra = SpeechServer.speak_character\n",
            "_linux_rdaccess_character_method = 'conflict'\n" + CHARACTER_HOOK,
        ):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "orca-customizations.py"
                path.write_text(CONFIG + source, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "character"):
                    remote_access.update_legacy_orca_customizations(
                        remote_access.RemoteAccessConfig(host="host", key="key"), path)
                self.assertEqual(path.read_text(encoding="utf-8"), CONFIG + source)


if __name__ == "__main__":
    unittest.main()
