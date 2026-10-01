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

The launcher queries the active AT-SPI bus through org.a11y.Bus.GetAddress, exports AT_SPI_BUS_ADDRESS, and sets the AT_SPI_BUS X11 root property on the xrdp display before starting the bridge.

For best results, start the launcher immediately after logging in to xrdp, before opening applications you want to inspect with AT-SPI.

## Tests

    python3 -m unittest discover -s tests -t .
    python3 -m py_compile *.py diagnostics/*.py tests/*.py
    bash -n run_braille_bridge.sh

## Speech-only bridge

The older speech-only bridge remains available:

    DISPLAY=:10 python3 atspi_nvda_bridge.py --debug
