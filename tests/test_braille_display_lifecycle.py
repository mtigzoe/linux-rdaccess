"""NVDA Remote display information must size Orca's own braille viewport."""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import orca_adapter
from tests.test_compat_lifecycle import Harness


class BrailleDisplayLifecycleTests(Harness, unittest.TestCase):
    def make(self):
        c, _, _ = self._patched_controller(inline=False)
        queue, glib = self._fake_glib()
        calls = []
        braille = types.ModuleType("orca.braille")
        # Orca 42 uses 32 cells when no local BrlAPI display is connected.
        braille._displaySize = [32, 1]
        braille.viewport = [0, 0]
        braille.refresh = lambda *args, **kwargs: calls.append(("refresh", braille._displaySize[0]))

        def pan(event=None):
            braille.viewport[0] += braille._displaySize[0]
            calls.append(("pan", braille.viewport[0]))

        script = types.SimpleNamespace(
            panBrailleRight=pan,
            processRoutingKey=lambda event: calls.append(
                ("route", braille.viewport[0] + event.event["argument"])),
        )
        orca = types.ModuleType("orca")
        orca.braille = braille
        orca.orca_state = types.SimpleNamespace(activeScript=script)
        patches = mock.patch.dict(sys.modules, {
            "orca": orca, "orca.braille": braille,
            "linux_rdaccess_orca_adapter": orca_adapter,
        })
        self.addCleanup(lambda: setattr(orca_adapter, "_REMOTE_BRAILLE_DISPLAY", None))
        return c, queue, glib, patches, braille, calls

    @staticmethod
    def drain(queue):
        while queue:
            queue.pop(0)()

    @staticmethod
    def pan(c):
        c._on_remote_braille_input(scriptPath=[
            "globalCommands", "GlobalCommands", "braille_scrollForward"])

    @staticmethod
    def route(c, index):
        c._on_remote_braille_input(scriptPath=[
            "globalCommands", "GlobalCommands", "braille_routeTo"], routingIndex=index)

    def test_remote_info_sizes_the_native_viewport_before_pan_and_routing(self):
        for width in (40, 80):
            with self.subTest(width=width):
                c, queue, glib, patches, braille, calls = self.make()
                with glib, patches:
                    c._on_remote_braille_info(name="display", numCells=width)
                    self.pan(c)
                    self.route(c, width - 1)
                    self.drain(queue)
                self.assertEqual(braille._displaySize, [width, 1])
                self.assertEqual(calls, [("refresh", width), ("pan", width), ("route", width * 2 - 1)])
                orca_adapter._REMOTE_BRAILLE_DISPLAY = None

    def test_replacement_expires_queued_gestures_and_bounds_new_routing(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            calls.clear()
            self.pan(c)
            self.route(c, 79)
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
            self.assertEqual(calls, [("refresh", 40)])
            self.route(c, 39)
            self.route(c, 40)
            self.drain(queue)
        self.assertEqual(braille._displaySize, [40, 1])
        self.assertEqual(calls, [("refresh", 40), ("route", 39)])

    def test_reset_restores_local_size_and_expires_pending_width_and_routing(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            self.assertEqual(braille._displaySize[0], 80)
            calls.clear()
            c._on_remote_braille_info(numCells=40)
            self.route(c, 39)
            c._linux_rdaccess_reset_keys()
            self.drain(queue)
        self.assertEqual(braille._displaySize, [32, 1])
        self.assertEqual(calls, [("refresh", 32)])

    def test_cleanup_from_old_session_cannot_restore_over_new_display(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            c._linux_rdaccess_reset_keys()
            self.assertTrue(queue, "reset must schedule restoration of the local display width")
            old_cleanup = queue.pop(0)
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
            old_cleanup()
            self.assertEqual(braille._displaySize[0], 40)
            c._linux_rdaccess_reset_keys()
            self.drain(queue)
        self.assertEqual(braille._displaySize, [32, 1])

    def test_invalid_width_does_not_change_display_or_expire_valid_gesture(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
            calls.clear()
            self.pan(c)
            for width in (None, True, False, -1, 1025, 40.5, "40", [], {}):
                c._on_remote_braille_info(name="private-sentinel", numCells=width)
            self.drain(queue)
        self.assertEqual(braille._displaySize[0], 40)
        self.assertEqual(calls, [("pan", 40)])

    def test_unplugged_remote_display_restores_local_size_and_discards_routing(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            calls.clear()
            self.route(c, 7)
            c._on_remote_braille_info(numCells=0)
            self.route(c, 0)
            self.drain(queue)
        self.assertEqual(braille._displaySize, [32, 1])
        self.assertEqual(calls, [("refresh", 32)])

    def test_repeated_info_preserves_queued_command_and_avoids_duplicate_refresh(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
            calls.clear()
            self.pan(c)
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
        self.assertEqual(calls, [("pan", 40)])

    def test_unsupported_width_api_does_not_route_using_guessed_geometry(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches, mock.patch.object(
                orca_adapter.OrcaRuntimeAdapter, "set_remote_braille_width", return_value=False):
            c._on_remote_braille_info(numCells=80)
            self.pan(c)
            self.route(c, 79)
            self.drain(queue)
        self.assertEqual(braille._displaySize[0], 32)
        self.assertEqual(calls, [])

    def test_local_brlapi_reconnect_width_is_preserved_when_remote_display_is_replaced(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            # Orca 42 init() replaces _displaySize when a local display joins.
            braille._displaySize = [20, 1]
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
            c._linux_rdaccess_reset_keys()
            self.drain(queue)
        self.assertEqual(braille._displaySize, [20, 1])

    def test_same_width_local_brlapi_reconnect_is_preserved_on_reset_or_replacement(self):
        for replacement in (None, 40):
            with self.subTest(replacement=replacement):
                c, queue, glib, patches, braille, calls = self.make()
                with glib, patches:
                    c._on_remote_braille_info(numCells=80)
                    self.drain(queue)
                    # The width equals the remote override, but Orca init()
                    # replaced the list because this is a new local display.
                    local_size = braille._displaySize = [80, 1]
                    if replacement is not None:
                        c._on_remote_braille_info(numCells=replacement)
                        self.drain(queue)
                    c._linux_rdaccess_reset_keys()
                    self.drain(queue)
                self.assertIs(braille._displaySize, local_size)
                self.assertEqual(braille._displaySize, [80, 1])
                orca_adapter._REMOTE_BRAILLE_DISPLAY = None

    def test_transient_refresh_failure_can_retry_the_same_width(self):
        c, queue, glib, patches, braille, calls = self.make()
        refresh = braille.refresh
        with glib, patches:
            braille.refresh = mock.Mock(side_effect=RuntimeError("private-sentinel"))
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            self.assertEqual(braille._displaySize, [32, 1])
            self.assertIsNone(orca_adapter._REMOTE_BRAILLE_DISPLAY)
            braille.refresh = refresh
            c._on_remote_braille_info(numCells=80)
            self.pan(c)
            self.route(c, 79)
            self.drain(queue)
            self.assertEqual(calls, [("refresh", 80), ("pan", 80), ("route", 159)])
            c._linux_rdaccess_reset_keys()
            self.drain(queue)
        self.assertEqual(braille._displaySize, [32, 1])

    def test_failed_replacement_keeps_the_previous_owned_width_and_can_retry(self):
        c, queue, glib, patches, braille, calls = self.make()
        refresh = braille.refresh
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
            calls.clear()
            braille.refresh = mock.Mock(side_effect=RuntimeError("private-sentinel"))
            c._on_remote_braille_info(numCells=40)
            self.drain(queue)
            self.assertEqual(braille._displaySize, [80, 1])
            braille.refresh = refresh
            c._on_remote_braille_info(numCells=40)
            self.pan(c)
            self.drain(queue)
            self.assertEqual(calls, [("refresh", 40), ("pan", 40)])
            c._linux_rdaccess_reset_keys()
            self.drain(queue)
        self.assertEqual(braille._displaySize, [32, 1])

    def test_duplicate_pending_info_does_not_expire_an_already_queued_gesture(self):
        c, queue, glib, patches, braille, calls = self.make()
        with glib, patches:
            c._on_remote_braille_info(numCells=80)
            self.pan(c)
            c._on_remote_braille_info(numCells=80)
            self.drain(queue)
        self.assertEqual(calls, [("refresh", 80), ("pan", 80)])


if __name__ == "__main__":
    unittest.main()
