"""Isolated stale Say All progress contracts for issue #58.

Execute production-generated wrapper helpers, not a copied model of their logic.
No Orca process, NVDA connection, speech device, or desktop is required.
"""
import ast
import types
import unittest

from linux_rdaccess_core.connection import remote_access


class SayAllStaleProgressTests(unittest.TestCase):
    def setUp(self):
        self.transport = types.SimpleNamespace(connected=True, connection_type="slave")
        self.controller = types.SimpleNamespace(
            _lrd_generation=1, _lrd_speech_epoch=0, _lrd_braille_route_epoch=0)
        self.script = object()
        self.window = object()
        self.state = types.SimpleNamespace(
            activeScript=self.script, activeWindow=self.window)
        namespace = {
            "transport": self.transport, "controller": self.controller,
            "orca_state": self.state,
        }
        # Select only the two production wrapper functions. Other contents
        # of the customization hook initialize real Orca speech adapters.
        tree = ast.parse(remote_access._CUSTOMIZATION_SAY_ALL_LIFECYCLE_HOOK)
        selected = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name in (
                        "_linux_rdaccess_say_all_session",
                        "_linux_rdaccess_wrap_say_all")]
        self.assertEqual(len(selected), 2)
        exec(compile(ast.Module(body=selected, type_ignores=[]),
                     "<generated-say-all-wrapper>", "exec"), namespace)
        exec("def native(server, iterator, callback):\n"
             "    return iterator, callback\n", namespace)
        self.wrapper = namespace["_linux_rdaccess_wrap_say_all"](namespace["native"])
        self.server = types.SimpleNamespace()
        self.events = []

    def start(self):
        def callback(context, kind):
            self.events.append((context, kind))
            return True
        return self.wrapper(self.server, iter(("first", "second")), callback)

    def test_old_end_does_not_run_after_focus_or_window_change(self):
        for changed in ("script", "window"):
            with self.subTest(changed=changed):
                self.setUp()
                iterator, progress = self.start()
                self.assertEqual(next(iterator), "first")
                if changed == "script":
                    self.state.activeScript = object()
                else:
                    self.state.activeWindow = object()
                self.assertFalse(progress("old", "END"))
                self.assertEqual(self.events, [])
                with self.assertRaises(StopIteration):
                    next(iterator)

    def test_old_end_cannot_resume_after_disconnect_and_reconnect(self):
        iterator, progress = self.start()
        self.assertEqual(next(iterator), "first")
        self.transport.connected = False
        self.controller._lrd_generation += 1
        self.transport.connected = True
        self.assertFalse(progress("old", "END"))
        self.assertEqual(self.events, [])
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_old_end_does_not_run_after_ctrl_speech_epoch_change(self):
        iterator, progress = self.start()
        self.assertEqual(next(iterator), "first")
        self.controller._lrd_speech_epoch += 1
        self.assertFalse(progress("old", "END"))
        self.assertEqual(self.events, [])

    def test_queued_end_is_expired_by_braille_routing_epoch(self):
        iterator, progress = self.start()
        self.assertEqual(next(iterator), "first")
        self.controller._lrd_braille_route_epoch += 1
        self.assertFalse(progress("old", "END"))
        self.assertEqual(self.events, [])
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_focus_change_remains_expired_when_focus_returns_before_callback(self):
        iterator, progress = self.start()
        self.assertEqual(next(iterator), "first")
        old_script = self.state.activeScript
        self.state.activeScript = object()
        self.assertFalse(progress("old", "END"))
        self.state.activeScript = old_script
        # A late END cannot resume a run invalidated by an observed switch.
        self.assertFalse(progress("old-again", "END"))
        self.assertEqual(self.events, [])
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_old_cancel_like_progress_rejected_after_reconnect(self):
        iterator, progress = self.start()
        self.assertEqual(next(iterator), "first")
        self.controller._lrd_generation += 1
        for kind in ("CANCEL", "END"):
            with self.subTest(kind=kind):
                self.assertFalse(progress("old", kind))
        self.assertEqual(self.events, [])

    def test_new_say_all_run_supersedes_queued_old_progress(self):
        _old_iterator, old_progress = self.start()
        new_iterator, new_progress = self.start()
        self.assertFalse(old_progress("old", "END"))
        self.assertTrue(new_progress("new", "END"))
        self.assertEqual(self.events, [("new", "END")])
        self.assertEqual(next(new_iterator), "first")


if __name__ == "__main__":
    unittest.main()
