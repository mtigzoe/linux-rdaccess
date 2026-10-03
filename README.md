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

linux-rdaccess additionally translates:

    NVDA+Space
        Toggle Orca browse/focus mode (Orca+A)

This lets Windows NVDA users use the familiar NVDA browse/focus gesture while controlling Firefox on Linux.

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

The compatibility layer is being extended for NVDA review commands, braille panning/routing, braille keyboard input, speech interruption, and other screen-reader-specific gestures.

### Current compatibility work

Implemented or under active testing:

    remote keyboard navigation
    NVDA speech from Linux
    remote braille output
    Ctrl/key speech interruption
    NVDA+Space browse/focus translation
    safe capture of NVDA braille-input gesture metadata

Braille pan, routing keys, and braille keyboard gestures are being mapped from the real NVDA Remote braille_input messages so device-specific assumptions are avoided.

## VS Code on Linux

VS Code on Linux is supported through Orca. For reliable screen-reader behavior, enable:

    "editor.accessibilitySupport": "on"

If the editor is still silent with Orca, launch VS Code with:

    ACCESSIBILITY_ENABLED=1 code

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

VS Code suggestion lists should be navigated with Ctrl+Up and Ctrl+Down when announced by the screen reader.

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
- X11 keyboard injection currently relies on `xdotool`; Wayland requires a different injection backend.
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
