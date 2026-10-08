"""Bridge tests that need the Atspi typelib (skipped where it is missing). No AT-SPI bus is needed."""

import logging
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

try:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import GLib

    import atspi_nvda_bridge as bridge
except (ImportError, ValueError) as exc:  # pragma: no cover
    raise unittest.SkipTest(f"Atspi not available: {exc}")

ROOT = Path(__file__).resolve().parents[3]


class FakeAccessible:
    def __init__(self, name="", role="push button", raises=None):
        self._name, self._role, self._raises = name, role, raises

    def get_name(self):
        if self._raises:
            raise self._raises
        return self._name

    def get_role_name(self):
        return self._role

    def get_description(self):
        return ""

    def get_state_set(self):
        raise AssertionError("not used in these tests")


class FakeEvent:
    def __init__(self, type, detail1=1, source=None, any_data=None):
        self.type, self.detail1, self.source, self.any_data = type, detail1, source, any_data


class RecordingLink:
    ready = True

    def __init__(self):
        self.spoken = []

    def speak(self, text, interrupt=False):
        self.spoken.append((text, interrupt))
        return True

    def poll(self):
        pass

    def close(self):
        pass


class BridgeEventTests(unittest.TestCase):
    def test_dry_run_output_does_not_persist_speech(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            bridge.DryRunLink().speak('private-speech-text', interrupt=True)
        self.assertNotIn('private-speech-text', output.getvalue())
        self.assertIn('speak', output.getvalue())

    def test_debugging_does_not_log_application_text_or_exceptions(self):
        logging.disable(logging.NOTSET)
        self.addCleanup(logging.disable, logging.CRITICAL)
        b, link = self.make()
        secret = 'private-application-text'
        with self.assertLogs('bridge', level='DEBUG') as logs:
            b._on_event(FakeEvent('object:state-changed:focused', 1, FakeAccessible(secret)))
            b._on_event(FakeEvent('object:state-changed:focused', 1, FakeAccessible(raises=RuntimeError(secret))))
            b._on_event(FakeEvent('object:state-changed:focused', 1, FakeAccessible(raises=GLib.Error(secret))))
        self.assertNotIn(secret, str(logs.output))
        self.assertEqual(link.spoken, [(secret + ', push button', True)])

    def make(self, **kw):
        link = RecordingLink()
        return bridge.Bridge(link, **kw), link

    def test_focus_event_is_spoken_with_interrupt(self):
        b, link = self.make()
        b._on_event(FakeEvent("object:state-changed:focused", 1, FakeAccessible("Save")))
        self.assertEqual(link.spoken, [("Save, push button", True)])

    def test_no_interrupt_flag_suppresses_cancel(self):
        b, link = self.make(interrupt=False)
        b._on_event(FakeEvent("object:state-changed:focused", 1, FakeAccessible("Save")))
        self.assertEqual(link.spoken, [("Save, push button", False)])

    def test_geometry_noise_is_ignored(self):
        b, link = self.make()
        b._on_event(FakeEvent("object:bounds-changed", 0, FakeAccessible("Save")))
        self.assertEqual(link.spoken, [])

    def test_active_descendant_uses_any_data_child(self):
        b, link = self.make()
        b._on_event(
            FakeEvent(
                "object:active-descendant-changed",
                0,
                FakeAccessible("Fruit", "table"),
                any_data=FakeAccessible("Apples", "table cell"),
            )
        )
        self.assertEqual(link.spoken, [("Apples, table cell", True)])

    def test_dead_application_is_swallowed(self):
        """An app that exits mid-event raises GLib.Error; that must not escape into the main loop."""
        b, link = self.make()
        gone = FakeAccessible(raises=GLib.Error("The application no longer exists"))
        b._on_event(FakeEvent("object:state-changed:focused", 1, gone))
        self.assertEqual(link.spoken, [])

    def test_unexpected_error_is_swallowed_and_logged(self):
        logging.disable(logging.NOTSET)  # tests/__init__.py silences logging; this test needs it
        self.addCleanup(logging.disable, logging.CRITICAL)
        b, link = self.make()
        with self.assertLogs("bridge", level="ERROR"):
            b._on_event(FakeEvent("object:state-changed:focused", 1, FakeAccessible(raises=ValueError("boom"))))
        self.assertEqual(link.spoken, [])


class SignalTests(unittest.TestCase):
    def run_script(self, code: str):
        return subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=15
        )

    def test_sigterm_stops_an_idle_main_loop(self):
        """Regression: signal.signal + Atspi.event_quit() never ran while Atspi.event_main() was idle."""
        code = (
            "import os, signal\n"
            "from gi.repository import GLib\n"
            "import atspi_nvda_bridge as b\n"
            "loop = GLib.MainLoop()\n"
            "b.install_signal_handlers(loop)\n"
            "GLib.timeout_add(100, lambda: (os.kill(os.getpid(), signal.SIGTERM), False)[1])\n"
            "GLib.timeout_add_seconds(5, lambda: (print('TIMEOUT'), loop.quit(), False)[2])\n"
            "loop.run()\n"
            "print('CLEAN')\n"
        )
        result = self.run_script(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLEAN", result.stdout)
        self.assertNotIn("TIMEOUT", result.stdout)

    def test_sigint_also_stops_the_loop(self):
        code = (
            "import os, signal\n"
            "from gi.repository import GLib\n"
            "import atspi_nvda_bridge as b\n"
            "loop = GLib.MainLoop()\n"
            "b.install_signal_handlers(loop)\n"
            "GLib.timeout_add(100, lambda: (os.kill(os.getpid(), signal.SIGINT), False)[1])\n"
            "GLib.timeout_add_seconds(5, lambda: (print('TIMEOUT'), loop.quit(), False)[2])\n"
            "loop.run()\n"
            "print('CLEAN')\n"
        )
        result = self.run_script(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("TIMEOUT", result.stdout)


if __name__ == "__main__":
    unittest.main()
