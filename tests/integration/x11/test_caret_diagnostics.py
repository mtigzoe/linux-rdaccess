"""Native GTK caret diagnostics in an owned Xvfb/D-Bus session, with no keys."""

import os
import sys
import unittest
from pathlib import Path

from linux_rdaccess_core.accessibility.a11y_model import set_caret_offset
from linux_rdaccess_core.caret_diagnostics import CaretReason
from linux_rdaccess_core.routing_observer import RoutingObservation


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("LRD_GUI_PRIVATE"),
    "Requires the GUI runner's private Xvfb and D-Bus environment",
)
class NativeCaretDiagnosticsTests(unittest.TestCase):
    def test_real_provider_reason_event_and_readback_without_keyboard(self):
        from tools.diagnostics import real_gui_atspi_smoke as gui

        gui.verify_private_display()
        session = gui.Session(Path(os.environ["LRD_GUI_PRIVATE"]))
        try:
            process = session.launch(
                "caret-fixture",
                [sys.executable, "-B", "tests/apps/accessibility_smoke_app.py"],
            )

            def owned_app():
                desktop = session.Atspi.get_desktop(0)
                for index in range(desktop.get_child_count()):
                    app = desktop.get_child_at_index(index)
                    if app is not None and app.get_process_id() == process.pid:
                        return app
                return None

            app = session.wait(owned_app, "owned GTK fixture")
            entry = session.wait(
                lambda: session.find(app, {"text", "entry"}, name="Account name"),
                "public entry",
            )
            text = entry.get_text_iface()
            self.assertTrue(text.set_caret_offset(2))
            session.wait(lambda: text.get_caret_offset() == 2, "initial provider caret")
            while session.context.pending():
                session.context.iteration(False)
            snapshot = {"object": entry, "role": "text"}
            observation = RoutingObservation(snapshot)
            listener = session.Atspi.EventListener.new(observation.event)
            self.assertTrue(listener.register("object:text-caret-moved"))
            reasons, stops, results = [], [], []
            loop = session.GLib.MainLoop()

            def route_fixture():
                results.append(
                    set_caret_offset(
                        entry,
                        7,
                        before_action=lambda: stops.append("before"),
                        diagnostic=reasons.append,
                    )
                )
                return False

            try:
                session.GLib.timeout_add(100, route_fixture)
                session.GLib.timeout_add(800, lambda: (loop.quit(), False)[1])
                loop.run()
            finally:
                listener.deregister("object:text-caret-moved")
            result = observation.finish(snapshot)
            self.assertEqual(results, [True])
            self.assertEqual(reasons, [CaretReason.SETTER_RETURNED])
            self.assertEqual(stops, ["before"])
            self.assertEqual((result["before_caret"], result["after_caret"]), (2, 7))
            self.assertTrue(
                any(event.get("caret_offset") == 7 for event in result["events"])
            )
            self.assertEqual(result["dropped_events"], 0)
            self.assertFalse(set_caret_offset(entry, 8193, diagnostic=reasons.append))
            self.assertEqual(reasons[-1], CaretReason.INVALID_OFFSET)
            self.assertEqual(text.get_caret_offset(), 7)
            self.assertEqual(stops, ["before"])
        finally:
            session.close()
