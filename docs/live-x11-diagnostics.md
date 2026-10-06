# Local X11 live diagnostics

`diagnostics/live_x11.py` operates on the existing XFCE X11 session. It detects
the user's graphical-session environment and requires it to match `--display`
(default `:0`). It does not start a desktop, xrdp session, application, Orca,
relay, or remote-control server.

Run from the repository with Mint's system Python, which provides PyGObject
and AT-SPI. X11 queries need libX11; input needs libXtst; window selection and
activation need xdotool. AT-SPI calls have timeouts and tree traversal is
bounded. A missing focus result means focus was not found within those bounds,
not proof that an application has no accessibility support.

## Read-only inspection

```sh
python3 diagnostics/live_x11.py --display :0
python3 diagnostics/live_x11.py --display :0 --watch-locks 30
python3 diagnostics/live_x11.py --display :0 --target firefox
python3 diagnostics/live_x11.py --display :0 --target thunar
```

Lock queries use `XkbGetIndicatorState` and `XkbGetNamedIndicator`, reading the
server's real Num Lock, Caps Lock, and Scroll Lock indicators. Missing named
indicators are reported as unavailable with a null state, never as OFF.
`--watch-locks` prints changes in indicator state and elapsed observation time;
it does not listen for keyboard events or infer state from a key press. A
named indicator can exist without an effective toggle binding in the current
XKB layout, so state and layout must be considered separately.

Window inspection lists numeric IDs and process IDs, never titles. Only
visible Thunar/Firefox windows belonging to the current Unix user are eligible.
If multiple windows match, select one with `--window ID`. Activation is explicit:

```sh
python3 diagnostics/live_x11.py --target thunar --window 12345 --activate
```

The focus reader inspects AT-SPI focus, name, role, and states within the target
process. In-memory callers can inspect the name; terminal reports replace all
names with `[redacted]`, retaining only whether a name exists. Password-field
names are never queried. The tool does not query text, clipboard, braille,
speech output, or connection configuration.

## Controlled navigation

```sh
python3 diagnostics/live_x11.py --target thunar --activate --key Tab --key Shift+Tab
```

The allowed inputs are Tab, Shift+Tab, Left/Right/Up/Down, Home/End, Prior/Next
(Page Up/Down), Escape, Return, Control_L, Num_Lock, Caps_Lock, and Scroll_Lock.
There is no text-entry facility or arbitrary key/chord command. Return may
activate a control; specify it only when that action is intended. Lock inputs
are explicit, and the tool does not automatically restore their state.

Input reuses the exact production XTest implementation and transactional
ownership wrapper from `remote_access.py`. It uses a separate connection and
refuses fallback to another injection backend. Existing held input/modifier
keys cause refusal. The selected target must be active immediately before
each test step; successful chord presses receive matching releases even when
a later press fails. Output identifies steps by number, without input names.

Each step reports sanitized focus before/after, input submission time, and time
until a different focused accessible is observed. Submission time measures
enqueueing XTest events, not application completion. Focus observation includes
AT-SPI queries and polling and is an upper bound on application response time;
a null latency means no change was observed within the timeout. It does not
prove that NVDA spoke, or that a Windows key traversed the network. Those
end-to-end observations still require the Windows controller. Other desktop
activity can affect a live run, so run during an idle interval.

## Optional screenshot

```sh
python3 diagnostics/live_x11.py --target firefox --screenshot /private/directory/debug.png
```

This explicitly captures only the selected window to a PNG with permissions
0600, using an atomic replacement. Screenshots can contain private visible
content; they are opt-in debugging artifacts, never accessibility assertions.
No screenshot is taken during ordinary inspection or navigation.

## Verification

```sh
xvfb-run -a python3 -m unittest -v tests.test_live_x11 tests.test_xtest_injection
```

The diagnostic integration tests refuse `:0`: they change and restore Num Lock
on an isolated X server, verify named XKB state, check held-modifier refusal,
and check failed-release ownership. Unit tests cover sanitized output, argument
errors, chord cleanup, unavailable indicators, and refusal of inactive targets.

## Historical Num Lock finding, 2026-10-04

The user reported silence after Num Lock while controlling Linux through
Windows NVDA Remote. The local `:0` baseline was indicator mask 0, with Num
Lock/Caps Lock/Scroll Lock all OFF. A subsequent read, after requesting one
Windows press and without injecting any lock keys, reported mask 2 and Num
Lock ON; Caps Lock/Scroll Lock remained OFF. Confirmation tying that transition
to the requested Windows press and its speech outcome is still pending.

The installed injection mapping includes all three lock keys. Orca 42 normally
presents Num Lock through `Script.presentKeyboardEvent`, `speech.speakKeyEvent`,
and `SpeechServer.speakKeyEvent` -> `speak` -> `_speak`. The installed remote
customization hooks `_speak`, so this path can already forward lock speech.
The saved settings inspected do not explicitly disable lock presentation.
Orca 42 derives Num Lock/Caps Lock echo state from event modifiers; it returns
no on/off state for Scroll Lock. Caps Lock can instead be an Orca/NVDA modifier.
These source facts do not establish where the reported live speech was lost.

There is no independent resulting-XKB-state feedback in the controller today.
If the controlled press is confirmed to toggle Linux with no remote speech,
classify the symptom as missing lock feedback, not failed XTest injection.
The next diagnosis must distinguish absent/suppressed Orca presentation from
lost forwarding before choosing a fix. A possible narrow fix would query the
resulting Num Lock indicator after successful input and speak a fixed state
message through the existing Orca/Remote path, with duplicate suppression,
main-thread scheduling, and reconnect guards. It is not implemented while the
root cause remains unresolved. No lock behavior or injected patch version has
changed, and no announcement regression has been added.

Live Caps Lock/Scroll Lock feedback remains untested. Thunar Tab/Shift+Tab is
still pending. A harness exercise in the existing Firefox window did observe
page-tab -> push-button -> page-tab for Tab/Shift+Tab, with lock state unchanged;
this validates local focus inspection/injection only, not Windows NVDA speech.

## Lock feedback correction, 2026-10-05

The v35 controller added explicit Caps Lock and Num Lock announcements, but
queried their XKB state in a queued callback after key-down. Isolated Xvfb
testing of the production injection code showed that a lock switching off can
remain on until key-up. Announcing while the key is held therefore reports the
old state. If several toggles finish before the callback runs, reading the state
then also reports the final result for every queued announcement.

Controller v36 captures the named XKB indicator immediately after a successful,
owned key release and carries that result to Orca's main-thread announcement.
Failed or unowned releases do not announce. Existing Num Lock repeat filtering,
CapsLock NVDA-command deferral, and queued-operation generation guards remain
in use. The regression checks run against an isolated X server; they do not
establish that Windows NVDA spoke the result.

The live Linux Mint check found the XFCE desktop on `:0`, with Num Lock on and
Caps Lock off. Orca calls `setproctitle`, which can erase its initial environment
from `/proc/PID/environ` while keeping Python's runtime environment intact.
Missing display or session-bus entries in that file therefore do not establish
that Orca is attached to the wrong desktop. Start Orca in the desktop session
using `start-orca-session.sh` or the session-discovering `linux-rdaccess connect`
command. Confirm both actual Linux state and Windows speech when repeating the
remote test.

After installing v36, a diagnostic restart with `SPT_NOENV=1` confirmed one Orca
process using XFCE's display and session bus, all installed patch checks current,
and an established connection to the configured NVDA relay. The complete suite
passed 533 tests under Xvfb; the four new lock regressions also passed separately.
Windows-side speech still requires a live remote test.

## Disabled Caps Lock action, 2026-10-05

The user confirmed Num Lock worked after v36, but a single Caps Lock press left
typing lowercase. Live production XTest gestures, both immediate and held for
150 ms, also failed to toggle Caps Lock. The active XKB Caps Lock interpretation
used `NoAction()`, although saved Orca preferences used Insert and keypad Insert
as modifiers. This disabled action matches Orca's Caps-as-modifier mapping;
the available evidence does not establish when it was left in the active map.

The active map was backed up, and only the Caps Lock action was changed to
`LockMods(modifiers=Lock)`. All other source bytes were preserved, and the map
compiled before application. A production Caps Lock tap then changed the real
indicator from off to on, and a second tap restored its initial off state.
Orca was replaced so it cached the repaired map; a graceful shutdown could have
restored its previous cached map. After replacement, the action remained enabled,
the Caps-only test passed again with its initial state restored, one Orca process
matched the desktop session, all patch checks were current, and the configured
NVDA relay connection was established. Windows-side input and speech still need
the user's remote retest.

## Windows keyboard-script trial, 2026-10-05

Desktop Commander on Windows reported NVDA in the same desktop session with
scripted keys enabled. A focused `SendInput` script compiled with the expected
40-byte input structure, submitted the user's Insert+Alt+Tab shortcut, and
completed paired Caps Lock and Num Lock taps with matching key releases.
Mint's named XKB indicators changed during observation and finished with Caps
Lock off and Num Lock on. More transitions occurred than the script's taps
explain, including Num Lock changes before the scripted Num Lock trial. The
user then confirmed they were also manually testing during the script trial
and that Windows NVDA announced the states of both Caps Lock and Num Lock.
This resolves the extra-transition ambiguity and confirms user-observed remote
lock feedback. It does not isolate every transition as scripted input. The
observer was stopped afterward; no Windows NVDA speech was captured by tools.

## Native Firefox keyboard processing repair, 2026-10-05

The user reported that plain Up/Down did not work in Firefox. The installed
Orca Remote customization wrapped `KeyboardEvent.process` but called the newer
`is_pressed_key()` method; Mint's Orca 42 supplies `isPressedKey()`. An
unconditional call raised before delegation to Orca's native processor. A
harness using the actual installed wrapper reproduced the exception for both
arrows' presses and releases, with zero native handler calls. Other directly
translated commands could still work because they bypass that processor.

The customization updater now replaces the known wrapper's press-state calls
with a helper supporting both APIs. Native processing, injection markers,
management shortcut releases, and master forwarding keep their existing
handler chain. The raw customization keyboard debug logger is disabled. A
separate customization marker and validator let `doctor` detect missing or
incomplete repair; the controller remains v36 and local-machine remains v10.
The repair was installed and Orca replaced in the existing desktop session.
All four patch checks then reported current.

A known local Firefox navigation fixture was opened in a new tab. Before the
repair, local Up/Down left its caret unchanged. Afterward, document caret and
focus changes were observed, and a bounded X11 check confirmed Windows Down
presses/releases reached Mint after switching remote control on. Additional
arrow events and focus changes occurred outside the scripted taps, so these
observations do not isolate each transition or establish correct line-by-line
remote behavior. A metadata-only Windows speech-probe receiver received no
events; probe activation/output is therefore unverified for this trial.

The full isolated-Xvfb suite passed 546 tests after the final validator
hardening. Regressions include native arrow delegation with both event APIs,
press/release injection-marker ownership, management shortcut releases,
master forwarding, safe debug behavior, private backups, idempotence, and
refusal of altered helpers or local helper shadowing. These tests establish
the repaired processing path, not complete NVDA parity or Windows audio.
The [shortcut audit](nvda-orca-shortcut-audit-2026-10-05.md) records remaining
command/layout gaps and the pending end-to-end Firefox matrix.
