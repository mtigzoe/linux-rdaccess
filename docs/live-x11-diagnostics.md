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

## Num Lock finding, 2026-10-04 (investigation open)

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
