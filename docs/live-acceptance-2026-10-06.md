# Live acceptance record, October 6, 2026

PR #14 remains unmerged. The baseline is documentation revision `edff42a`,
with tested production code from `4372efd` (controller v79, local-machine v11).
This record supplements the [eighteen-area checklist](compatibility-audit-2026-10-06-followup.md).
It records readiness and live observations separately from the completed 758-test
automated run. No production behavior is changed for this acceptance phase.

## Readiness observed at 17:25 UTC

- Windows Desktop Commander device `LAPTOP-A3REH38I` was offline, last seen
  approximately 17 hours earlier. One Desktop Commander call listed devices;
  no Windows input was sent.
- Mint's existing XFCE/X11 display `:0` was accessible.
- One Orca process was running; all seven installed patch checks were current.
- Orca had zero established TCP connections at the observation time. This
  establishes no live relay session at that instant, rather than a diagnosis
  of the relay's availability or configuration.
- Firefox had no running process or visible window.
- Named XKB Caps Lock, Num Lock and Scroll Lock indicators were available and
  all off. No lock keys were injected during these observations.

This is the historical preflight; subsequent readiness observations follow.

## Live-session preparation

- Windows Desktop Commander was subsequently online. One Windows NVDA process
  was running, using desktop keyboard layout and `NVDAModifierKeys = 7`.
- The requested controlled page was launched on Mint. Firefox exposed a focused
  `document-web` on window 69206020; its initial process ID was 470454.
- Orca then had one established TCP connection. This confirms an established
  local transport, but does not establish that Windows has enabled remote control.
- Linux lock indicators remained all off.
- The Windows diagnostic speech add-on was already installed. Port 8765 was
  listening on Windows; a metadata-only Linux receiver was started on loopback.
  Probe activation, event delivery and actual audio remain to be established.
- The page was extended with form controls, ARIA heading levels 7–9 and a
  coordinate table after initial launch; the loaded page must be refreshed before
  those targets are tested. An initial heading scan found none of these added
  targets on the previously loaded version; this is not a browser-exposure failure.
- Confirmation of “Control computer remote” and an idle interval is pending.
  The user has also been asked which physical braille display is available.
- The temporary Linux speech receiver was stopped while awaiting readiness.
  It received no events during preparation; this does not diagnose the speech
  path because probe activation was not confirmed. No Windows test input was sent.

One Windows preparation query was rejected by automatic approval review because
it included SSH host metadata and installed-add-on data beyond the test's scope.
No such data was returned. Preparation continued without reading SSH host
configuration, using only the already installed speech probe and a port-listener
check. No production code, SSH configuration or add-on was changed.

## Controlled page

Use [firefox-acceptance.html](../tests/fixtures/firefox-acceptance.html), opened
locally in Firefox. It has distinct browse paragraphs, a textarea, a genuine
multiline `contenteditable`, other labelled form controls, paired ARIA headings
at levels 7–9, a four-by-four coordinate table, six numbered reading segments and
a long braille reference. Reloading restores edited text. The page has no scripts, external
resources, network forms or automatic focus changes.

Before each trial, identify the NVDA keyboard layout and configured NVDA modifier
on Windows, the starting focus/mode and the starting lock states. Designate one
input source and send one action at a time; simultaneous manual and scripted
input invalidated an earlier lock trial. Linux-injected input is useful for
isolating a failure but does not count as Windows-to-Linux acceptance.

## Required acceptance sequence

The following order is the user's instruction. PR #14 must not be merged after
initial Firefox success: lock, speech, reconnect and physical braille acceptance
must be completed first. A Linux observation alone cannot close a listening or
hardware check.

| Check | Action and observations needed | Current result |
| --- | --- | --- |
| 1. Browse/focus transitions and address-bar isolation | Ctrl+L enters chrome. NVDA+Space there must retain browser-chrome focus. Return to verified document focus, use Down/Up and test the document mode toggle. Record Linux caret/mode and Windows speech. | Inconclusive preparation/input trial: an intact Windows Ctrl+L chord reached Linux, alongside repeated unplanned Down events. Address-bar isolation not yet tested. |
| 2. Form fields/contenteditable | Enter the labelled input, textarea and rich editor, navigate known lines, return to browse text, and revisit the address bar. Record actual focus/mode, caret movement and spoken text. | Not run. |
| 3. Single-letter and reverse navigation | Test H/Shift+H, K/Shift+K, D/Shift+D and supported control types against known targets in browse mode; verify reverse targets and that letters remain editor input in focus mode. | Not run. |
| 4. Heading levels 7–9 and F/Shift+F | Inspect actual Firefox heading roles/level attributes, then test each level forward twice and back once. Test native form-field jumps in both directions, checking mode after each jump. | Exposure prerequisite observed: both headings at each level 7, 8 and 9 have heading roles and matching numeric attributes. Navigation not run. |
| 5. Table movement and first/last row/column | Test Ctrl+Alt+Arrows in document browse mode. From confirmed R2 B, test Ctrl+Alt+PageUp, PageDown, Home and End separately; expected targets are Column B header, R3 B, Row two header and R2 C. Record any XFCE workspace movement. | Exposure prerequisite observed: native table reports four rows/four columns and known headers/cells. Navigation not run. |
| 6. NVDA+F7 | Check chooser categories/order, an actual native result list, Escape/focus restoration, remembered category and activation of a known result. | Not run. |
| 7. Caps Lock/Num Lock | Test each lock separately from a recorded baseline. Match Windows modifier behavior, Linux indicator and spoken state; verify Caps typing case in the controlled editor, then restore initial states. | Baseline both off; remote trial not run. |
| 8. Ctrl interruption and Say All | Desktop NVDA+Down starts Say All at the reading section. Listen for later segments, interrupt during an utterance with Ctrl, and check no later chunks resume. Repeat with slower Windows speech to compare audible and caret/current-line positions. | Not run; local-synthesizer pacing remains a known limitation. |
| 9. Disconnect/reconnect with held modifiers | Test a held modifier and navigation key in separate trials: disconnect during hold, release while disconnected, reconnect, then try fresh navigation. Record disconnect mechanism, held state, repeats, modifier effects and speech. | Not run. |
| 10. Braille pan/routing/to-focus | Record physical display model/cell count, translation table and tether mode. Pan both ways on known long text, route a known character, return to focus and change line. Record physical cells, routing position and focus following. | User confirms Eurobraille b.note connected to Windows NVDA and readable. Cell count, table/tether and hardware actions remain untested. |

## First Windows input trial, 17:55–18:04 UTC

The user confirmed Windows had announced “Control computer remote” and both
keyboards were idle. They confirmed a Eurobraille b.note was connected and that
they could read braille. No particular cell count is assumed.

Orca was temporarily restarted with a reviewed metadata observer to report
real mode, cached caret, table position and Say All flags. This restart is a
setup event, not a reconnect acceptance test. The relay reconnected once.
The observer emits only numeric state and fixed tokens from this exact local
fixture, and is scheduled for a bounded fifteen-minute interval.

The Windows sender used `SendInput` with a verified 40-byte input structure,
explicit extended-key flags and paired releases. It submitted an initial Down,
then attempted refresh and document-start commands. An extra Firefox window and
menu focus appeared; one later navigation step was refused because Windows
reported a planned key/modifier held. A subsequent fixed allowlist query found
none held. `handleInjectedKeys = True` is present in Windows NVDA's saved
keyboard settings. Submission success establishes Windows input enqueueing,
not receipt by NVDA or Linux.

After restoring the controlled window, Escape and Ctrl+L were submitted.
Another attempted isolated pair was refused by the held-key guard. No refused
step is treated as delivered. The guard message was then extended to identify
only the planned virtual-key code when refusal occurs; this is a temporary
sender diagnostic, not a production change.

A fresh local fixture tab was opened to load the added targets. Local setup
actions are separate from Windows acceptance. A bounded read-only AT-SPI scan
confirmed both known headings at each level 7–9, all labelled control targets,
and the four-by-four coordinate table. An older fixture tab also remained open.

At 18:03:55 UTC the Windows script submitted the user's Insert+Alt+Tab management
shortcut, then Ctrl+L at 18:03:58 UTC. A 25-second Linux query watched only the
planned test keys, without injecting input. It observed Control_L and `l`
held together and subsequently released. It also observed numerous Down
press/release states before, during and after that chord, although this script
contained no Down. XTest cannot identify the source of these events.

Input testing was paused and the user was asked whether any keyboard or b.note
navigation keys were in use during that interval. The source is unconfirmed;
neither user interference nor a bridge defect is assumed. No focus, navigation,
speech or lock acceptance result is passed from this mixed trial. The speech
metadata receiver received no events during this interval; probe activation
has not been established, so absence is inconclusive.

A read of only the relevant saved Windows braille settings found automatic
display selection, automatic tether and `en-ueb-g2.ctb` for output and input.
Saved automatic choices do not identify the active driver, cell count or actual
tether at the time of a gesture. The b.note's physical observations are still
required. No display configuration was changed.

Test input remained paused pending the source question. The temporary speech
receiver was stopped and Orca restarted normally without the metadata observer,
so the temporary diagnostic does not remain active during ordinary use. This
cleanup does not close the reconnect or held-modifier acceptance checks.

Keep each observed interval bounded to 30–60 seconds. Read-only local commands:

```sh
/usr/bin/python3 diagnostics/x11/live_x11.py --display :0 --target firefox
/usr/bin/python3 diagnostics/x11/live_x11.py --display :0 --watch-locks 30
```

`live_x11.py` reports sanitized focus role/state and actual lock indicators.
It does not report the virtual cursor, words spoken or Windows key state.
The AT-SPI event probe can report event types/counts, but those alone do not
establish correct line content or review semantics. Match a known remote action
to local observations and Windows listening before marking a check passed.

The [optional Windows speech probe](nvda-speech-probe.md), if already installed
with a working SSH forward, proves only that NVDA queued speech. It does not
prove audible output, completion, cancellation or speech origin. Metadata-only
events do not establish announcement wording. No diagnostic add-on or SSH
configuration change is required merely to begin manual listening tests.

For every trial, record the exact Windows gesture, starting context, Linux
observation, Windows spoken or tactile observation, and whether the original
state was restored. Distinguish passed, failed, inconclusive and not run.
An unexpected result should first be reproduced with one input source before
changing production code. The other acceptance areas remain open.
