# Diagnostics commands

Run these commands from the `linux-rdaccess` repository root. These scripts
are for troubleshooting and are not necessary for ordinary bridge startup.

## AT-SPI (Linux Mint)

Check whether Python can reach the AT-SPI accessibility bus and list accessible
application entries without showing application names:

```bash
python3 diagnostics/atspi/atspi_probe.py
python3 diagnostics/atspi/atspi_probe.py --limit 5
```

Watch accessibility focus and window events for 12 seconds (default) or a
longer session:

```bash
python3 diagnostics/atspi/atspi_event_probe.py
python3 diagnostics/atspi/atspi_event_probe.py --seconds 30
python3 diagnostics/atspi/atspi_event_probe.py --seconds 30 --all
python3 diagnostics/atspi/atspi_event_probe.py --types object:state-changed:focused window:activate
```

These commands require working Linux `gi` / AT-SPI bindings and an accessible
desktop session. The event probe redacts object labels.

## X11 desktop and keyboard (Linux Mint, X11)

Check the active X11 session and lock-key indicators:

```bash
python3 diagnostics/x11/live_x11.py --display :0
python3 diagnostics/x11/live_x11.py --display :0 --watch-locks 30
```

Inspect Thunar or Firefox focus during live NVDA Remote testing:

```bash
python3 diagnostics/x11/live_x11.py --display :0 --target thunar
python3 diagnostics/x11/live_x11.py --display :0 --target firefox
```

Trace Tab key delivery and correlate it with AT-SPI focus changes. Run this
in the X11 session you are actually testing (`:0` is typical for the local
Mint desktop; `:10` is only an example of an xrdp session):

```bash
DISPLAY=:0 python3 diagnostics/x11/tab_trace.py --seconds 60
```

For advanced options:

```bash
python3 diagnostics/x11/live_x11.py --help
python3 diagnostics/x11/tab_trace.py --help
```

The live X11 diagnostic is designed to redact names in its CLI reports.
Use keyboard-injection or screenshot options only in a controlled test
session.

## NVDA speech probe

With the Windows NVDA speech-probe add-on installed and the configured
connection/SSH forwarding active, run the receiving diagnostic:

```bash
python3 diagnostics/nvda/nvda_speech_probe.py
```

To explicitly include speech text in live output (which may be sensitive):

```bash
python3 diagnostics/nvda/nvda_speech_probe.py --show-text
```

See [NVDA speech probe setup](../docs/nvda-speech-probe.md) for the
Windows installation and connection instructions. The receiver uses
loopback and does not save speech to disk.

## Related developer tools

Other developer utilities are grouped under `tools/diagnostics/`, including
`xkb_lock_state.py` and `summarize_input_trace.py`. See
[tools/README.md](../tools/README.md) for their commands.
