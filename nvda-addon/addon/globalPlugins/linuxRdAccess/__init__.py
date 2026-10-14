# Linux Remote Access Companion for NVDA
# Derived from RDAccess, Copyright 2023 Leonard de Ruijter <alderuijter@gmail.com>
# Extracted and adapted for linux-rdaccess on 2026-10-12.
# License: GNU General Public License version 2.0 or later

from __future__ import annotations

import threading
from contextlib import suppress

import addonHandler
import config
import core
import globalPluginHandler
import gui
import ui
import wx
from logHandler import log
from scriptHandler import script
from utils.security import isRunningOnSecureDesktop, post_sessionLockStateChanged
from winAPI.secureDesktop import post_secureDesktopStateChange
from winAPI.sessionTracking import isLockScreenModeActive

from . import localTestIpc, localTestRequest, localTestStatus
from .localTestRoutingTrace import RoutingTraceRecorder
from .localTestService import LocalTestService, LocalTestSessionBusyError
from .localTestSession import LocalStatusSession
from .remoteAccessSemanticBraille import RemoteAccessSemanticBrailleBridge, findRemoteAccessTransport

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self._localTestUiInitialized = False
		self._remoteAccessSemanticBrailleStopped = False
		self._remoteAccessSemanticBraille = None
		self._localTestSession = LocalStatusSession()
		self._routingTrace = RoutingTraceRecorder(self._localTestSession.active)
		self._localTestService = None
		self._refreshTimer = None
		self._legacyConflict = False
		if isRunningOnSecureDesktop():
			self._remoteAccessSemanticBrailleStopped = True
			return
		# NVDA adds each plugin to runningPlugins only after its constructor
		# returns. Defer ownership until all plugins have been constructed.
		wx.CallAfter(self._initializeWhenReady)

	def _legacyIntegrationPresent(self):
		return any(
			type(plugin).__module__.startswith("globalPlugins.rdAccess")
			and callable(getattr(plugin, "_refreshRemoteAccessSemanticBraille", None))
			for plugin in getattr(globalPluginHandler, "runningPlugins", ())
		)

	def _initializeWhenReady(self):
		if self._remoteAccessSemanticBrailleStopped or self._localTestUiInitialized:
			return
		if isRunningOnSecureDesktop():
			self._remoteAccessSemanticBrailleStopped = True
			return
		if self._legacyIntegrationPresent():
			self._reportLegacyConflict()
			return
		self._localTestService = LocalTestService(
			self._localTestSession,
			self.getLocalTestStatus,
			wx.CallAfter,
			self._testSessionPermitted,
			self._notifyLocalTestSession,
			routingTrace=self.getLocalRoutingTrace,
			routingOutcomes=self.getLocalRoutingOutcomes,
		)
		assert gui.mainFrame is not None
		tray = gui.mainFrame.sysTrayIcon
		# Translators: NVDA Tools command for explicit, temporary local test consent.
		self._authorizeTestMenu = tray.toolsMenu.Append(wx.ID_ANY, _("Authorize Linux test session..."))
		# Translators: NVDA Tools command for immediate test-session revocation.
		self._revokeTestMenu = tray.toolsMenu.Append(wx.ID_ANY, _("Revoke Linux test session"))
		tray.Bind(wx.EVT_MENU, self._showLocalTestAuthorization, self._authorizeTestMenu)
		tray.Bind(wx.EVT_MENU, self._revokeLocalTestSession, self._revokeTestMenu)
		post_secureDesktopStateChange.register(self._revokeLocalTestSession)
		post_sessionLockStateChanged.register(self._handleLocalTestLock)
		config.post_configProfileSwitch.register(self._revokeLocalTestSession)
		self._localTestUiInitialized = True
		log.info("Initialized Linux Remote Access Companion")
		self._refreshRemoteAccessSemanticBraille()

	def _reportLegacyConflict(self):
		self._legacyConflict = True
		self._remoteAccessSemanticBrailleStopped = True
		log.warning("Linux companion inactive: RDAccess already provides the Linux integration")
		# Translators: A legacy development add-on already owns the Linux bridge.
		ui.message(
			_(
				"Linux Remote Access Companion is inactive because RDAccess already provides the Linux integration. "
				"Disable that development add-on and restart NVDA to use the companion.",
			)
		)

	def _testSessionPermitted(self):
		return (
			self._localTestUiInitialized
			and not self._remoteAccessSemanticBrailleStopped
			and not isRunningOnSecureDesktop()
			and not isLockScreenModeActive()
		)

	def _notifyLocalTestSession(self, outcome):
		if outcome in ("failed", "stopped"):
			self._routingTrace.clear()
		log.info("Local test session outcome: %s", outcome)
		if not self._testSessionPermitted():
			return
		if outcome == "started":
			# Translators: The explicitly authorized endpoint is ready.
			ui.message(_("Linux test session authorized for five minutes"))
		elif outcome == "failed":
			# Translators: Generic failure; contains no IPC addresses or credentials.
			ui.message(_("Could not start the Linux test session. Authorization revoked."))
		elif outcome == "busy":
			# Translators: Duplicate consent must not extend the current expiry.
			ui.message(
				_(
					"Linux test session is already active or ending. Revoke it or wait before authorizing again."
				)
			)
		else:
			# Translators: Authorization has expired or been revoked.
			ui.message(_("Linux test session authorization ended"))

	def _showLocalTestAuthorization(self, _event=None):
		from .localTestDialog import LocalTestAuthorizationDialog
		from .localTestRemote import findRemoteConnection

		if not self._testSessionPermitted():
			return
		dialog = LocalTestAuthorizationDialog(gui.mainFrame)

		def complete(result):
			if result != wx.ID_OK or not self._testSessionPermitted():
				return
			log.info("Local test consent accepted")
			try:
				self._localTestService.start(
					allowConnect=dialog.allowConnect.GetValue(),
					remote=findRemoteConnection(getattr(globalPluginHandler, "runningPlugins", ())),
				)
				self._routingTrace.start(enabled=dialog.recordRouting.GetValue() is True)
			except LocalTestSessionBusyError:
				self._notifyLocalTestSession("busy")
			except Exception as error:
				log.warning("Local test consent could not start (%s)", type(error).__name__)
				self._notifyLocalTestSession("failed")

		gui.runScriptModalDialog(dialog, callback=complete)

	def _revokeLocalTestSession(self, _event=None, **_kwargs):
		self._routingTrace.clear()
		if self._localTestSession.active():
			log.info("Revoking local test authorization after explicit request or desktop transition")
		if self._localTestService is not None:
			self._localTestService.stop()

	def _handleLocalTestLock(self, isNowLocked):
		if isNowLocked:
			self._revokeLocalTestSession()

	@script(
		# Translators: Input Gestures description for temporary Linux test consent.
		description=_("Authorize a temporary Linux test session"),
		category="Linux Remote Access Companion",
	)
	def script_authorizeLocalTestSession(self, _gesture):
		self._showLocalTestAuthorization()

	@script(
		# Translators: Input Gestures description for immediate revocation.
		description=_("Revoke Linux test session authorization"),
		category="Linux Remote Access Companion",
	)
	def script_revokeLocalTestSession(self, _gesture):
		self._revokeLocalTestSession()

	def getLocalTestStatus(self):
		return localTestStatus.snapshot(self._remoteAccessSemanticBraille)

	def getLocalRoutingTrace(self):
		return self._routingTrace.snapshot()

	def getLocalRoutingOutcomes(self):
		return self._routingTrace.snapshotOutcomes()

	def handleLocalTestRequest(self, request):
		localTestRequest.validateRequest(request)
		if not self._testSessionPermitted():
			raise PermissionError("Local test status unavailable")
		return self.getLocalTestStatus()

	def getLocalTestStatusFromWorker(self, *, cancelled=None):
		if threading.current_thread() is threading.main_thread():
			raise RuntimeError("Local status worker must not run on NVDA main thread")
		return localTestIpc.waitForMainThreadStatus(
			lambda: self.handleLocalTestRequest({"version": 1, "action": "status"}),
			wx.CallAfter,
			cancelled=cancelled,
		)

	def _refreshRemoteAccessSemanticBraille(self):
		if self._remoteAccessSemanticBrailleStopped:
			return
		if self._legacyIntegrationPresent():
			self._deactivate()
			self._reportLegacyConflict()
			return
		try:
			transport = findRemoteAccessTransport(getattr(globalPluginHandler, "runningPlugins", ()))
			current = self._remoteAccessSemanticBraille
			if current is not None and current.transport is transport:
				return
			if current is not None:
				current.terminate()
				self._remoteAccessSemanticBraille = None
			if transport is not None:
				self._remoteAccessSemanticBraille = RemoteAccessSemanticBrailleBridge(transport)
				self._remoteAccessSemanticBraille._routingTrace = self._routingTrace
				log.info("Attached NVDA-native linux-rdaccess braille presentation")
		except Exception:
			log.debugWarning("Could not attach linux-rdaccess semantic braille", exc_info=True)
		finally:
			if not self._remoteAccessSemanticBrailleStopped:
				self._refreshTimer = core.callLater(1000, self._refreshRemoteAccessSemanticBraille)

	def _deactivate(self):
		self._remoteAccessSemanticBrailleStopped = True
		self._revokeLocalTestSession()
		if self._refreshTimer is not None:
			with suppress(Exception):
				self._refreshTimer.Stop()
			self._refreshTimer = None
		if self._remoteAccessSemanticBraille is not None:
			self._remoteAccessSemanticBraille.terminate()
			self._remoteAccessSemanticBraille = None
		if self._localTestUiInitialized:
			self._localTestUiInitialized = False
			post_secureDesktopStateChange.unregister(self._revokeLocalTestSession)
			post_sessionLockStateChanged.unregister(self._handleLocalTestLock)
			config.post_configProfileSwitch.unregister(self._revokeLocalTestSession)
			assert gui.mainFrame is not None
			tray = gui.mainFrame.sysTrayIcon
			for item in (self._authorizeTestMenu, self._revokeTestMenu):
				tray.Unbind(wx.EVT_MENU, source=item)
				tray.toolsMenu.DestroyItem(item)

	def terminate(self):
		try:
			self._deactivate()
		finally:
			super().terminate()
