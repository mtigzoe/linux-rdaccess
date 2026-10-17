# Extracted for linux-rdaccess on 2026-10-12; original GPL-2.0-or-later license retained.
"""Standard wx controls for temporary local test authorization."""

from __future__ import annotations

import addonHandler
import wx

addonHandler.initTranslation()


class LocalTestAuthorizationDialog(wx.Dialog):
	def __init__(self, parent):
		# Translators: Title of the temporary test-session authorization dialog.
		super().__init__(parent, title=_("Authorize Linux test session"))
		sizer = wx.BoxSizer(wx.VERTICAL)
		# Translators: Explains the local test-session permission and its expiry.
		message = _(
			"Authorize programs running under your Windows account to read connection status "
			"for five minutes. "
			"You can revoke authorization from NVDA Tools. "
			"A connection created by this test session will be disconnected when authorization ends. "
			"Existing connections are preserved. Keyboard injection is unavailable. "
			"The optional routing permission allows one software routing press on cell 0 "
			"of a visible Linux temporary message, never the document underneath.",
		)
		label = wx.StaticText(self, label=message)
		label.Wrap(480)
		sizer.Add(label, flag=wx.ALL, border=12)
		# Translators: Additional permission, unchecked by default, to use saved Remote Access settings.
		self.allowConnect = wx.CheckBox(
			self,
			label=_("Allow connection using saved Remote Access relay settings"),
		)
		sizer.Add(self.allowConnect, flag=wx.ALL, border=12)
		# Translators: Optional numeric diagnostics, unchecked by default; no text is recorded.
		self.recordRouting = wx.CheckBox(
			self,
			label=_("Record numeric braille routing diagnostics (no text)"),
		)
		sizer.Add(self.recordRouting, flag=wx.ALL, border=12)
		# Translators: Separate optional input permission; not granted by status/diagnostics consent.
		self.allowMessageRoute = wx.CheckBox(
			self,
			label=_("Allow one simulated routing press on a Linux message (records numeric diagnostics)"),
		)
		sizer.Add(self.allowMessageRoute, flag=wx.ALL, border=12)
		buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
		# Translators: Confirms temporary authorization; this is not persistent configuration.
		self.FindWindowById(wx.ID_OK).SetLabel(_("Authorize for five minutes"))
		sizer.Add(buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=12)
		self.SetSizerAndFit(sizer)
		self.allowConnect.SetFocus()
