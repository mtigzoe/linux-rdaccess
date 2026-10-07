# Orca
#
# Copyright 2012 Igalia, S.L.
#
# Author: Joanmarie Diggs <jdiggs@igalia.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., Franklin Street, Fifth Floor,
# Boston MA  02110-1301 USA.

# Frozen Orca 42.0 native callbacks for list lifetime regression tests.
# Source: /usr/lib/python3/dist-packages/orca/orca_gui_navlist.py

class OrcaNavListGUI:
    def _onCancelClicked(self, widget):
        self._gui.destroy()

    def _onJumpToClicked(self, widget):
        obj, offset = self._getSelectedAccessibleAndOffset()
        self._gui.destroy()
        self._script.utilities.setCaretPosition(obj, offset, self._document)

    def _onActivateClicked(self, widget):
        obj, offset = self._getSelectedAccessibleAndOffset()
        self._gui.destroy()
        if not obj:
            return

        self._script.utilities.setCaretPosition(obj, offset)
        try:
            action = obj.queryAction()
        except NotImplementedError:
            msg = "ERROR: Action interface not implemented for %s" % obj
            debug.println(debug.LEVEL_INFO, msg, True)
        except:
            msg = "ERROR: Exception getting action interface for %s" % obj
            debug.println(debug.LEVEL_INFO, msg, True)
        else:
            action.doAction(0)
