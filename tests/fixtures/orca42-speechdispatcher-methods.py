# Copyright 2006, 2007, 2008, 2009 Brailcom, o.p.s.
#
# Author: Tomas Cerha <cerha@brailcom.org>
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

# # [[[TODO: richb - Pylint is giving us a bunch of warnings along these
# lines throughout this file:
#
#  W0142:202:SpeechServer._send_command: Used * or ** magic
#
# So for now, we just disable these warnings in this module.]]]
#
# pylint: disable-msg=W0142

"""Provides an Orca speech server for Speech Dispatcher backend."""


# Frozen Orca 42.0 methods for isolated speech callback regression tests.
# Source: /usr/lib/python3/dist-packages/orca/speechdispatcherfactory.py

class SpeechServer:
    def sayAll(self, utteranceIterator, progressCallback):
        GLib.idle_add(self._say_all, utteranceIterator, progressCallback)

    def stop(self):
        self._cancel()

    def _apply_acss(self, acss):
            if acss is None:
                acss = settings.voices[settings.DEFAULT_VOICE]
            current = self._current_voice_properties
            for acss_property, method in self._acss_manipulators:
                value = acss.get(acss_property)
                if value is not None:
                    if current.get(acss_property) != value:
                        method(value)
                        current[acss_property] = value
                elif acss_property == ACSS.AVERAGE_PITCH:
                    method(5.0)
                    current[acss_property] = 5.0
                elif acss_property == ACSS.GAIN:
                    method(10)
                    current[acss_property] = 5.0
                elif acss_property == ACSS.RATE:
                    method(50)
                    current[acss_property] = 5.0
                elif acss_property == ACSS.FAMILY:
                    method({})
                    current[acss_property] = {}

    def _speak(self, text, acss, **kwargs):
            if isinstance(text, ACSS):
                text = ''

            # Mark beginning of words with U+E000 (private use) and record the
            # string offsets
            # Note: we need to do this before disturbing the text offsets
            # Note2: we assume that text mangling below leave U+E000 untouched
            last_begin = None
            last_end = None
            is_numeric = None
            marks_offsets = []
            marks_endoffsets = []
            marked_text = ""

            for i in range(len(text)):
                c = text[i]
                if c == '\ue000':
                    # Original text already contains U+E000. But syntheses will not
                    # know what to do of it anyway, so discard it
                    continue

                if not c.isspace() and last_begin == None:
                    # Word begin
                    marked_text += '\ue000'
                    last_begin = i
                    is_numeric = c.isnumeric()

                elif c.isspace() and last_begin != None:
                    # Word end
                    if is_numeric:
                        # We had a wholy numeric word, possibly next word is as well.
                        # Skip to next word
                        for j in range(i+1, len(text)):
                            if not text[j].isspace():
                                break
                        else:
                            is_numeric = False
                        # Check next word
                        while is_numeric and j < len(text) and not text[j].isspace():
                            if not text[j].isnumeric():
                                is_numeric = False
                            j += 1

                    if not is_numeric:
                        # add a mark
                        marks_offsets.append(last_begin)
                        marks_endoffsets.append(i)
                        last_begin = None
                        is_numeric = None

                elif is_numeric and not c.isnumeric():
                    is_numeric = False

                marked_text += c

            if last_begin != None:
                # Finished with a word
                marks_offsets.append(last_begin)
                marks_endoffsets.append(i + 1)

            text = marked_text

            text = self.__addVerbalizedPunctuation(text)
            if orca_state.activeScript:
                text = orca_state.activeScript.\
                    utilities.adjustForPronunciation(text)

            # Replace no break space characters with plain spaces since some
            # synthesizers cannot handle them.  See bug #591734.
            #
            text = text.replace('\u00a0', ' ')

            # Replace newline followed by full stop, since
            # this seems to crash sd, see bgo#618334.
            #
            text = text.replace('\n.', '\n')

            # Transcribe to SSML, translating U+E000 into marks
            # Note: we need to do this after all mangling otherwise the ssml markup
            # would get mangled too
            ssml = "<speak>"
            i = 0
            for c in text:
                if c == '\ue000':
                    if i >= len(marks_offsets):
                        # This is really not supposed to happen
                        msg = "%uth U+E000 does not have corresponding index" % i
                        debug.println(debug.LEVEL_WARNING, msg, True)
                    else:
                        ssml += '<mark name="%u:%u"/>' % (marks_offsets[i], marks_endoffsets[i])
                    i += 1
                # Disable for now, until speech dispatcher properly parses them (version 0.8.9 or later)
                #elif c == '"':
                #  ssml += '&quot;'
                #elif c == "'":
                #  ssml += '&apos;'
                elif c == '<':
                  ssml += '&lt;'
                elif c == '>':
                  ssml += '&gt;'
                elif c == '&':
                  ssml += '&amp;'
                else:
                  ssml += c
            ssml += "</speak>"

            self._apply_acss(acss)
            self._debug_sd_values("Speaking '%s' " % ssml)
            self._send_command(self._client.speak, ssml, **kwargs)

    def _say_all(self, iterator, orca_callback):
            """Process another sayAll chunk.

            Called by the gidle thread.

            """
            try:
                context, acss = next(iterator)
            except StopIteration:
                pass
            else:
                def callback(callbackType, index_mark=None):
                    # This callback is called in Speech Dispatcher listener thread.
                    # No subsequent Speech Dispatcher interaction is allowed here,
                    # so we pass the calls to the gidle thread.
                    t = self._CALLBACK_TYPE_MAP[callbackType]
                    if t == speechserver.SayAllContext.PROGRESS:
                        if index_mark:
                            index = index_mark.split(':')
                            if len(index) >= 2:
                                start, end = index[0:2]
                                context.currentOffset = context.startOffset + int(start)
                                context.currentEndOffset = context.startOffset + int(end)
                                msg = "SPEECH DISPATCHER: Got mark %d:%d / %d-%d" % \
                                    (context.currentOffset, context.currentEndOffset, \
                                     context.startOffset, context.endOffset)
                                debug.println(debug.LEVEL_INFO, msg, True)
                        else:
                            context.currentOffset = context.startOffset
                            context.currentEndOffset = None
                    elif t == speechserver.SayAllContext.COMPLETED:
                        context.currentOffset = context.endOffset
                        context.currentEndOffset = None
                    GLib.idle_add(orca_callback, context, t)
                    if t == speechserver.SayAllContext.COMPLETED:
                        GLib.idle_add(self._say_all, iterator, orca_callback)
                self._speak(context.utterance, acss, callback=callback,
                            event_types=list(self._CALLBACK_TYPE_MAP.keys()))
            return False

    def _set_volume(self, acss_volume):
            volume = int(15 * max(0, min(9, acss_volume)) - 35)
            self._send_command(self._client.set_volume, volume)

    def _send_command(self, command, *args, **kwargs):
            try:
                return command(*args, **kwargs)
            except speechd.SSIPCommunicationError:
                msg = "SPEECH DISPATCHER: Connection lost. Trying to reconnect."
                debug.println(debug.LEVEL_INFO, msg, True)
                self.reset()
                return command(*args, **kwargs)
            except:
                pass
