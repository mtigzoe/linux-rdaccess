# Extracted verbatim methods from Ubuntu Orca 42.0-1ubuntu2 braille.py.
# Copyright 2005-2009 Sun Microsystems Inc.
# SPDX-License-Identifier: LGPL-2.1-or-later
# See the installed module for the full upstream license notice.
# Test namespaces replace module globals and accessible objects; method bodies
# are unmodified. Liblouis performs the actual contraction and cell mapping.

class Region:
    def __init__(self, string, cursorOffset=0, expandOnCursor=False):
        """Creates a new Region containing the given string.

        Arguments:
        - string: the string to be displayed
        - cursorOffset: a 0-based index saying where to draw the cursor
                        for this Region if it gets focus.
        """

        if not string:
            string = ""

        # If louis is None, then we don't go into contracted mode.
        self.contracted = settings.enableContractedBraille and louis is not None

        self.expandOnCursor = expandOnCursor

        # The uncontracted string for the line.
        #
        self.rawLine = string.strip("\n")

        if self.contracted:
            self.contractionTable = settings.brailleContractionTable or _defaultContractionTable
            if string.strip():
                msg = "BRAILLE: Contracting '%s' with table %s" % (string, self.contractionTable)
                debug.println(debug.LEVEL_INFO, msg, True)

            self.string, self.inPos, self.outPos, self.cursorOffset = \
                         self.contractLine(self.rawLine,
                                           cursorOffset, expandOnCursor)
        else:
            if string.strip():
                if not settings.enableContractedBraille:
                    msg = "BRAILLE: Not contracting '%s' because contracted braille is not enabled." % string
                    debug.println(debug.LEVEL_INFO, msg, True)
                else:
                    msg = "BRAILLE: Not contracting '%s' due to problem with liblouis." % string
                    debug.println(debug.LEVEL_INFO, msg, True)

            self.string = self.rawLine
            self.cursorOffset = cursorOffset

    def getAttributeMask(self, getLinkMask=True):
        """Creates a string which can be used as the attrOr field of brltty's
        write structure for the purpose of indicating text attributes, links,
        and selection.

        Arguments:
        - getLinkMask: Whether or not we should take the time to get
          the attributeMask for links. Reasons we might not want to
          include knowing that we will fail and/or it taking an
          unreasonable amount of time (AKA Gecko).
        """

        # Create an empty mask.
        #
        return '\x00' * len(self.string)

    def contractLine(self, line, cursorOffset=0, expandOnCursor=False):
        """Contract the given line. Returns the contracted line, and the
        cursor position in the contracted line.

        Arguments:
        - line: Line to contract.
        - cursorOffset: Offset of cursor,defaults to 0.
        - expandOnCursor: Expand word under cursor, False by default.
        """

        try:
            cursorOnSpace = line[cursorOffset] == ' '
        except IndexError:
            cursorOnSpace = False

        if not expandOnCursor or cursorOnSpace:
            mode = 0
        else:
            mode = louis.compbrlAtCursor

        contracted, inPos, outPos, cursorPos = \
            louis.translate([self.contractionTable],
                            line,
                            cursorPos=cursorOffset,
                            mode=mode)

        # Make sure the cursor is at a realistic spot.
        # Note that if cursorOffset is beyond the end of the buffer,
        # a spurious value is returned by liblouis in cursorPos.
        #
        if cursorOffset >= len(line):
            cursorPos = len(contracted)
        else:
            cursorPos = min(cursorPos, len(contracted))

        return contracted, inPos, outPos, cursorPos

    def displayToBufferOffset(self, display_offset):
        try:
            offset = self.inPos[display_offset]
        except IndexError:
            # Off the chart, we just place the cursor at the end of the line.
            offset = len(self.rawLine)
        except AttributeError:
            # Not in contracted mode.
            offset = display_offset

        return offset

class Text(Region):
    def __init__(self, accessible, label="", eol="",
                 startOffset=None, endOffset=None):
        """Creates a new Text region.

        Arguments:
        - accessible: the accessible that implements AccessibleText
        - label: an optional label to display
        """

        self.accessible = accessible
        if orca_state.activeScript and self.accessible:
            [string, self.caretOffset, self.lineOffset] = \
                 orca_state.activeScript.getTextLineAtCaret(
                     self.accessible, startOffset=startOffset, endOffset=endOffset)
        else:
            string = ""
            self.caretOffset = 0
            self.lineOffset = 0

        try:
            endOffset = endOffset - self.lineOffset
        except TypeError:
            endOffset = len(string)

        try:
            self.startOffset = startOffset - self.lineOffset
        except TypeError:
            self.startOffset = 0

        string = string[self.startOffset:endOffset]

        self.caretOffset -= self.startOffset

        cursorOffset = min(self.caretOffset - self.lineOffset, len(string))

        self._maxCaretOffset = self.lineOffset + len(string)

        self.eol = eol

        if label:
            self.label = label + ' '
        else:
            self.label = ''

        string = self.label + string

        cursorOffset += len(self.label)

        Region.__init__(self, string, cursorOffset, True)

        if not self.contracted and not settings.disableBrailleEOL:
            self.string += self.eol
        elif settings.disableBrailleEOL:
            # Ensure there is a place to click on at the end of a line
            # so the user can route the caret to the end of the line.
            #
            self.string += ' '

    def getCaretOffset(self, offset):
        """Returns the caret position of the given offset if the object
        has text with a caret.  Otherwise, returns -1.

        Arguments:
        - offset: 0-based offset of the cell on the physical display
        """
        offset = self.displayToBufferOffset(offset)

        if offset < 0:
            return -1

        return min(self.lineOffset + offset, self._maxCaretOffset)

    def processRoutingKey(self, offset):
        """Processes a cursor routing key press on this Component.  The offset
        is 0-based, where 0 represents the leftmost character of text
        associated with this region.  Note that the zeroeth character may have
        been scrolled off the display.
        """

        caretOffset = self.getCaretOffset(offset)

        if caretOffset < 0:
            return

        orca_state.activeScript.utilities.setCaretOffset(
            self.accessible, caretOffset)

    def contractLine(self, line, cursorOffset=0, expandOnCursor=True):
        contracted, inPos, outPos, cursorPos = Region.contractLine(
            self, line, cursorOffset, expandOnCursor)

        return contracted + self.eol, inPos, outPos, cursorPos

class Line:
    def __init__(self, region=None):
        self.regions = []
        self.string = ""
        if region:
            self.addRegion(region)

    def addRegion(self, region):
        self.regions.append(region)

    def addRegions(self, regions):
        self.regions.extend(regions)

    def getLineInfo(self, getLinkMask=True):
        """Computes the complete string for this line as well as a
        0-based index where the focused region starts on this line.
        If the region with focus is not on this line, then the index
        will be -1.

        Arguments:
        - getLinkMask: Whether or not we should take the time to get
          the attributeMask for links. Reasons we might not want to
          include knowing that we will fail and/or it taking an
          unreasonable amount of time (AKA Gecko).

        Returns [string, offsetIndex, attributeMask, ranges]
        """

        string = ""
        focusOffset = -1
        attributeMask = ""
        ranges = []
        for region in self.regions:
            if region == _regionWithFocus:
                focusOffset = len(string)
            if region.string:
                string += region.string
            mask = region.getAttributeMask(getLinkMask)
            attributeMask += mask

        words = [word.span() for word in re.finditer(r"(^\s+|\S+\s*)", string)]
        span = []
        for start, end in words:
            if span and end - span[0] > _displaySize[0]:
                ranges.append(span)
                span = []
            if not span:
                # Subdivide long words that exceed the display width.
                wordLength = end - start
                if wordLength > _displaySize[0]:
                    displayWidths = wordLength // _displaySize[0]
                    if displayWidths:
                        for i in range(displayWidths):
                            ranges.append([start + i * _displaySize[0], start + (i+1) * _displaySize[0]])
                        if wordLength % _displaySize[0]:
                            span = [start + displayWidths * _displaySize[0], end]
                        else:
                            continue
                else:
                    span = [start, end]
            else:
                span[1] = end
            if end == focusOffset:
                ranges.append(span)
                span = []
        else:
            if span:
                ranges.append(span)

        return [string, focusOffset, attributeMask, ranges]

    def getRegionAtOffset(self, offset):
        """Finds the Region at the given 0-based offset in this line.

        Returns the [region, offsetinregion] where the region is
        the region at the given offset, and offsetinregion is the
        0-based offset from the beginning of the region, representing
        where in the region the given offset is."""

        # Translate the cursor offset for this line into a cursor offset
        # for a region, and then pass the event off to the region for
        # handling.
        #
        foundRegion = None
        string = ""
        pos = 0
        for region in self.regions:
            foundRegion = region
            string = string + region.string
            if len(string) > offset:
                break
            else:
                pos = len(string)

        if offset >= len(string):
            return [None, -1]
        else:
            return [foundRegion, offset - pos]

    def processRoutingKey(self, offset):
        """Processes a cursor routing key press on this Component.  The offset
        is 0-based, where 0 represents the leftmost character of string
        associated with this line.  Note that the zeroeth character may have
        been scrolled off the display."""

        [region, regionOffset] = self.getRegionAtOffset(offset)
        if region:
            region.processRoutingKey(regionOffset)

def _getRangeForOffset(offset):
    string, focusOffset, attributeMask, ranges = _lines[viewport[1]].getLineInfo()
    for r in ranges:
        if r[0] <= offset < r[1]:
            return r
    for r in ranges:
        if offset == r[1]:
            return r

    return [0, 0]

def panRight(panAmount=0):
    """Pans the display to the right, limiting the pan to the length
    of the line being displayed.

    Arguments:
    - panAmount: the amount to pan.  A value of 0 means the entire
                 width of the physical display.

    Returns True if a pan actually happened.
    """

    oldX = viewport[0]
    if panAmount == 0:
        oldStart, oldEnd = _getRangeForOffset(oldX)
        newStart, newEnd = _getRangeForOffset(oldEnd)
        panAmount = max(0, min(newStart - oldStart, _displaySize[0]))

    if len(_lines) > 0:
        lineNum = viewport[1]
        newX = viewport[0] + panAmount
        string, focusOffset, attributeMask, ranges = _lines[lineNum].getLineInfo()
        if newX < len(string):
            viewport[0] = newX

    msg = "BRAILLE: Panning right. Amount: %i (from %i to %i)" % (panAmount, oldX, viewport[0])
    debug.println(debug.LEVEL_INFO, msg, True)
    return oldX != viewport[0]

def processRoutingKey(event):
    """Processes a cursor routing key event.

    Arguments:
    - event: an instance of input_event.BrailleEvent.  event.event is
    the dictionary form of the expanded BrlAPI event.
    """

    # If a message is being flashed, we'll use a routing key to dismiss it.
    #
    if _flashEventSourceId:
        killFlash()
        return

    cell = event.event["argument"]

    if len(_lines) > 0:
        cursor = cell + viewport[0]
        lineNum = viewport[1]
        _lines[lineNum].processRoutingKey(cursor)

    return True
