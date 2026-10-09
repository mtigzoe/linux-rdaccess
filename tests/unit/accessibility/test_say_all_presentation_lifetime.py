"""Remote Say All must expire when Orca activates another script or window."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import remote_access
from tests.shared.test_compat_lifecycle import Harness
from tests.unit.accessibility import test_customization_say_all_callbacks as callbacks

Voice = callbacks.Voice


class SayAllPresentationLifetimeTests(Harness, unittest.TestCase):
    native = callbacks.SayAllCallbacksTests.native
    hooked = callbacks.SayAllCallbacksTests.hooked

    def runtime(self):
        namespace, server, original, idle, messages = self.hooked()
        state = original.__globals__["orca_state"]
        state.activeWindow = object()
        state.lastInputEvent = object()
        text = mock.Mock()
        text.getText.return_value = "x"
        text.getNSelections.return_value = 1
        target = SimpleNamespace(queryText=mock.Mock(return_value=text))
        state.locusOfFocus = target
        orca = SimpleNamespace(
            emitRegionChanged=mock.Mock(), SAY_ALL=object(),
            setLocusOfFocus=mock.Mock(side_effect=lambda event, obj, **kwargs:
                                     setattr(state, "locusOfFocus", obj)),
        )
        native = {
            "__name__": "orca.scripts.default", "orca": orca, "orca_state": state,
            "speechserver": original.__globals__["speechserver"],
            "input_event": SimpleNamespace(KeyboardEvent=type("KeyboardEvent", (), {})),
        }
        fixture = Path(__file__).resolve().parents[2] / "fixtures/orca42-default-say-all-methods.py"
        exec(compile(fixture.read_text(), str(fixture), "exec"), native)
        script = native["Script"]()
        script.utilities = SimpleNamespace(adjustForPronunciation=lambda text: text)
        script.EMBEDDED_OBJECT_CHARACTER = "\ufffc"
        script._inSayAll = True
        script._sayAllContexts = [target]
        script._sayAllIsInterrupted = False
        state.activeScript = script
        contexts = [SimpleNamespace(
            obj=target, utterance=utterance, startOffset=start, endOffset=end,
            currentOffset=start, currentEndOffset=None,
        ) for utterance, start, end in (("FIRST", 0, 5), ("SECOND", 5, 11))]
        return namespace, server, idle, messages, state, script, contexts, text, orca

    @staticmethod
    def drain(idle):
        while idle:
            func, args = idle.pop(0)
            func(*args)

    def start(self, server, idle, script, contexts):
        server.sayAll(iter((context, Voice(gain=5)) for context in contexts),
                      script._Script__sayAllProgressCallback)
        func, args = idle.pop(0)
        func(*args)

    @staticmethod
    def move_context(state, change):
        if change == "script":
            state.activeScript = SimpleNamespace(
                utilities=SimpleNamespace(adjustForPronunciation=lambda text: text),
            )
        else:
            state.activeWindow = object()
        state.locusOfFocus = object()

    def test_activation_change_expires_queued_end_and_next_utterance(self):
        for change in ("script", "window"):
            with self.subTest(change=change):
                _, server, idle, messages, state, script, contexts, text, orca = self.runtime()
                self.start(server, idle, script, contexts)
                server._client.queued[0][2]["callback"]("end")
                self.move_context(state, change)
                new_focus = state.locusOfFocus
                self.drain(idle)
                self.assertEqual([message["sequence"] for message in messages], [["FIRST"]])
                self.assertIs(state.locusOfFocus, new_focus)
                text.setCaretOffset.assert_not_called()
                text.setSelection.assert_not_called()
                orca.setLocusOfFocus.assert_not_called()
                orca.emitRegionChanged.assert_not_called()
                self.assertFalse(script._inSayAll)
                self.assertEqual(script._sayAllContexts, [])

    def test_activation_change_rejects_late_cancel_caret_and_selection_updates(self):
        for change in ("script", "window"):
            with self.subTest(change=change):
                namespace, server, idle, _, state, script, contexts, text, orca = self.runtime()
                self.start(server, idle, script, contexts)
                namespace["old_stop"](server)
                self.move_context(state, change)
                server._client.queued[0][2]["callback"]("cancel")
                self.drain(idle)
                text.setCaretOffset.assert_not_called()
                text.setSelection.assert_not_called()
                orca.emitRegionChanged.assert_not_called()
                self.assertFalse(script._inSayAll)
                self.assertEqual(script._sayAllContexts, [])

    def test_activation_change_rejects_late_index_mark_presentation(self):
        _, server, idle, _, state, script, contexts, _, orca = self.runtime()
        self.start(server, idle, script, contexts)
        server._client.queued[0][2]["callback"]("index_marks", index_mark="1:4")
        self.move_context(state, "script")
        self.drain(idle)
        orca.emitRegionChanged.assert_not_called()
        self.assertFalse(script._inSayAll)

    def test_activation_change_before_first_idle_never_starts_the_iterator(self):
        for change in ("script", "window"):
            with self.subTest(change=change):
                _, server, idle, messages, state, script, contexts, _, _ = self.runtime()
                consumed = []

                def chunks():
                    consumed.append(True)
                    yield contexts[0], Voice(gain=5)

                server.sayAll(chunks(), script._Script__sayAllProgressCallback)
                self.move_context(state, change)
                self.drain(idle)
                self.assertEqual(consumed, [])
                self.assertEqual(messages, [])
                self.assertEqual(server._client.queued, [])
                self.assertFalse(script._inSayAll)

    def test_expired_run_does_not_revive_when_the_original_window_returns(self):
        _, server, idle, _, state, script, contexts, text, orca = self.runtime()
        window = state.activeWindow
        self.start(server, idle, script, contexts)
        callback = server._client.queued[0][2]["callback"]
        self.move_context(state, "window")
        callback("index_marks", index_mark="1:4")
        self.drain(idle)
        orca.emitRegionChanged.reset_mock()
        state.activeWindow = window
        callback("cancel")
        self.drain(idle)
        text.setCaretOffset.assert_not_called()
        text.setSelection.assert_not_called()
        orca.emitRegionChanged.assert_not_called()

    def test_unchanged_script_and_window_keep_native_completion_and_caret_tracking(self):
        _, server, idle, messages, state, script, contexts, text, orca = self.runtime()
        self.start(server, idle, script, contexts)
        # Say All itself changes locusOfFocus between text objects. This must
        # remain valid while the owning script and top-level window are current.
        state.locusOfFocus = object()
        server._client.queued[0][2]["callback"]("end")
        self.drain(idle)
        self.assertEqual([message["sequence"] for message in messages], [["FIRST"], ["SECOND"]])
        orca.setLocusOfFocus.assert_called_once_with(None, contexts[0].obj, notifyScript=False)
        text.setCaretOffset.assert_called_once_with(5)
        text.setSelection.assert_called_once_with(0, 5, 5)

    def test_unchanged_context_retains_native_interruption_cleanup(self):
        namespace, server, idle, _, _, script, contexts, text, _ = self.runtime()
        self.start(server, idle, script, contexts)
        namespace["old_stop"](server)
        server._client.queued[0][2]["callback"]("cancel")
        self.drain(idle)
        text.setCaretOffset.assert_called_once_with(0)
        text.setSelection.assert_called_once_with(0, 0, 0)
        self.assertFalse(script._inSayAll)

    def test_equivalent_window_proxies_keep_the_current_run(self):
        class Window:
            def __eq__(self, other):
                return isinstance(other, Window)

        _, server, idle, messages, state, script, contexts, text, _ = self.runtime()
        state.activeWindow = Window()
        self.start(server, idle, script, contexts)
        # AT-SPI can expose another Python proxy for the same accessible.
        state.activeWindow = Window()
        server._client.queued[0][2]["callback"]("end")
        self.drain(idle)
        self.assertEqual([message["sequence"] for message in messages], [["FIRST"], ["SECOND"]])
        text.setCaretOffset.assert_called_once_with(5)

    def test_historical_hooks_upgrade_privately_and_keep_the_original_backup(self):
        original = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "test.invalid"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "synthetic"
connection_type = "slave"
''' + remote_access._CUSTOMIZATION_SPEECH_FORWARD_SOURCE
        for historical in (
            remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK_V1,
            remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK_V2,
            remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK_V3,
            remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK_V4,
        ):
            with self.subTest(marker=historical.splitlines()[0]), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "orca-customizations.py"
                path.write_text(original)
                config = remote_access.RemoteAccessConfig(key="synthetic")
                remote_access.update_legacy_orca_customizations(config, path)
                path.write_text(path.read_text().replace(
                    remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK, historical))
                remote_access.update_legacy_orca_customizations(config, path)
                upgraded = path.read_text()
                self.assertTrue(remote_access.legacy_customization_say_all_callback_patch_current(upgraded))
                self.assertNotIn(historical.splitlines()[0], upgraded)
                backup = path.with_name(path.name + ".linux-rdaccess-backup")
                self.assertEqual(backup.read_text(), original)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
                remote_access.update_legacy_orca_customizations(config, path)
                self.assertEqual(path.read_text(), upgraded)
                self.assertEqual(backup.read_text(), original)

    def test_tampered_old_and_current_lifetime_guards_leave_files_untouched(self):
        source = remote_access._patch_legacy_customization_speech_sequence(
            remote_access._CUSTOMIZATION_SPEECH_FORWARD_SOURCE)
        source += "\n" + remote_access._LOCAL_SPEECH_PREF_HOOK
        source = remote_access._patch_legacy_customization_say_all_callbacks(source)
        source = '''YOUR_NVDAREMOTE_SERVER_ADDRESS = "test.invalid"
YOUR_NVDAREMOTE_SERVER_PORT = 6837
YOUR_NVDAREMOTE_KEY = "synthetic"
connection_type = "slave"
''' + source
        for corrupted in (
            source.replace(remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK,
                           remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK_V3)
                  .replace("while current():", "while True:"),
            source.replace(remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK,
                           remote_access._CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK_V4)
                  .replace("while current():", "while True:"),
            source.replace("context_valid and active_script is originating_script", "True"),
            source.replace('getattr(owner, "_lrd_braille_route_epoch", 0)', '0'),
            source + "\n_linux_rdaccess_wrap_say_all = another\n",
        ):
            with self.subTest(marker=corrupted[-80:]), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "orca-customizations.py"
                path.write_text(corrupted)
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    remote_access.update_legacy_orca_customizations(
                        remote_access.RemoteAccessConfig(key="replacement"), path)
                self.assertEqual(path.read_text(), corrupted)
                self.assertFalse(path.with_name(path.name + ".linux-rdaccess-backup").exists())


if __name__ == "__main__":
    unittest.main()
