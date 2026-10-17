"""Companion lifecycle boundaries, with no running NVDA or desktop changes."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from unittest import mock

from extensionPoints import Action

from tests import PLUGIN_ROOT, WIRE_ROOT
from tests._objects import install_handler_runtime_stubs


class PluginTests(unittest.TestCase):
	def setUp(self):
		install_handler_runtime_stubs()
		self.callbacks = []
		self.secure = False
		self.locked = False
		self.lockEvent = Action()
		self.secureEvent = Action()
		self.profileEvent = Action()
		self.plugins = set()
		self.tray = mock.Mock()
		self.tray.toolsMenu.Append.side_effect = [object(), object()]
		self.timers = []
		self.dialogs = mock.Mock()
		self.messages = mock.Mock()

		def callLater(_delay, callback):
			timer = mock.Mock(callback=callback)
			self.timers.append(timer)
			return timer

		modules = {
			"globalPluginHandler": types.SimpleNamespace(
				GlobalPlugin=type("BasePlugin", (), {"terminate": lambda self: None}),
				runningPlugins=self.plugins,
			),
			"gui": types.SimpleNamespace(
				mainFrame=types.SimpleNamespace(sysTrayIcon=self.tray),
				runScriptModalDialog=self.dialogs,
			),
			"ui": types.SimpleNamespace(message=self.messages),
			"wx": types.SimpleNamespace(
				CallAfter=self.callbacks.append, ID_ANY=-1, ID_OK=1, EVT_MENU=object()
			),
			"core": types.SimpleNamespace(callLater=callLater),
			"scriptHandler": types.SimpleNamespace(script=lambda **_kwargs: lambda function: function),
			"config": types.SimpleNamespace(post_configProfileSwitch=self.profileEvent),
			"utils.security": types.SimpleNamespace(
				isRunningOnSecureDesktop=lambda: self.secure,
				post_sessionLockStateChanged=self.lockEvent,
			),
			"winAPI.secureDesktop": types.SimpleNamespace(post_secureDesktopStateChange=self.secureEvent),
			"winAPI.sessionTracking": types.SimpleNamespace(isLockScreenModeActive=lambda: self.locked),
		}
		patcher = mock.patch.dict(sys.modules, modules)
		patcher.start()
		self.addCleanup(patcher.stop)
		name = "_linux_rdaccess_plugin_tests"
		spec = importlib.util.spec_from_file_location(
			name,
			PLUGIN_ROOT / "__init__.py",
			submodule_search_locations=[str(PLUGIN_ROOT), str(WIRE_ROOT)],
		)
		self.module = importlib.util.module_from_spec(spec)
		sys.modules[name] = self.module
		spec.loader.exec_module(self.module)
		self.service = mock.Mock()
		self.module.LocalTestService = mock.Mock(return_value=self.service)
		self.discover = self.module.findRemoteAccessTransport = mock.Mock(return_value=None)
		self.module.RemoteAccessSemanticBrailleBridge = mock.Mock()
		remote = sys.modules[f"{name}.localTestRemote"]
		remote.findRemoteConnection = mock.Mock(return_value=mock.sentinel.remote)
		self.dialog = types.SimpleNamespace(
			allowConnect=mock.Mock(), recordRouting=mock.Mock(), allowMessageRoute=mock.Mock()
		)
		self.dialog.allowMessageRoute.GetValue.return_value = False
		self.dialog.allowConnect.GetValue.return_value = False
		self.dialog.recordRouting.GetValue.return_value = False
		sys.modules[f"{name}.localTestDialog"] = types.SimpleNamespace(
			LocalTestAuthorizationDialog=lambda _parent: self.dialog,
		)
		self.plugin = None

	def tearDown(self):
		if self.plugin is not None:
			self.plugin.terminate()
		for name in list(sys.modules):
			if name.startswith("_linux_rdaccess_plugin_tests"):
				sys.modules.pop(name)

	def create(self, *, activate=True):
		self.plugin = self.module.GlobalPlugin()
		if activate:
			self.callbacks.pop(0)()
		return self.plugin

	def legacyPlugin(self, *, linuxIntegration=True):
		attributes = {"__module__": "globalPlugins.rdAccess"}
		if linuxIntegration:
			attributes["_refreshRemoteAccessSemanticBraille"] = lambda self: None
		return type("RDAccess", (), attributes)()

	def test_constructor_waits_for_all_plugins_and_starts_no_listener(self):
		plugin = self.create(activate=False)
		self.module.LocalTestService.assert_not_called()
		self.tray.toolsMenu.Append.assert_not_called()
		self.assertFalse(plugin._localTestSession.active())
		self.assertEqual(len(self.callbacks), 1)
		self.callbacks.pop(0)()
		self.service.start.assert_not_called()
		self.assertEqual(self.tray.toolsMenu.Append.call_count, 2)

	def test_legacy_plugin_created_later_blocks_duplicate_bridge_and_consent(self):
		plugin = self.create(activate=False)
		self.plugins.add(self.legacyPlugin())
		self.callbacks.pop(0)()
		self.assertTrue(plugin._legacyConflict)
		self.module.LocalTestService.assert_not_called()
		self.module.RemoteAccessSemanticBrailleBridge.assert_not_called()
		self.tray.toolsMenu.Append.assert_not_called()
		plugin.script_authorizeLocalTestSession(None)
		self.dialogs.assert_not_called()

	def test_general_rdaccess_without_linux_bridge_can_coexist(self):
		self.plugins.add(self.legacyPlugin(linuxIntegration=False))
		self.assertTrue(self.create()._localTestUiInitialized)

	def test_secure_desktop_startup_has_no_ui_worker_or_deferred_activation(self):
		self.secure = True
		self.create(activate=False)
		self.assertEqual(self.callbacks, [])
		self.module.LocalTestService.assert_not_called()
		self.tray.toolsMenu.Append.assert_not_called()

	def test_termination_before_deferred_start_cannot_reactivate(self):
		plugin = self.create(activate=False)
		plugin.terminate()
		self.callbacks.pop(0)()
		self.module.LocalTestService.assert_not_called()
		self.tray.toolsMenu.Append.assert_not_called()

	def test_explicit_and_transition_revocation_stop_the_session(self):
		plugin = self.create()
		plugin.script_revokeLocalTestSession(None)
		self.profileEvent.notify()
		self.lockEvent.notify(isNowLocked=True)
		self.secureEvent.notify(isSecureDesktop=True)
		self.assertEqual(self.service.stop.call_count, 4)
		self.lockEvent.notify(isNowLocked=False)
		self.assertEqual(self.service.stop.call_count, 4)

	def test_cancelled_dialog_does_not_start_consent(self):
		self.create()._showLocalTestAuthorization()
		self.dialogs.call_args.kwargs["callback"](0)
		self.service.start.assert_not_called()

	def test_connection_permission_requires_the_explicit_checkbox(self):
		plugin = self.create()
		for allowed in (False, True):
			self.dialog.allowConnect.GetValue.return_value = allowed
			plugin._showLocalTestAuthorization()
			self.dialogs.call_args.kwargs["callback"](1)
			self.service.start.assert_called_with(
				allowConnect=allowed, remote=mock.sentinel.remote, allowMessageRoute=False
			)

	def test_routing_diagnostics_require_their_checkbox_and_active_consent(self):
		plugin = self.create()
		with mock.patch.object(plugin._routingTrace, "_authorized", return_value=True):
			for enabled in (False, True):
				self.dialog.recordRouting.GetValue.return_value = enabled
				plugin._showLocalTestAuthorization()
				self.dialogs.call_args.kwargs["callback"](1)
				self.assertEqual(plugin.getLocalRoutingTrace()["available"], enabled)
		plugin._revokeLocalTestSession()
		self.assertFalse(plugin.getLocalRoutingTrace()["available"])

	def test_message_route_permission_is_separate_and_includes_diagnostics(self):
		plugin = self.create()
		self.dialog.recordRouting.GetValue.return_value = False
		self.dialog.allowMessageRoute.GetValue.return_value = True
		with mock.patch.object(plugin._routingTrace, "_authorized", return_value=True):
			plugin._showLocalTestAuthorization()
			self.dialogs.call_args.kwargs["callback"](1)
			self.service.start.assert_called_with(
				allowConnect=False, remote=mock.sentinel.remote, allowMessageRoute=True
			)
			self.assertTrue(plugin.getLocalRoutingTrace()["available"])

	def test_failed_or_ended_consent_clears_routing_diagnostics(self):
		plugin = self.create()
		with mock.patch.object(plugin._routingTrace, "_authorized", return_value=True):
			for outcome in ("failed", "stopped"):
				plugin._routingTrace.start(enabled=True)
				plugin._notifyLocalTestSession(outcome)
				self.assertFalse(plugin.getLocalRoutingTrace()["available"])

	def test_duplicate_consent_cannot_change_existing_routing_permission(self):
		plugin = self.create()
		with mock.patch.object(plugin._routingTrace, "_authorized", return_value=True):
			plugin._routingTrace.start(enabled=True)
			self.service.start.side_effect = self.module.LocalTestSessionBusyError()
			plugin._showLocalTestAuthorization()
			self.dialogs.call_args.kwargs["callback"](1)
			self.assertTrue(plugin.getLocalRoutingTrace()["available"])

	def test_profile_lock_and_secure_desktop_clear_opted_in_routing_permission(self):
		plugin = self.create()
		with mock.patch.object(plugin._routingTrace, "_authorized", return_value=True):
			for revoke in (
				self.profileEvent.notify,
				lambda: self.lockEvent.notify(isNowLocked=True),
				lambda: self.secureEvent.notify(isSecureDesktop=True),
			):
				plugin._routingTrace.start(enabled=True)
				revoke()
				self.assertFalse(plugin.getLocalRoutingTrace()["available"])

	def test_locked_or_secure_desktop_rejects_pending_dialog_confirmation(self):
		plugin = self.create()
		for attribute in ("secure", "locked"):
			plugin._showLocalTestAuthorization()
			setattr(self, attribute, True)
			self.dialogs.call_args.kwargs["callback"](1)
			self.service.start.assert_not_called()
			with self.assertRaises(PermissionError):
				plugin.handleLocalTestRequest({"version": 1, "action": "status"})
			setattr(self, attribute, False)

	def test_reuses_transport_and_cleans_old_bridge_on_replacement(self):
		self.discover.return_value = mock.sentinel.transport1
		bridge = mock.Mock(transport=mock.sentinel.transport1)
		self.module.RemoteAccessSemanticBrailleBridge.return_value = bridge
		plugin = self.create()
		plugin._refreshRemoteAccessSemanticBraille()
		self.module.RemoteAccessSemanticBrailleBridge.assert_called_once_with(mock.sentinel.transport1)
		self.discover.return_value = mock.sentinel.transport2
		plugin._refreshRemoteAccessSemanticBraille()
		bridge.terminate.assert_called_once()
		self.module.RemoteAccessSemanticBrailleBridge.assert_called_with(mock.sentinel.transport2)

	def test_late_legacy_conflict_removes_companion_hooks_and_menus(self):
		plugin = self.create()
		self.plugins.add(self.legacyPlugin())
		plugin._refreshRemoteAccessSemanticBraille()
		self.assertTrue(plugin._legacyConflict)
		self.service.stop.assert_called_once()
		self.assertEqual(self.tray.toolsMenu.DestroyItem.call_count, 2)
		self.assertEqual(list(self.profileEvent.handlers), [])
		self.timers[0].Stop.assert_called_once()

	def test_shutdown_removes_callbacks_menus_and_rejects_queued_refresh(self):
		plugin = self.create()
		plugin.terminate()
		self.timers[0].callback()
		self.assertEqual(len(self.timers), 1)
		self.assertEqual(self.tray.Unbind.call_count, 2)
		self.assertEqual(self.tray.toolsMenu.DestroyItem.call_count, 2)
		self.assertEqual(list(self.lockEvent.handlers), [])
		self.assertEqual(list(self.secureEvent.handlers), [])
		self.assertEqual(list(self.profileEvent.handlers), [])

	def test_main_thread_cannot_block_waiting_for_worker_status(self):
		with self.assertRaises(RuntimeError):
			self.create().getLocalTestStatusFromWorker()
