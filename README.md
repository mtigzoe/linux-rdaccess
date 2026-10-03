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
