"""Exercise simulated routing through a real GTK provider in a private desktop."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("LRD_GUI_PRIVATE"),
    "Requires the GUI runner's private Xvfb and D-Bus environment",
)
class NativeRoutingSimulatorTests(unittest.TestCase):
    def test_preview_then_one_guarded_route_with_event_and_readback(self):
        from tools.diagnostics import real_gui_atspi_smoke as gui

        gui.verify_private_display()
        session = gui.Session(Path(os.environ["LRD_GUI_PRIVATE"]))
        try:
            session.launch("wm", ["xfwm4", "--replace", "--compositor=off"])
            process = session.launch(
                "routing-fixture", [sys.executable, "-B", "tests/apps/accessibility_smoke_app.py"]
            )

            def owned_app():
                desktop = session.Atspi.get_desktop(0)
                for index in range(desktop.get_child_count()):
                    app = desktop.get_child_at_index(index)
                    if app is not None and app.get_process_id() == process.pid:
                        return app
                return None

            app = session.wait(owned_app, "owned public GTK fixture")
            session.activate(app)
            editor = session.wait(
                lambda: session.find(app, {"text", "entry"}, name="Account name"),
                "public fixture entry",
            )
            session.focus(editor)
            text = editor.get_text_iface()
            self.assertTrue(text.set_caret_offset(2))
            session.wait(lambda: text.get_caret_offset() == 2, "initial caret")
            while session.context.pending():
                session.context.iteration(False)

            def command(*extra):
                result = subprocess.run(
                    [sys.executable, "-B", "diagnostics/atspi/simulate_routing.py",
                     "--application", "gtk-fixture", "--offset", "7", *extra],
                    capture_output=True, text=True, timeout=15,
                )
                return result.returncode, [json.loads(line) for line in result.stdout.splitlines()]

            code, records = command()
            self.assertEqual(code, 0)
            preview = records[-1]
            self.assertFalse(preview["caret_write_attempted"])
            self.assertEqual(text.get_caret_offset(), 2)
            guards = ["--apply", "--expect-pid", str(process.pid), "--expect-caret", "2",
                      "--expect-count", str(preview["target"]["character_count"]), "--duration", "1"]
            code, records = command(*guards)
            self.assertEqual(code, 0)
            result = records[-1]
            self.assertTrue(result["caret_readback_matches"])
            self.assertEqual(result["setter_reasons"], ["setter_returned"])
            self.assertEqual(text.get_caret_offset(), 7)
            self.assertTrue(any(event.get("caret_offset") == 7
                                for event in result["observation"]["events"]))
            self.assertEqual(result["physical_braille"], "unverified")
            self.assertEqual(records[0]["observer"], "ready")
            # Stale preview is rejected; do not silently replay an old route.
            code, records = command(*guards)
            self.assertEqual(code, 2)
            self.assertEqual(records[-1]["simulator"], "unavailable_or_refused")
            self.assertEqual(text.get_caret_offset(), 7)
            print(json.dumps({"environment": "isolated-test", "simulation": result}), flush=True)
        finally:
            session.close()
