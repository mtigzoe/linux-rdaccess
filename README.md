# linux-rdaccess

Experimental Linux accessibility bridge for Windows screen readers.

The project now supports two architectural directions:

1. **NVDA Remote + Orca Remote (recommended)** — Linux accessibility output is produced by Orca and transported directly to NVDA Remote on Windows. This avoids depending on an RDP client for accessibility and has already been validated for remote keyboard control, NVDA speech, and braille.
2. **xrdp dynamic virtual channels (experimental)** — Linux AT-SPI focus/window data is forwarded through xrdp DVC channels to the Windows rdAccess NVDA add-on.

The xrdp implementation is being retained for research and future native RDP integration. It is no longer the recommended path for normal use.

## Recommended architecture

```text
Windows NVDA
    ⇅
NVDA Remote protocol
    ⇅
Orca Remote on Linux
    ⇅
Orca / AT-SPI
    ⇅
Linux applications
```

This path does not require Windows App or Remote Desktop Connection for accessibility. RDP may still be used independently for visual desktop access, but it is not part of the accessibility transport.

See [docs/nvda-remote.md](docs/nvda-remote.md) for the current tested design and known compatibility work.

## Windows controller with uv (PowerShell)

The optional Windows controller lets you run the installed Linux `linux-rdaccess`
commands over SSH using a keyboard-accessible numbered menu. It requires
[uv](https://docs.astral.sh/uv/), the Windows OpenSSH client, and SSH access
to a Linux machine with `linux-rdaccess` installed.

In PowerShell, from a Windows clone of this repository:

```powershell
uv venv
uv run --no-project python .\linux_rdaccess_windows.py configure
uv run --no-project python .\linux_rdaccess_windows.py
```

The first command creates a local `.venv` directory. The `--no-project`
option lets uv use the environment without requiring a `pyproject.toml` or
trying to install the Linux-specific project dependencies. The Windows
controller uses only the Python standard library.

You can also run an individual command directly:

```powershell
uv run --no-project python .\linux_rdaccess_windows.py connect
uv run --no-project python .\linux_rdaccess_windows.py status
uv run --no-project python .\linux_rdaccess_windows.py doctor
uv run --no-project python .\linux_rdaccess_windows.py compatibility
uv run --no-project python .\linux_rdaccess_windows.py disconnect
```

### Verify connection and start the Linux bridge

After configuring SSH once, check that the Linux command is installed and
the Remote Access configuration is ready:

```powershell
uv run --no-project python .\linux_rdaccess_windows.py status
```

Example (the relay address and port depend on your own Linux configuration):

```text
host: <configured relay address>
port: <configured relay port>
role: host
orca_connection_type: slave
key_configured: True
mute_local_orca_speech: True
ready: True
autostart_enabled: True
command_installed: True
orca_remote_config_found: True
```

A `ready: True` status means the Linux-side saved configuration is ready; it
does **not** confirm that Windows NVDA is connected or that speech/braille
events have been verified. The `host` and `port` lines describe the Remote
Access relay, **not** the SSH host and SSH port set during Windows
`configure`.

Apply the saved Linux configuration and start or restart Orca:

```powershell
uv run --no-project python .\linux_rdaccess_windows.py connect
```

Expected output when configuration succeeds:

```text
Configured <configured relay address>:<configured relay port> as role host.
Remote Access key remains hidden.
```

The Windows controller runs the installed Linux command through
`~/.local/bin/linux-rdaccess`, so it works even if non-interactive SSH
sessions omit `~/.local/bin` from PATH. `connect` returning successfully
means the Linux command completed, not that the Windows NVDA Remote Access
add-on connected. Establish the NVDA Remote Access connection separately.


To run the Windows controller unit tests:

```powershell
uv run --no-project python -m unittest discover -s tests -p "test_windows_controller.py"
```

The controller prompts for the Linux hostname, SSH username, and port during
`configure`, and stores them under
`%APPDATA%\linux-rdaccess\windows-config.json` — **outside the repository**.
It does not save passwords or SSH private keys. Verify the SSH host-key
fingerprint on first use. The repository's `.gitignore` excludes `.venv/`
so the virtual environment is not committed.

For requirements, architecture, and troubleshooting, see
[Windows controller documentation](docs/windows-controller.md).

### PowerShell session helpers

From PowerShell in the Windows repository directory, run:

```powershell
.\start-windows-session.ps1
```

This creates `.venv` with `uv venv` if needed, prompts for SSH configuration
if none is saved, runs `linux-rdaccess connect` on Linux, and checks its status.
To change the SSH target:

```powershell
.\start-windows-session.ps1 -Configure
```

To skip the status check after connecting:

```powershell
.\start-windows-session.ps1 -SkipStatus
```

To disable the Linux-side Orca Remote auto-connection:

```powershell
.\stop-windows-session.ps1
```

These scripts are Windows-side counterparts to the Linux session helper, but
they do **not** launch or connect the NVDA Remote Access add-on: NVDA must be
running and its Remote Access connection must be handled separately. They also
do not replace `start-orca-session.sh` when the Linux desktop requires
explicit Orca session startup. No personal hostname or username is embedded
in the scripts. If PowerShell blocks locally downloaded scripts, inspect
them and use a process-scoped execution policy if permitted by your system
administrator.

### Run the test suite with uv

From the repository root, run all tests discovered under `tests/`:

```powershell
uv run --no-project python -m unittest discover -s tests -t .
```

This command discovers all tests, but the complete suite targets Linux (including X11, Orca, and POSIX file permissions), so it is **not expected to pass on native Windows**. GitHub Actions runs the Linux suite with uv and publishes the results. On Windows, run only the controller tests:\n\n```powershell\nuv run --no-project python -m unittest tests.unit.windows.test_windows_controller\n```\n\nFor Linux CI results, see [Full unittest suite with uv](https://github.com/mtigzoe/linux-rdaccess/actions/workflows/uv-unittest.yml). The workflow retains a downloadable unittest log even when tests fail.

## Install once, then use simple commands

From a clone of this repository on Linux Mint:

    python3 linux_rdaccess.py install

That installs a user command at:

    ~/.local/bin/linux-rdaccess

and enables login autostart by default.

If you do not want autostart:

    python3 linux_rdaccess.py install --no-autostart

Configure Linux as the computer controlled by Windows NVDA and generate a key:

    linux-rdaccess configure --role host --generate-key

Apply the saved configuration and connect:

    linux-rdaccess connect

If Orca cannot be restarted automatically from your current shell, apply the
configuration without restarting Orca, then start Orca in the active XFCE
graphical session with the helper script:

    linux-rdaccess connect --no-restart
    ./start-orca-session.sh

Disconnect while keeping the saved configuration:

    linux-rdaccess disconnect

Show redacted status:

    linux-rdaccess status

Enable or disable login autostart:

    linux-rdaccess autostart enable
    linux-rdaccess autostart disable
    linux-rdaccess autostart status

Show the keyboard shortcuts:

    linux-rdaccess shortcuts

Remove the installed command and autostart entry:

    linux-rdaccess uninstall

The saved Remote Access configuration is intentionally kept during uninstall.

When autostart is enabled, Linux runs:

    linux-rdaccess connect --quiet

after graphical login. The command applies the saved Orca Remote settings and starts Orca with `orca --replace`.

## NVDA compatibility on Linux applications

The goal is to make Windows NVDA control Linux applications through Orca and AT-SPI with familiar NVDA behavior while keeping Linux applications themselves in control of normal keyboard input.

### Firefox and web content

Orca provides native browse/focus modes and structural navigation for web content. Common single-letter navigation such as headings, links, form fields, buttons, combo boxes, entries, radio buttons, checkboxes, and heading levels is passed through to Orca/Firefox.

Plain Up/Down use Orca's native previous/next-line navigation in web document
browse mode. The customization patch supports Orca 42's keyboard-event API so
the upstream Remote wrapper reaches Orca's native event processor. `doctor`
checks this patch separately from input injection. Browser chrome, editable
fields, and focus mode retain the application's normal arrow handling.

NVDA's table commands Ctrl+Alt+Left/Right/Up/Down are translated to Orca 42's
Shift+Alt+Arrow table-cell navigation, but only for an arrow that arrived from
the remote session and only where Orca itself would use structural navigation
(web document, browse mode). Editable grids, focus mode and non-document windows
keep Ctrl+Alt+Arrow. NVDA's Ctrl+Alt+PageUp/PageDown/Home/End table-edge
commands are implemented with Orca 42's native table APIs: they preserve the
current column or row and re-read the caret/table when Orca's delayed consumer
runs, which also preserves nested/non-uniform table context. Set
`LINUX_RDACCESS_NVDA_TABLE_KEYS=0` to disable arrow translation. Desktop window
managers may grab Ctrl+Alt+Arrow (XFCE uses it for workspaces) before Orca sees
it; see the [shortcut audit](docs/nvda-orca-shortcut-audit-2026-10-05.md).
Queued table arrows and landmark keys have separate, bounded pending claims,
so fast presses retain their translations. Failed injection removes its claim.
XTest does not identify individual input sources: a simultaneous local press
of the same key can still be confused with a pending remote press. NVDA's
NVDA+Ctrl+Alt+Arrow row/column reading commands remain controller-consumed:
Orca 42 has no exact caret-preserving read-row/read-column equivalent, and
forwarding those chords into X11 could let XFCE intercept Ctrl+Alt+Arrow before
Orca sees them.

Compatibility covers the NVDA global and browse-mode gestures for which Orca
42 has a proven equivalent, and explicitly consumes known NVDA commands that
would otherwise execute unrelated Orca or Linux application shortcuts. Desktop
layout is the default. Set `LINUX_RDACCESS_NVDA_LAYOUT=laptop` in Orca's
environment to select NVDA's laptop keyboard layout. Laptop NVDA+A (caret Say
All), NVDA+L (current line), and NVDA+Shift+End (status) are translated
directly. Laptop review/object gestures whose semantics differ from Orca flat
review are consumed rather than misrouted.

linux-rdaccess additionally translates:

    NVDA+Space
        Toggle Orca browse/focus mode as a manual command, including editor focus

This lets Windows NVDA users use the familiar NVDA browse/focus gesture while controlling Firefox on Linux.
NVDA+V uses Orca's native web layout/object mode toggle in document content;
NVDA+Ctrl+F and NVDA+F3/Shift+F3 use Orca's native find commands. NVDA+Shift+F10
(native selection mode) and Alt+Up/Down virtual-caret collapse/expand are
consumed where Orca 42 has no equivalent, rather than falling through to an
unrelated Orca or application command.

Other NVDA chords translated to native Orca commands (desktop NVDA layout;
only with the NVDA key held and no Shift/Ctrl/Alt/Win unless noted):

    NVDA+1     Toggle input help using Orca learn mode
    NVDA+M     Toggle Orca mouse review
    NVDA+P     Cycle punctuation / speech-symbol level
    NVDA+U     Cycle progress-bar output: off, speech, beep, both
    NVDA+Up    Current caret line (without entering flat review)
    NVDA+Down  Say all
    NVDA+Tab   Where am I
    NVDA+T     Window title
    NVDA+End   Status bar
    NVDA+Shift+Up (desktop) / NVDA+Shift+S (laptop)
               Report current selection through Orca's native selection command
    NVDA+F12   Time; press twice quickly for date

The clock uses Orca's configured format and Linux time zone. NVDA+F12 is consumed
instead of reaching Orca's caret-navigation toggle. NVDA+1 toggles Orca learn
mode on and off rather than falling through to Orca's bookmark-1 command.

Known NVDA commands which still have no proven Orca 42 equivalent are consumed
when their physical gesture would otherwise run an unrelated Orca or Linux
application command. Examples include NVDA+2 through NVDA+7, NVDA+B /
NVDA+Shift+B, NVDA+F, NVDA+K, NVDA+S, NVDA+Ctrl+Space, and the unsupported
navigator/review hierarchy commands. These suppress incorrect side effects; they
do not claim equivalent functionality. Current-line reporting uses
Orca's native caret context and does not move the caret or review cursor; it
does not implement NVDA's double/triple-press spelling and character details.

NVDA's D (landmark) is Orca's M (Orca's own D is "live region"). A D typed in the
remote session is turned into the landmark key (Shift+D into previous landmark)
only where Orca itself would use structural navigation, i.e. browse mode on web
content. NVDA F/Shift+F use Orca's native form-field navigation, and heading
levels 7 through 9 use Orca's native heading-level factories even though Orca
42 only binds levels 1 through 6 by default. The decision is made on Orca's main thread inside `KeyboardEvent.shouldConsume`,
using Orca's own `useStructuralNavigationModel()`, and is re-read for every key,
so NVDA+Space toggling is followed immediately. Focus mode, edit fields, the
address bar, Ctrl/Alt+D, NVDA+D and any D from the Linux keyboard are never
translated. Set `LINUX_RDACCESS_NVDA_D_LANDMARK=0` in Orca's environment to turn
it off. The other single-letter keys (H K F B E X C R L I T G P Q S O, 1-6)
already match Orca 42 and are untouched. `tools/orca42_d_landmark_check.py` runs
the hook through real Orca 42 key matching.

Also translated (verified against Orca 42 key matching, which needs the modifier
state to be exactly Orca, so Shift is released around the key and restored):

    NVDA+Shift+Space   Single-letter navigation on/off   (Orca+Z)
    NVDA+F2            Pass the next key to the app      (Orca+BackSpace)

Orca+Z is Orca's toggle for structural-navigation keys. While it is off, the D
landmark translation above is off too, so single-letter keys never get in the
way of typing. Plain Shift+Space and plain F2 (Thunar rename) are untouched.

NVDA Ctrl+Alt+PageUp/PageDown/Home/End table-edge commands are implemented with
Orca's native table coordinates so they preserve the current column or row.
NVDA's row/column reading commands remain unsupported because Orca 42 has no
non-moving full-row/full-column presentation primitive.

Desktop keypad object-navigation interception uses unambiguous keypad VKs
(for example Numpad5, Minus, Divide, Multiply, and extended NumpadEnter) and,
for Numpad1-9/Delete, the low-level Windows scan code forwarded by NVDA Remote.
This distinguishes physical numpad navigation keys from dedicated navigation
keys that share the same VK. Legacy payloads without matching scan-code evidence
still pass through rather than being guessed as keypad input. NVDA's
Shift+Numpad1/2/3/7/9 review commands and Shift+NumpadDivide/Multiply mouse-lock
commands are also consumed when their keypad identity is proven, because Orca
42 either has no exact equivalent or assigns the physical gesture a conflicting
meaning; they are not falsely presented as implemented. These physical keypad
bindings apply in both NVDA keyboard layouts.
CapsLock and Insert presses used as NVDA modifiers are deferred so translated
or consumed NVDA commands do not leak those modifier presses into Linux. A
standalone CapsLock or Insert press is replayed as one complete press/release.

### Linux GUI and file manager

Normal application navigation remains unchanged and is forwarded directly:

    Tab / Shift+Tab
    Arrow keys
    Enter
    Space
    Home / End
    Page Up / Page Down
    standard Ctrl/Alt shortcuts

This is intentional: file managers and desktop applications expose their focused controls through Orca/AT-SPI, so their native keyboard navigation should not be replaced by a screen-reader-specific layer.

NVDA+F7 opens an NVDA-style category chooser using the NVDA 2026.2 default
categories and order: Links, Headings, Form fields, Buttons, and Landmarks.
The last selected category is remembered for the next invocation; Orca owns the
actual structural-navigation result list.

The compatibility layer is being extended for NVDA review commands, braille
panning/routing, braille keyboard input, speech interruption, and other
screen-reader-specific gestures.

### Current compatibility work

Implemented or under active testing:

    remote keyboard navigation
    NVDA speech from Linux
    remote braille output
    Ctrl/key speech interruption
    NVDA+Space browse/focus translation
    safe capture of NVDA braille-input gesture metadata

Synthetic braille command modifiers and the NVDA+F7 structural-list fallback
retain release ownership and make one bounded retry if a synthetic Shift/Ctrl/Alt
key-up is rejected. This avoids leaving a modifier held until the next
disconnect/reset. Braille callbacks share the controller input-ownership lock,
so a control handoff cannot split an in-flight emulated key gesture across two
sessions.

Braille pan back/forward are mapped generically from the NVDA script path
(`braille_scrollBack` / `braille_scrollForward`), not from a device model, and
run the active Orca script's `panBrailleLeft` / `panBrailleRight` on the GLib
main loop (so line wrapping and flat review work). Routing keys call the script's
`processRoutingKey` with the cell index. Both are unverified on a live session.
Braille keyboard input is still not forwarded.

Optional gesture trace (`~/.local/share/orca/orca-remote-braille-input.log`):
disabled by default. Set `LINUX_RDACCESS_BRAILLE_TRACE=1` in Orca's environment
to enable it. The file and rotated copy are mode 0600; rotation occurs at 256 KiB.
Only canonical supported command names are recorded; arbitrary identifiers,
driver metadata and unknown script paths are redacted. Braille-keyboard input
(dots/space) is typed text and remains
recorded only as `redacted` even when tracing is enabled. The patch also removes
upstream's debug line that logged the whole braille message.

### Live-test input trace

Set `LINUX_RDACCESS_TRACE=1` in Orca's environment to write a metadata-only trace
to `~/.local/share/orca/orca-remote-input-trace.log` (mode 0600, rotated at
256 KiB). It records, per remote key, whether the controller forwarded,
translated or suppressed it, the modifier ownership (received versus injected,
left/right distinguished, NVDA modifier, pending Caps Lock/Insert), the control
generation, XKB Caps/Num/Scroll Lock transitions, held-key release failures after a
reconnect, speech-cancel and stale main-loop events, braille command classes, and
the Orca-side browse/table decisions with a Firefox context class. A character
key is never identified, braille keyboard input, speech, clipboard data,
passwords and connection keys are never recorded, and every value is reduced to a
number, a boolean or a short fixed token before it is written. Summarize a run
with `python3 tools/summarize_input_trace.py --timeline`. See
[live-trace-diagnostics.md](docs/live-trace-diagnostics.md).

### Responsiveness

Upstream legacy Orca Remote started one `xdotool` process per key event, serially
on the receive thread. Measured on X11 that is about 38 ms per event (76 ms per
keystroke), so held arrow keys, fast typing and multi-key chords queued up and
played out late. `linux-rdaccess connect` now also patches `local_machine.py` to
inject keys in-process through XTest (about 0.03 ms per keystroke) and falls back
to `xdotool` for any key it cannot map. Upstream's per-keypress debug log (which
recorded key names, including typed passwords) is permanently disabled in both
patched modules, including when debugging is enabled. Setting
`LINUX_RDACCESS_DEBUG=1` enables timing diagnostics only. Speech interruption on held keys
is limited to once per 150 ms.

Ctrl now sends the NVDA Remote `cancel` message to the controlling NVDA
immediately. Other action keys cancel local Orca speech without sending an
additional protocol message. Previously only Linux-side speech was stopped,
and upstream defers the cancel to NVDA until the next utterance, so Ctrl with
nothing spoken afterwards never silenced Windows. Bare Shift/Alt/Insert/CapsLock/Win
do not cancel, so NVDA+key chords can keep reading.

The Linux-side speech stop runs on Orca's GLib main loop, coalesced, never on the
thread that receives keys: Orca's speech-dispatcher client is not thread-safe and
a stop blocks until speech-dispatcher answers, which froze key forwarding during
busy Firefox navigation. Remote clipboard writes are likewise moved off the
network thread (GTK is not thread-safe). Run `linux-rdaccess doctor` to check the
patches are active; set `LINUX_RDACCESS_DEBUG=1` to log key-handling stalls
(duration only, never which key) to `~/.local/share/orca/orca-remote-slow-events.log`.

Orca Remote's legacy transport is also patched so failed initial connections,
socket/select disconnects, and malformed relay frames cleanly tear down before
the native reconnect worker starts another attempt. The socket is shut down
before joining the sender thread so a blocked `sendall()` cannot stall cleanup.
Upstream clears `connected` before one cleanup path, while its original
`_disconnect()` returned immediately when `connected` was false; it also lets
JSON decode errors escape a receive loop that catches only `socket.error`.
A concurrent close can additionally make `select()` raise `ValueError` for an
invalid descriptor. A write-side `sendall()` failure can otherwise kill only
the sender thread while the transport still reports connected. v5 treats the
former as a disconnect and shuts down the socket on the latter so the receive
loop wakes and the reconnect worker stays alive. `doctor` reports the relay
transport cleanup separately.

Caps Lock, Num Lock, and Scroll Lock feedback reads the actual named XKB indicator after a
successful key release, when X11 has completed the toggle. The state is captured
before queuing the Orca announcement, so quick consecutive toggles retain their
individual on/off results. Num Lock and Scroll Lock auto-repeat produce one toggle and one
announcement per press. CapsLock used for a translated NVDA command produces
neither a lock toggle nor a lock announcement.

The current patches are controller **v95**, local-machine **v12**, and transport cleanup **v7**. Update the
installed command from the repository with `python3 linux_rdaccess.py install`,
then run `linux-rdaccess connect` to update the Orca-side files and restart Orca.
`doctor` verifies the connected patch hooks, valid Python, and the installed
Orca adapter against the adapter shipped beside the running CLI. Local Orca
speech resumes when the relay disconnects. Prototype RDP debug logs and dry-run
output also redact speech, protocol payloads, and backend exception messages.
Automatic startup uses the transport's retry worker so an unavailable relay
does not permanently stop connection attempts. `doctor` checks this patch too.
See the [hardening audit](docs/compatibility-audit-2026-10-04-hardening.md) for the
source evidence, regressions and remaining desktop checks.
The [October 6 audit](docs/compatibility-audit-2026-10-06.md) covers table/landmark
burst handling, manual focus switching, command retries, current-line reporting
and the clock shortcut conflict, plus automatic relay retries.
The [state and timing audit](docs/compatibility-audit-2026-10-07-live-edgecases.md)
records Orca 42 speech cancellation, stale browser actions, remote braille display
width and gesture ownership, focus restoration fixes, and the remaining live checks.
The [October 8 pre-live audit](docs/compatibility-audit-2026-10-08.md) records
Insert recovery, raw braille fallback, relay cancellation, SSH session discovery,
and actual Mint GTK focus checks. Run `python3 tools/gtk_atspi_smoke.py` on Linux
for its isolated GTK/AT-SPI regression smoke test.
The [follow-up audit](docs/compatibility-audit-2026-10-06-followup.md) records
current-line context, modal focus, pass-next ordering and speech/Say All repairs,
with the remaining eighteen acceptance areas.
The [live acceptance record](docs/live-acceptance-2026-10-06.md) supplies a
controlled Firefox page and the first Windows input, speech and braille checks.

## Live X11 + AT-SPI diagnostics

For live testing on the existing Linux Mint XFCE/X11 desktop, use the bounded
diagnostic driver in `diagnostics/live_x11.py`. It inspects the real X11 and
AT-SPI state that Orca uses, while keeping accessible names redacted in terminal
output by default.

Install the diagnostic dependencies on Linux Mint:

    sudo apt install -y python3-pyatspi python3-gi gir1.2-atspi-2.0 at-spi2-core xdotool xinput wmctrl x11-utils x11-xserver-utils x11-xkb-utils xvfb

Inspect the detected `:0` desktop and XKB lock indicators:

    python3 diagnostics/live_x11.py --display :0

Watch Num Lock, Caps Lock, and Scroll Lock state changes without listening for
ordinary typed keys:

    python3 diagnostics/live_x11.py --display :0 --watch-locks 30

This is useful for end-to-end NVDA Remote testing: start the lock watcher, press
Num Lock from Windows NVDA, and compare the before/after XKB state. A successful
Linux state change with no NVDA announcement points to missing remote feedback
rather than failed key injection.

Inspect visible Thunar or Firefox windows:

    python3 diagnostics/live_x11.py --display :0 --target thunar
    python3 diagnostics/live_x11.py --display :0 --target firefox

If more than one matching window is found, choose the reported numeric window
ID explicitly. To activate one Thunar window and exercise a bounded local
Tab/Shift+Tab focus test:

    python3 diagnostics/live_x11.py --display :0 --target thunar --window 12345 --activate --key Tab --key Shift+Tab

The local key mode reuses the production XTest injection path and refuses
arbitrary text input. It is useful for isolating Linux/X11/AT-SPI behavior, but
it does **not** prove that a key traversed Windows NVDA Remote. End-to-end
testing should use the read-only/watch modes while the input comes from Windows.

The driver reports JSON containing XKB state, selected-window metadata, redacted
AT-SPI focus information, step timing, and focus transitions. It never provides
a general text-entry command and does not inspect clipboard, braille input,
speech text, or the Remote Access key.

Optional screenshots are explicit and private because they may contain visible
user content:

    python3 diagnostics/live_x11.py --display :0 --target firefox --window 12345 --screenshot /private/path/debug.png

See [docs/live-x11-diagnostics.md](docs/live-x11-diagnostics.md) for the complete
safety model, supported keys, Num Lock investigation notes, and Xvfb verification
commands.


### Optional Windows NVDA speech probe

For controlled end-to-end tests, an opt-in Windows NVDA diagnostic add-on can
report when NVDA actually queues speech after a Linux action. The probe is
disabled by default, writes nothing to disk, and sends only to Windows loopback.
Use an SSH LocalForward so the data stays inside the existing Remote-SSH
connection.

On Linux, start the receiver:

    python3 diagnostics/nvda_speech_probe.py

To let Codex verify the exact announcement during a controlled test:

    python3 diagnostics/nvda_speech_probe.py --show-text

Install the Windows diagnostic add-on from a Windows checkout or copy of this
repository:

    powershell -ExecutionPolicy Bypass -File .\tools\nvda\install_nvda_speech_probe.ps1

To remove the diagnostic add-on later:

    powershell -ExecutionPolicy Bypass -File .\tools\nvda\install_nvda_speech_probe.ps1 -Uninstall

After installing or uninstalling, restart NVDA. When installed, press
NVDA+Ctrl+Shift+F12 to enable the probe and press it
again immediately after the test to disable it. Exact speech can contain
sensitive information, including typed characters depending on NVDA settings, so
do not leave the probe enabled during ordinary computer use.

See [docs/nvda-speech-probe.md](docs/nvda-speech-probe.md) for the SSH
LocalForward setup, privacy model, and interpretation of results.

## VS Code on Linux

VS Code on Linux is supported through Orca. For reliable screen-reader behavior, run:

    linux-rdaccess vscode-setup

This preserves existing VS Code settings and enables:

    "editor.accessibilitySupport": "on"

It also defaults the Linux title bar to the custom accessible title bar unless you already chose another title-bar style.

If the editor is still silent with Orca, launch VS Code with one of:

    code --force-renderer-accessibility
    ACCESSIBILITY_ENABLED=1 code

`vscode-setup` edits `settings.json` in place (comments and trailing commas are kept) and keeps a one-time `.linux-rdaccess-backup`.

Recommended Windows-NVDA-to-Linux workflow:

    Windows NVDA
        ↓
    NVDA Remote
        ↓
    linux-rdaccess
        ↓
    Orca / AT-SPI
        ↓
    VS Code

Keep VS Code in screen-reader/focus-oriented navigation. Normal VS Code shortcuts are forwarded unchanged, including:

    Ctrl+P           Quick Open
    Ctrl+Shift+P     Command Palette
    Ctrl+G           Go to Line
    Ctrl+Shift+O     Go to Symbol
    Ctrl+Shift+M     Problems
    F8               Next error or warning
    Shift+F8         Previous error or warning
    F7               Next diff
    Shift+F7         Previous diff
    Shift+Alt+F1     Accessibility Help on Linux
    Ctrl+Space       Trigger suggestions

Use the arrow keys in suggestion lists unless VS Code's own accessibility help for the current widget says otherwise (not yet verified over NVDA Remote).

The compatibility layer should not replace VS Code's keyboard model. linux-rdaccess translates only screen-reader-specific gestures and carries Orca speech/braille back to NVDA.

Targeted compatibility areas:

    editor line/word/character navigation
    Explorer tree navigation
    Problems panel
    suggestions/completion lists
    Source Control
    integrated terminal
    diff viewer
    accessibility help/view
    speech interruption
    braille pan/routing/input

## Linux Mint / XFCE compatibility matrix

linux-rdaccess targets reusable accessibility patterns first, then validates them against common Linux Mint/XFCE applications.

Priority applications:

| Priority | Application / area | What must work remotely |
| --- | --- | --- |
| 1 | Thunar File Manager | tree/list navigation, file/folder names, selection, rename, context menus, properties, mounted drives, trash |
| 2 | XFCE panel and application menu | menu navigation, task buttons, tray items, notifications, clock, workspace controls |
| 3 | GTK Open/Save dialogs | location entry, file list, folders, filename field, filters, action buttons |
| 4 | xfce4-terminal | caret/line reading, command editing, selection, tabs, search, scrolling, braille |
| 5 | XFCE Settings Manager | tabs, lists, checkboxes, combo boxes, sliders, spin buttons, dialogs |
| 6 | Update / software tools | package lists, progress, authentication prompts, errors, reboot prompts |
| 7 | Text editor | caret, selection, find/replace, menus, status bar, braille routing |
| 8 | Firefox | browse/focus mode, structural navigation, forms, tables, landmarks |
| 9 | VS Code | editor, Explorer, Problems, Source Control, terminal, suggestions, diffs |

Reusable UI patterns that should be compatible across applications:

    focus traversal
    trees and lists
    tables
    menus and context menus
    dialogs
    tabs
    toolbars
    editable text
    terminal text
    progress bars
    notifications
    file pickers
    authentication prompts
    web/browse content
    Electron applications

Compatibility goals for each target:

    speech output reaches Windows NVDA
    Ctrl/key input interrupts stale speech
    keyboard navigation follows the Linux application's native model
    focused item/state/value changes are announced
    braille output follows focus/caret
    braille pan and routing work remotely
    braille keyboard input is forwarded
    reconnect does not lose the active graphical session

## Thunar / file-manager compatibility test

Thunar is the first Linux Mint/XFCE application target because it exercises several reusable GTK accessibility patterns.

Remote NVDA test sequence:

    1. Open Thunar.
    2. Use Tab / Shift+Tab to move between side pane, file view, location controls, and toolbar.
    3. In the file view, use Up/Down/Left/Right and Home/End.
    4. Press Enter on a folder, then Alt+Left and Alt+Right.
    5. Press F2 to rename a selected item and verify editable-text/caret feedback.
    6. Open the context menu with Shift+F10 and navigate it with arrow keys.
    7. Open Properties and move through tabs, labels, values, and buttons.
    8. Test Ctrl+L location entry.
    9. Test Delete/Trash confirmation dialogs.
    10. Open a GTK Open/Save dialog from an application and test file list, location entry, filename field, filters, and action buttons.

Expected compatibility:

    selected file/folder name is announced
    role/state changes are announced when useful
    focus moves once per navigation command
    Ctrl or another navigation key interrupts stale speech
    braille follows the selected item or text caret
    normal Thunar shortcuts remain unchanged
    menus and dialogs announce the focused item
    rename and location fields expose caret/text changes
    no duplicate announcements from focus + selection events

Problems found here should be fixed in reusable focus/list/tree/dialog handling whenever possible rather than with Thunar-only code.

## Installed command reference

After running:

    python3 linux_rdaccess.py install

you can use these commands from any terminal:

### Configure

Configure Linux as the computer controlled by Windows NVDA and generate a new key:

    linux-rdaccess configure --role host --generate-key

Use the public NVDA Remote relay explicitly:

    linux-rdaccess configure --host nvdaremote.com --port 6837

Configure Linux to control another NVDA Remote-compatible computer:

    linux-rdaccess configure --role client

Keep local Orca speech muted while NVDA speaks Linux output:

    linux-rdaccess configure --local-orca-speech mute

Allow local Orca speech:

    linux-rdaccess configure --local-orca-speech speak

### Connect and disconnect

Apply the saved configuration, update Orca Remote, and restart Orca:

    linux-rdaccess connect

Connect without restarting Orca:

    linux-rdaccess connect --no-restart

If Orca needs to be restarted from SSH, Desktop Commander, or another shell that does not inherit the graphical desktop environment, use:

    ./start-orca-remote.sh

The helper locates the active XFCE session, imports its display, Xauthority, D-Bus, runtime-directory, and session-type variables, and then runs:

    orca --replace

This avoids hard-coding session-specific values in ~/.bashrc. A typical recovery sequence after restarting Windows NVDA Remote Access is:

    linux-rdaccess connect --no-restart
    ./start-orca-remote.sh

Disconnect Orca Remote while keeping the saved configuration:

    linux-rdaccess disconnect

Disconnect without restarting Orca:

    linux-rdaccess disconnect --no-restart

### Status

Show the saved Remote Access configuration without revealing the key:

    linux-rdaccess status

The status also reports whether:

    autostart is enabled
    the linux-rdaccess command is installed
    the Orca Remote configuration file was found

### Autostart

Enable automatic Remote Access startup after graphical login:

    linux-rdaccess autostart enable

Disable automatic startup:

    linux-rdaccess autostart disable

Check whether autostart is enabled:

    linux-rdaccess autostart status

When enabled, the desktop session runs:

    linux-rdaccess connect --quiet

### Shortcuts

Show the common NVDA and Orca Remote keyboard shortcuts:

    linux-rdaccess shortcuts

The main Windows NVDA shortcut is:

    Insert+Alt+Tab

Use it to switch between controlling the local Windows computer and the remote Linux computer.

### Uninstall

Remove the installed command and autostart entry:

    linux-rdaccess uninstall

The saved Remote Access configuration is intentionally preserved so it can be reused after reinstalling.

## Remote Access manager

`linux-rdaccess` now includes a small configuration manager for the NVDA Remote / Orca Remote backend.

Default endpoint:

    Host: nvdaremote.com
    Port: 6837

Create a configuration and generate a channel key:

    python3 remote_access.py configure --generate-key

Show the redacted configuration:

    python3 remote_access.py status

Generate a new key later:

    python3 remote_access.py generate-key --save

Configure Linux as the machine controlled by Windows NVDA:

    python3 remote_access.py configure --role host

Configure Linux to control another NVDA Remote machine:

    python3 remote_access.py configure --role client

Apply the saved endpoint, port, key, and role to a legacy Orca Remote installation such as Orca 42:

    python3 remote_access.py apply-legacy

Show the relevant keyboard commands:

    python3 remote_access.py shortcuts

The channel key is stored in `~/.config/linux-rdaccess/remote.json` with user-only permissions when the platform supports them. Status output never prints the key.

For the normal Windows-to-Linux setup, use role `host`. Windows NVDA can then enter Remote Access control mode with **Insert+Alt+Tab**. Connect, disconnect, and mute are handled by the Orca Remote integration; the manager provides the persistent connection settings and role used by that integration.

## Command reference

### Initial setup

Configure Linux as the machine controlled by Windows NVDA and generate a new Remote Access key:

    python3 remote_access.py configure --role host --generate-key

The default relay and port are:

    nvdaremote.com:6837

Show the saved configuration without revealing the key:

    python3 remote_access.py status

Apply the saved settings to the legacy Orca Remote configuration used by Orca 42:

    python3 remote_access.py apply-legacy

Restart Orca after applying legacy settings:

    orca --replace

### Generate or rotate the Remote Access key

Generate and save a new key:

    python3 remote_access.py generate-key --save

Generate a key and print it once so it can be entered on the Windows NVDA side:

    python3 remote_access.py generate-key --save --show

The key is stored in:

    ~/.config/linux-rdaccess/remote.json

Status commands never print the saved key.

### Change the relay address or port

Use the public NVDA Remote relay:

    python3 remote_access.py configure --host nvdaremote.com --port 6837

Use another relay or a locally hosted NVDA Remote server:

    python3 remote_access.py configure --host 192.168.1.81 --port 6837

Then apply the new settings to legacy Orca Remote:

    python3 remote_access.py apply-legacy

### Choose which computer is controlled

Linux is controlled by Windows NVDA:

    python3 remote_access.py configure --role host

Linux controls another NVDA Remote-compatible computer:

    python3 remote_access.py configure --role client

For the normal `linux-rdaccess` Windows-to-Linux setup, use `host`.

### Speech preference

Keep local Orca speech muted while NVDA speaks Linux output:

    python3 remote_access.py configure --local-orca-speech mute

Allow local Orca speech:

    python3 remote_access.py configure --local-orca-speech speak

### Show Remote Access shortcuts

    python3 remote_access.py shortcuts

Useful shortcuts for the tested legacy Orca Remote setup:

    Windows NVDA:
      Insert+Alt+Tab
        Switch between controlling the local Windows computer and the remote Linux computer.

    Linux Orca Remote:
      Orca+Alt+PageUp or Orca+Alt+C
        Connect.

      Orca+Alt+PageDown or Orca+Alt+D
        Disconnect.

      Orca+Alt+M
        Mute or unmute remote output.

      Orca+Alt+Tab
        Toggle local/remote control when Linux is acting as the client.

      Ctrl+Shift+Orca+C
        Push clipboard text to the remote computer.

### Diagnostic commands

Check the configured Orca Remote endpoint without exposing the Remote Access key:

    python3 nvda_remote_check.py

Machine-readable redacted status:

    python3 nvda_remote_check.py --json

Run the unit tests:

    python3 -m unittest discover -s tests -t .

## Experimental xrdp architecture

The original bridge forwards Linux AT-SPI focus/window events through rdAccess dynamic virtual channels:

- `NVDA-SPEECH` for speech
- `NVDA-BRAILLE` for braille
- `NVDA-A11Y` for richer accessibility-object data

Braille text is translated with Liblouis using `en-ueb-g2.ctb`.

This backend remains useful for research into native RDP accessibility, automatic session handoff, reconnect behavior, and richer remote accessibility objects.

## Requirements

### Recommended NVDA Remote path

On Windows:

- NVDA with Remote Access enabled
- A braille display configured in NVDA if braille is wanted

On Linux:

- Orca
- AT-SPI
- Orca Remote
- Python 3
- Liblouis Python bindings for braille forwarding
- `xdotool` on X11 for remote keyboard injection

### Experimental xrdp path

On Windows:

- NVDA
- the rdAccess add-on
- a braille display configured in NVDA if braille is wanted

On Linux:

- xrdp with `drdynvc=true`
- Python 3
- PyGObject/AT-SPI
- Liblouis Python bindings and `liblouis-data`
- `gdbus`
- `xprop`

## Windows development folders

When developing or testing the xrdp backend on Windows, the repositories are normally kept as sibling folders, for example:

    C:\Users\Miriam\Personal_Coding\rdp\rdAccess
    C:\Users\Miriam\Personal_Coding\rdp\nvda

They have different purposes:

- `rdAccess` is the NVDA add-on used by the xrdp backend. It receives accessibility data sent by `linux-rdaccess` over RDP dynamic virtual channels and turns remote Linux controls into NVDA speech, braille, and remote NVDA objects.
- `nvda` is a checkout of upstream NVDA source. It is a development dependency for `rdAccess` tests and type checking and is useful for checking NVDA focus, speech, TextInfo, and braille APIs.
- The `nvda` checkout is not the installed copy of NVDA and normally should not be modified for `linux-rdaccess` work.

## Run the experimental xrdp backend

After logging in to the xrdp desktop:

    cd ~/linux-rdaccess
    DISPLAY=:10 ./run_braille_bridge.sh --debug

The launcher asks the live session bus for the AT-SPI address, exports it as `AT_SPI_BUS_ADDRESS`, publishes it on the xrdp display, and verifies the result.

Print environment facts without starting the bridge:

    DISPLAY=:10 ./run_braille_bridge.sh --check

For best results, start the launcher immediately after logging in to xrdp, before opening applications that should register with AT-SPI.

## xrdp diagnostics

When Tab does not produce speech or braille:

    DISPLAY=:10 python3 diagnostics/tab_trace.py

- No `Tab #n` line: the key never reached the Linux session.
- `Tab #n -> NO AT-SPI focus event`: Linux received the key but the application reported no focus change.
- `Tab #n -> focus event ...` but nothing from NVDA: run the bridge with `--debug` and inspect the corresponding focus event.

Additional tools:

    DISPLAY=:10 python3 diagnostics/atspi_event_probe.py --all
    DISPLAY=:10 python3 diagnostics/atspi_probe.py

## Known limits

### NVDA Remote / Orca path

- The public NVDA Remote relay may reject older Linux TLS stacks. Hosting the Remote Access session locally on the Windows NVDA machine avoids that dependency.
- Orca versions differ in speech and braille APIs; compatibility shims may be required.
- X11 keyboard injection uses in-process XTest for supported keys and falls back to `xdotool` when required; Wayland requires a different injection backend.
- Braille forwarding requires converting Orca's visible braille line into raw NVDA Remote cell values.

### xrdp path

- An xrdp reconnect can leave a dead DVC on older xrdp versions without a session-notification API. Restart the bridge after reconnecting.
- GTK3 can omit focus events for some controls such as combo boxes.

## Tests

    python3 -m unittest discover -s tests -t .
    python3 -m py_compile *.py diagnostics/*.py tests/*.py
    bash -n run_braille_bridge.sh

## Legacy speech-only xrdp bridge

    DISPLAY=:10 python3 atspi_nvda_bridge.py --debug


### NVDA-style web navigation

When Windows NVDA is controlling Linux through linux-rdaccess, the goal is to
keep NVDA muscle memory while Orca remains the Linux accessibility engine.

Implemented compatibility:

- `NVDA+Space` -> Orca browse/focus-mode toggle.
- `NVDA+F7` -> accessible **Elements List** category chooser, then Orca's
  native structural-navigation list for the selected category.
- Shared quick-navigation keys such as `H`, `K`, `F`, `B`, `E`,
  `X`, `C`, `R`, `L`, `I`, `T`, `G`, and `P` remain native
  so Orca can apply the active browser/application script.

The Elements List currently offers headings, links, form fields, buttons,
edit fields, checkboxes, combo boxes, radio buttons, lists, list items,
tables, landmarks, images, and paragraphs.

Do not globally remap ordinary letters where NVDA and Orca differ.
`linux-rdaccess` currently translates remote `D` / `Shift+D` to Orca's
landmark navigation only when Orca's active script reports structural/browse
navigation is in use. In focus mode, editable controls, browser chrome, and
local Linux input, `D` remains ordinary text. Ctrl/Alt/Orca-modified `D`
is also left untouched. Future differing quick keys should use the same
browse-state-aware approach rather than global printable-key remapping.

`F6` / `Shift+F6` are currently forwarded unchanged. Native Firefox and
Chromium behavior must be verified in a live Linux session before any
translation is considered.
