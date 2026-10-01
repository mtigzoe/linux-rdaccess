# linux-rdaccess

Prototype accessibility bridge for using NVDA on Windows with a Linux Mint/XFCE desktop over xrdp.

The bridge forwards Linux AT-SPI focus/window events through rdAccess dynamic virtual channels:

- NVDA-SPEECH for speech
- NVDA-BRAILLE for braille

Braille text is translated with Liblouis using en-ueb-g2.ctb.

## Requirements

On Windows: NVDA, the rdAccess add-on, and a braille display configured in NVDA if braille is wanted.

On Linux: xrdp with drdynvc=true, Python 3, PyGObject/AT-SPI, Liblouis Python bindings and liblouis-data, gdbus, and xprop.

## Run in the xrdp session

After logging in to the xrdp desktop, run:

    cd ~/linux-rdaccess
    DISPLAY=:10 ./run_braille_bridge.sh --debug

The launcher always asks the live session bus for the AT-SPI address (org.a11y.Bus.GetAddress), exports it as AT_SPI_BUS_ADDRESS, sets the AT_SPI_BUS X11 root property on the xrdp display, and reads the property back to confirm it. An AT_SPI_BUS_ADDRESS inherited from an older shell is only used if the live bus cannot be queried, because a stale one aborts the bridge and, once published on the root window, stops newly started applications from registering with AT-SPI.

Print the environment facts (DISPLAY, session bus, AT-SPI address, root property) without starting the bridge:

    DISPLAY=:10 ./run_braille_bridge.sh --check

For best results, start the launcher immediately after logging in to xrdp, before opening applications you want to inspect with AT-SPI.

## When Tab does not produce speech or braille

Run the tracer in the xrdp session, press Tab in a Linux application over the Remote Desktop window, and read which line you get for each press:

    DISPLAY=:10 python3 diagnostics/tab_trace.py

- No `Tab #n` line at all: the key never reached the Linux session (the Windows client kept it).
- `Tab #n -> NO AT-SPI focus event`: Linux received the key but the application reported no focus change. Terminals and text editors consume Tab, and GTK3 combo boxes never report focus gain, so nothing can be announced from this repository.
- `Tab #n -> focus event ...` but nothing from NVDA: run the bridge with `--debug` and check that the same control appears as `object:state-changed:focused -> '...'`.

`diagnostics/atspi_event_probe.py --all` lists every raw AT-SPI event, and `diagnostics/atspi_probe.py` lists the applications registered on the bus.

## Known limits

- An xrdp reconnect while the bridge is running can leave a dead dynamic virtual channel that reports no error. libxrdpapi in xrdp 0.9.17 has no session-notification API, so the bridge cannot detect this; restart it after reconnecting. NVDA restarts and dropped channels are recovered automatically.
- GTK3 emits no focus event when Tab lands on a combo box. Changing its value (arrow keys) is announced; arriving on it is not.

## Tests

    python3 -m unittest discover -s tests -t .
    python3 -m py_compile *.py diagnostics/*.py tests/*.py
    bash -n run_braille_bridge.sh

## Speech-only bridge

The older speech-only bridge remains available:

    DISPLAY=:10 python3 atspi_nvda_bridge.py --debug

DISPLAY=:10 ./run_braille_bridge.sh --debug                                                                             

DISPLAY=:10 ~/linux-rdaccess/run_braille_bridge.sh                                                                      
 DISPLAY=:10
 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
 AT_SPI_BUS_ADDRESS=... (X root AT_SPI_BUS matches)
 WINDOW_MANAGER=present (_NET_SUPPORTING_WM_CHECK)
