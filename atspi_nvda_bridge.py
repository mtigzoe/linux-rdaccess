"""Compatibility entry point for :mod:`linux_rdaccess_core.accessibility.atspi_nvda_bridge`."""
import sys as _sys
from importlib import import_module as _import_module
_implementation = _import_module('linux_rdaccess_core.accessibility.atspi_nvda_bridge')

if __name__ == "__main__":
    try:
        raise SystemExit(_implementation.main())
    except KeyboardInterrupt:
        raise SystemExit(130)
else:
    _sys.modules[__name__] = _implementation
