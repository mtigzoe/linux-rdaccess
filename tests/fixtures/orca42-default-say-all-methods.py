# Orca
#
# Copyright 2004-2009 Sun Microsystems Inc.
# Copyright 2010 Joanmarie Diggs
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

# Frozen Orca 42.0 native caret/focus callback for Say All lifetime tests.
# Source: /usr/lib/python3/dist-packages/orca/scripts/default.py

class Script:
    def __sayAllProgressCallback(self, context, progressType):
        # [[[TODO: WDW - this needs work.  Need to be able to manage
        # the monitoring of progress and couple that with both updating
        # the visual progress of what is being spoken as well as
        # positioning the cursor when speech has stopped.]]]
        #
        try:
            text = context.obj.queryText()
            char = text.getText(context.currentOffset, context.currentOffset+1)
        except:
            return

        # Setting the caret at the offset of an embedded object results in
        # focus changes.
        if char == self.EMBEDDED_OBJECT_CHARACTER:
            return

        if progressType == speechserver.SayAllContext.PROGRESS:
            orca.emitRegionChanged(
                context.obj, context.currentOffset, context.currentEndOffset, orca.SAY_ALL)
            return

        if progressType == speechserver.SayAllContext.INTERRUPTED:
            if isinstance(orca_state.lastInputEvent, input_event.KeyboardEvent):
                self._sayAllIsInterrupted = True
                lastKey = orca_state.lastInputEvent.event_string
                if lastKey == "Down" and self._fastForwardSayAll(context):
                    return
                elif lastKey == "Up" and self._rewindSayAll(context):
                    return

            self._inSayAll = False
            self._sayAllContexts = []
            orca.emitRegionChanged(context.obj, context.currentOffset)
            text.setCaretOffset(context.currentOffset)
        elif progressType == speechserver.SayAllContext.COMPLETED:
            orca.setLocusOfFocus(None, context.obj, notifyScript=False)
            orca.emitRegionChanged(context.obj, context.currentOffset, mode=orca.SAY_ALL)
            text.setCaretOffset(context.currentOffset)

        # If there is a selection, clear it. See bug #489504 for more details.
        #
        if text.getNSelections() > 0:
            text.setSelection(0, context.currentOffset, context.currentOffset)
