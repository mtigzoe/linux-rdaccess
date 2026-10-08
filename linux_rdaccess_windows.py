"""Compatibility entry point for :mod:`linux_rdaccess_core.connection.windows_controller`."""
import sys as _sys
from importlib import import_module as _import_module
_implementation = _import_module('linux_rdaccess_core.connection.windows_controller')

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
else:
    _sys.modules[__name__] = _implementation
