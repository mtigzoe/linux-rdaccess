"""Import the braille bridge against stub gi/Atspi/GLib/louis modules.

The real typelibs and liblouis are not needed (and not used, even where
installed), so bridge logic can be unit tested anywhere.  The imported module is
kept out of sys.modules afterwards so tests that need the real libraries are not
affected.
"""

import importlib
import sys
import types
from unittest import mock


class GLibError(Exception):
    pass


class _Listener:
    def __init__(self, callback):
        self.callback = callback

    def register(self, event_type):
        return True

    def deregister(self, event_type):
        return True


def _stub_modules():
    atspi = types.SimpleNamespace(
        StateType=types.SimpleNamespace(FOCUSED="focused"),
        CoordType=types.SimpleNamespace(SCREEN=0),
        EventListener=types.SimpleNamespace(new=lambda callback: _Listener(callback)),
        get_desktop=lambda index: object(),
        Accessible=object,
        Event=object,
    )
    glib = types.SimpleNamespace(
        Error=GLibError,
        MainLoop=object,
        SOURCE_CONTINUE=True,
        SOURCE_REMOVE=False,
        PRIORITY_HIGH=0,
        unix_signal_add=lambda *args: 0,
        timeout_add=lambda *args: 0,
    )
    gi = types.ModuleType("gi")
    gi.require_version = lambda name, version: None
    repository = types.ModuleType("gi.repository")
    repository.Atspi, repository.GLib = atspi, glib
    gi.repository = repository
    louis = types.ModuleType("louis")
    louis.dotsIO = 1
    louis.translateString = lambda tables, text, mode=0: "".join(
        chr(0x2800 + (ord(c) & 0x3F)) for c in text
    )
    return {"gi": gi, "gi.repository": repository, "louis": louis}


def import_braille_bridge():
    with mock.patch.dict(sys.modules, _stub_modules()):
        sys.modules.pop("atspi_nvda_braille_bridge", None)
        sys.modules.pop("linux_rdaccess_core.accessibility.atspi_nvda_braille_bridge", None)
        return importlib.import_module("atspi_nvda_braille_bridge")
