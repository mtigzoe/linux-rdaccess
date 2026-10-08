# Diagnostics

Run these scripts from the repository root.

## AT-SPI probes (Linux)
- `python3 diagnostics/atspi/atspi_probe.py` — inspect accessible objects
- `python3 diagnostics/atspi/atspi_event_probe.py --seconds 30` — capture accessibility events

## X11 and keyboard diagnostics (Linux)
- `python3 diagnostics/x11/live_x11.py --display :0` — inspect the running X11 session
- `DISPLAY=:0 python3 diagnostics/x11/tab_trace.py` — trace focus and Tab behavior

## NVDA speech diagnostic
- `python3 diagnostics/nvda/nvda_speech_probe.py --show-text` — inspect received NVDA speech messages

These diagnostic scripts may require a graphical Linux session, AT-SPI bindings, or a running NVDA Remote/Orca bridge, depending on the command. See the root README for setup. The related developer helpers in `tools/diagnostics/` have separate commands in `tools/README.md`.
