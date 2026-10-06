# Compatibility follow-up, October 6, 2026

The current tested repository revision is `4372efd`: controller v79 and
local-machine v11. It includes the following source-reproduced repairs after
the earlier v40 audit. The broader committed shortcut updates are described in
the README; this report concentrates on the reproduced defects and their limits.
No Desktop Commander calls were used.

## Reproduced repairs

- **Current line:** Orca's web handler selected a physical or cached browse
  caret according to stale flags from the previous command. An explicit report
  now selects the native branch for current browse/focus context and restores
  those flags in `finally`. A focused editor or address bar is not replaced by
  a stale page caret. Tests execute the installed Orca 42 handler.
- **Browse/focus toggle:** NVDA+Space in Firefox's address bar could grab an
  editor cached in the document. The adapter and fallback decline this command
  outside document content, retaining the native manual switch in documents.
- **Pass next key:** Receive-thread and GLib ordering could consume the intended
  key, bypass more than one gesture, or re-arm a used request. Each request now
  owns one delivered gesture plus its repeats/releases. Native FIFO claims
  include ordinary forwarded events, so an earlier normal key cannot take a
  later bypass claim. Failure rolls claims back; handoff expires owned work.
  Tests exercise the installed Orca event processor in both activation orders.
- **Elements List:** The category chooser temporarily becomes Orca's active
  script. Immediate native-list creation could use that dialog's script or send
  fallback keys to it. List opening now waits for the original script, window
  and document, with a two-second monotonic deadline, request/generation checks,
  and protection against another F7 opening a nested chooser.
- **Speech protocol:** Ordinary Orca text was sent as a scalar `sequence`, which
  NVDA's decoder iterates as individual characters. Strings now become a
  one-element sequence, preserving existing sequences and command order.
- **Say All callbacks:** The remote speech wrapper returned before invoking
  native synthesis, and the mute wrapper suppressed its callbacks. Orca's
  iterator therefore could stop after the first chunk. Callback-bearing speech
  now uses the genuine Orca/Speech Dispatcher path at backend volume -100,
  restoring client volumes and method ownership afterward. END advances the
  iterator; CANCEL stops it; native index marks update progress. Tests execute
  the frozen installed `_speak`, `_apply_acss`, `_send_command` and `_say_all`
  methods, including cache, reset and failure cases.

Say All timing follows the local synthesizer rather than Windows speech
completion. Different local and Windows rates can make caret progress differ
from what NVDA is currently speaking. The silent callback path requires the
supported native Speech Dispatcher API on the main thread; unsupported paths
do not fall back to audible synthesis or fabricated completion events. Ordinary
remote speech remains suppressed locally. No real Windows speech result is
claimed by these tests.

## Validation

The full isolated X11 suite passed **758 tests**:
`xvfb-run -a /usr/bin/python3 -m unittest discover -s tests`.
Another **158 tests** passed with the default Python interpreter, covering the
adapter, direct commands, modal focus, pass-next, speech, upgrades and CLI.
`git diff --check` passed. Genuine v40 generated output from `af9dff7` extends
the upgrade fixtures. These checks establish local implementation behavior,
not NVDA equivalence across every application.

The revision is installed on Mint. All seven installed patch checks report
current. A temporary metadata-only runtime probe confirmed that the keyboard
controller, native event adapter, speech sequence helper and Say All callback
helper loaded, and that the automatic relay retry worker was running. The relay
remained disconnected during that observation, so no Windows-to-Linux keyboard
or speech result was obtained. Orca was then restarted normally: one Orca process
is running, the temporary probe is absent from its environment, and all seven
patch checks remain current.

## Remaining acceptance checklist

The user's eighteen areas remain open for semantic, hardware or end-to-end
acceptance. Source repairs above provide partial coverage rather than closing
these areas:

1. NVDA navigator-object hierarchy versus Orca object navigation.
2. NVDA review cursor versus Orca flat review.
3. Review word, character and line semantics.
4. Repeated report, spelling and clipboard commands.
5. NVDA+K exact URL behavior.
6. NVDA+B foreground-window reading.
7. NVDA+Ctrl+Space embedded-object escape.
8. A/M/N/O/W web quick-navigation types absent from Orca 42.
9. Full table row and column reading.
10. Browse-mode Alt+Up/Down collapse and expand.
11. Ambiguous desktop keypad input without key name or scan code.
12. Braille tether/focus and previous/next-line semantics.
13. Hardware braille routing, panning and returning to focus.
14. Real Caps Lock and Num Lock through Windows NVDA Remote.
15. Ctrl interruption during Windows speech and Say All.
16. Disconnect/reconnect with real held modifiers and navigation keys.
17. Firefox address bar, document and contenteditable transitions.
18. Thunar, XFCE panels/menus, Settings Manager, GTK file dialogs,
    authentication dialogs, notifications, Update Manager, Software Manager,
    Mousepad/Xed and VS Code.

Tests still need to account for window-manager grabs and identical local versus
injected keys, which XTest cannot distinguish. Braille checks should include a
remote display narrower than Orca's default viewport. Transport cleanup after
socket/select failures also needs a separate lifecycle check.

Protocol and native behavior references:
[NVDA speech decoder](https://github.com/nvaccess/nvda/blob/master/source/_remoteClient/serializer.py),
[NVDA browse-mode toggle](https://github.com/nvaccess/nvda/blob/release-2026.2/source/globalCommands.py#L2379-L2409),
[Speech Dispatcher espeak volume mapping](https://github.com/brailcom/speechd/blob/master/src/modules/espeak.c).
The installed Orca 42 source supplies the native methods used in the regressions.
