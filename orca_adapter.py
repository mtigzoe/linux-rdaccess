"""Compatibility entry point for :mod:`linux_rdaccess_core.accessibility.orca_adapter`."""
import sys as _sys
from importlib import import_module as _import_module
_implementation = _import_module('linux_rdaccess_core.accessibility.orca_adapter')

_sys.modules[__name__] = _implementation
