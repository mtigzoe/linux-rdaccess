"""Native observer check in a runner-owned Xvfb/D-Bus session, never the desktop."""

import json
import os
import sys
import unittest
from pathlib import Path

from linux_rdaccess_core.routing_observer import observe


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("LRD_GUI_PRIVATE"),
    "Requires the GUI runner's private Xvfb and D-Bus environment",
)
class NativeRoutingObserverTests(unittest.TestCase):
    def test_mousepad_caret_events_and_readback(self):
        from diagnostics.x11.live_x11 import Focus
        from tools.diagnostics import real_gui_atspi_smoke as gui

        gui.verify_private_display()
        # Session verifies the private D-Bus daemon's environment before any UI action.
        session = gui.Session(Path(os.environ["LRD_GUI_PRIVATE"]))
        try:
            session.launch("wm", ["xfwm4", "--replace", "--compositor=off"])
            fixture = session.root / "observer-fixture.txt"
            fixture.write_text("alpha bravo charlie\n", encoding="utf-8")
            session.launch("mousepad", ["mousepad", "--disable-server", str(fixture)])
            app = session.application("mousepad")
            session.activate(app)
            editor = session.wait(
                lambda: session.find(
                    app, {"text", "entry"}, predicate=lambda obj: session.state(obj, "EDITABLE")
                ),
                "Mousepad observer fixture editor",
            )
            session.focus(editor)
            text = editor.get_text_iface()
            self.assertTrue(text.set_caret_offset(2))
            session.wait(lambda: text.get_caret_offset() == 2, "Initial fixture caret")
            session.wait(lambda: not session.context.pending(), "Initial caret event delivery")

            routed = []

            def route_fixture():
                # This direct AT-SPI action is only a test stimulus, not NVDA/braille input.
                routed.append(text.set_caret_offset(7))
                return False

            emitted = []

            def ready(item):
                emitted.append(item)
                if item.get("observer") == "ready":
                    session.GLib.timeout_add(100, route_fixture)

            result = observe(Focus(), "mousepad", 1, ready)
            self.assertEqual(routed, [True])
            self.assertEqual((result["before_caret"], result["after_caret"]), (2, 7))
            self.assertTrue(result["same_initial_focus"])
            self.assertFalse(result["focus_changed_during_observation"])
            self.assertTrue(any(item.get("caret_offset") == 7 for item in result["events"]))
            self.assertFalse(emitted[0]["input_sent"])
            print(json.dumps({"environment": "isolated-test", "observation": result}), flush=True)
        finally:
            session.close()
