# Orca
#
# Copyright 2004-2009 Sun Microsystems Inc.
# Copyright 2010 Joanmarie Diggs
# Copyright 2010-2011 The Orca Team
# Copyright 2012 Igalia, S.L.
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

# Frozen native methods for isolated remote braille-home speech tests.

# Source: Orca 42.0 braille.py
dontInteruptSpeechKeys = []
if _brlAPIAvailable:
    dontInteruptSpeechKeys = [ \
        brlapi.KEY_CMD_HWINLT, brlapi.KEY_CMD_HWINRT, \
        brlapi.KEY_CMD_FWINLT, brlapi.KEY_CMD_FWINRT, \
        brlapi.KEY_CMD_FWINLTSKIP, brlapi.KEY_CMD_FWINRTSKIP, \
        brlapi.KEY_CMD_LNUP, brlapi.KEY_CMD_LNDN]

# Source: Orca 42.0 orca.py
def _processBrailleEvent(event):
    """Called whenever a  key is pressed on the Braille display.

    Arguments:
    - command: the BrlAPI event for the key that was pressed.

    Returns True if the event was consumed; otherwise False
    """

    consumed = False

    # Braille key presses always interrupt speech.
    #
    event = BrailleEvent(event)
    if event.event['command'] not in braille.dontInteruptSpeechKeys:
        speech.stop()
    orca_state.lastInputEvent = event

    try:
        consumed = _eventManager.processBrailleEvent(event)
    except:
        debug.printException(debug.LEVEL_SEVERE)

    if (not consumed) and orca_state.learnModeEnabled:
        consumed = True

    return consumed

# Source: Orca 42.0 braille.py
def returnToRegionWithFocus(inputEvent=None):
    """Pans the display so the region with focus is displayed.

    Arguments:
    - inputEvent: the InputEvent instance that caused this to be called.

    Returns True to mean the command should be consumed.
    """

    setFocus(_regionWithFocus)
    refresh(True)

    return True

# Source: Orca 42.0 scripts/default.py
class Script:
    def goBrailleHome(self, inputEvent=None):
        """Returns to the component with focus."""

        if self.flatReviewContext:
            return self.toggleFlatReviewMode(inputEvent)
        else:
            return braille.returnToRegionWithFocus(inputEvent)
