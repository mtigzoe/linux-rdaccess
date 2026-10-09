# Orca
#
# Copyright 2005-2008 Sun Microsystems Inc.
# Copyright 2011-2016 Igalia, S.L.
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

# Frozen Orca 42.0 dispatcher and presenter for isolated keyboard regressions.
# Source: /usr/lib/python3/dist-packages/orca/input_event.py

class KeyboardEvent:
    def shouldConsume(self):
        """Returns True if this event should be consumed."""

        if not self.timestamp:
            return False, 'No timestamp'

        if not self._script:
            return False, 'No active script when received'

        if self.is_duplicate:
            return False, 'Is duplicate'

        if orca_state.capturingKeys:
            return False, 'Capturing keys'

        if orca_state.bypassNextCommand:
            return False, 'Bypass next command'

        self._handler = self._getUserHandler() \
            or self._script.keyBindings.getInputHandler(self)

        # TODO - JD: Right now we need to always call consumesKeyboardEvent()
        # because that method is updating state, even in instances where there
        # is no handler.
        scriptConsumes = self._script.consumesKeyboardEvent(self)

        if self._isReleaseForLastNonModifierKeyEvent():
            return scriptConsumes, 'Is release for last non-modifier keyevent'

        if orca_state.learnModeEnabled:
            if self.event_string == 'Escape':
                self._consumer = self._script.exitLearnMode
                return True, 'Exiting Learn Mode'

            if self.event_string == 'F1' and not self.modifiers:
                self._consumer = self._script.showHelp
                return True, 'Showing Help'

            if self.event_string in ['F2', 'F3'] and not self.modifiers:
                self._consumer = self._script.listOrcaShortcuts
                return True, 'Listing shortcuts'

            self._consumer = self._presentHandler
            return True, 'In Learn Mode'

        if self.isModifierKey():
            if not self.isOrcaModifier():
                return False, 'Non-Orca modifier not in Learn Mode'
            return True, 'Orca modifier'

        if orca_state.listNotificationsModeEnabled:
            self._consumer = self._script.listNotifications
            return True, 'Listing notifications'

        if not self._handler:
            return False, 'No handler'

        return scriptConsumes, 'Script indication'

    def _presentHandler(self, input_event=None):
        if not self._handler:
            return False

        if self._handler.learnModeEnabled and self._handler.description:
            self._script.presentMessage(self._handler.description)

        return True
