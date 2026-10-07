"""Keep Orca's native list callbacks safe after their origin disappears."""
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from orca_adapter import OrcaRuntimeAdapter
from tests.test_compat_lifecycle import Harness


class NativeListLifetimeTests(unittest.TestCase):
    def setUp(self):
        namespace = {
            "debug": types.SimpleNamespace(LEVEL_INFO=1, println=lambda *args: None),
        }
        fixture = Path(__file__).parent / "fixtures" / "orca42-navlist-methods.py"
        exec(compile(fixture.read_text(), str(fixture), "exec"), namespace)
        native = namespace["OrcaNavListGUI"]
        self.document = object()
        self.window = object()
        self.target = types.SimpleNamespace(queryAction=mock.Mock())
        self.action = self.target.queryAction.return_value
        self.state = {
            "document": self.document, "target_document": self.document,
            "dead": None, "zombie": None, "session": True,
        }
        self.utilities = types.SimpleNamespace(
            activeDocument=lambda window: self.state["document"],
            isDead=lambda obj: obj is self.state["dead"],
            isZombie=lambda obj: obj is self.state["zombie"],
            getTopLevelDocumentForObject=lambda obj: self.state["target_document"],
            setCaretPosition=mock.Mock(),
        )
        self.script = types.SimpleNamespace(utilities=self.utilities)
        self.orca_state = types.SimpleNamespace(
            activeScript=self.script, activeWindow=self.window,
        )
        self.guis = []

        def init(gui, *args):
            gui._script = self.orca_state.activeScript
            gui._document = None
            gui._gui = types.SimpleNamespace(destroy=mock.Mock())
            gui._getSelectedAccessibleAndOffset = lambda: (self.target, 4)
            self.guis.append(gui)

        def show(gui):
            gui._document = self.document

        native.__init__ = init
        native.showGUI = show
        module = types.ModuleType("orca.orca_gui_navlist")
        module.OrcaNavListGUI = native
        module.showUI = mock.Mock()
        self.module = module
        self.original_show = module.showUI

        def handler(script, event):
            module.showUI("Links", ["Link"], [[self.target, 4, "Link"]], 0)

        self.handler = mock.Mock(side_effect=handler)
        self.script.structuralNavigation = types.SimpleNamespace(enabledObjects={
            "link": types.SimpleNamespace(
                bindings={"list": ["k", 0, "Links"]}, showList=self.handler,
            ),
        })
        orca = types.ModuleType("orca")
        orca.orca_state = self.orca_state
        orca.orca_gui_navlist = module
        self.patch = mock.patch.dict(sys.modules, {
            "orca": orca, "orca.orca_gui_navlist": module,
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def open_list(self):
        self.assertTrue(OrcaRuntimeAdapter.show_structural_list(
            "k", lifetime_valid=lambda: self.state["session"],
        ))
        self.assertIs(self.module.showUI, self.original_show)
        self.original_show.assert_not_called()
        return self.guis[-1]

    def test_native_jump_still_uses_selected_accessible_offset_and_document(self):
        gui = self.open_list()
        # Orca switches to its GTK script while its own dialog has focus.
        self.orca_state.activeScript = object()
        self.orca_state.activeWindow = object()
        gui._onJumpToClicked(None)
        self.utilities.setCaretPosition.assert_called_once_with(self.target, 4, self.document)
        gui._gui.destroy.assert_called_once_with()

    def test_native_activate_still_positions_and_activates_selected_accessible(self):
        gui = self.open_list()
        gui._onActivateClicked(None)
        self.utilities.setCaretPosition.assert_called_once_with(self.target, 4)
        self.action.doAction.assert_called_once_with(0)

    def test_reload_tab_switch_and_removed_target_never_reach_native_callbacks(self):
        changes = (
            ("document", object()), ("document", None),
            ("dead", self.target), ("zombie", self.target),
            ("dead", self.document), ("zombie", self.document),
            ("target_document", object()), ("session", False),
        )
        for callback in ("_onJumpToClicked", "_onActivateClicked"):
            for key, value in changes:
                with self.subTest(callback=callback, change=key):
                    old = self.state[key]
                    gui = self.open_list()
                    self.state[key] = value
                    getattr(gui, callback)(None)
                    self.state[key] = old
                    self.utilities.setCaretPosition.assert_not_called()
                    self.target.queryAction.assert_not_called()
                    gui._gui.destroy.assert_called_once_with()

    def test_disappearing_document_query_closes_without_action(self):
        gui = self.open_list()
        self.utilities.activeDocument = mock.Mock(side_effect=RuntimeError("defunct"))
        gui._onJumpToClicked(None)
        self.utilities.setCaretPosition.assert_not_called()
        gui._gui.destroy.assert_called_once_with()

    def test_empty_selection_closes_without_positioning(self):
        gui = self.open_list()
        gui._getSelectedAccessibleAndOffset = lambda: (None, -1)
        gui._onJumpToClicked(None)
        self.utilities.setCaretPosition.assert_not_called()

    def test_cancel_keeps_orca_native_callback(self):
        gui = self.open_list()
        self.state["session"] = False
        gui._onCancelClicked(None)
        self.utilities.setCaretPosition.assert_not_called()
        gui._gui.destroy.assert_called_once_with()

    def test_handler_failure_restores_native_show_ui(self):
        self.handler.side_effect = RuntimeError("lookup failed")
        with self.assertRaises(RuntimeError):
            OrcaRuntimeAdapter.show_structural_list("k")
        self.assertIs(self.module.showUI, self.original_show)

    def test_local_orca_lists_remain_native_after_remote_dialog_opens(self):
        self.open_list()
        self.module.showUI("Local list")
        self.original_show.assert_called_once_with("Local list")


class RemoteNativeListSessionTests(Harness, unittest.TestCase):
    def test_open_native_list_expires_its_callback_on_session_handoff(self):
        controller, _, _ = self._patched_controller()
        handler = mock.Mock(return_value=True)
        adapter = types.ModuleType("linux_rdaccess_orca_adapter")
        adapter.OrcaRuntimeAdapter = types.SimpleNamespace(show_structural_list=handler)
        with mock.patch.dict(sys.modules, {"linux_rdaccess_orca_adapter": adapter}):
            controller._linux_rdaccess_open_structural_list("k", None)
            valid = handler.call_args.kwargs["lifetime_valid"]
            self.assertTrue(valid())
            controller.toggle_control()
            self.assertFalse(valid())


if __name__ == "__main__":
    unittest.main()
