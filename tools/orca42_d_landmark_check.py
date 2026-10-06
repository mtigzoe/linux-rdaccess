#!/usr/bin/env python3
"""Run the patched D -> landmark hook through the REAL Orca 42 key matching.

Not part of the unit suite (needs Orca 42 sources, AT-SPI and a display).
Setup used during development (Ubuntu 24 sandbox, Orca 42 from jammy):

    apt-get download orca=42.0-1ubuntu1 && dpkg-deb -x orca_*.deb orca42
    # Orca 42 imports the removed `imp` module on Python 3.12: put a tiny shim
    # providing load_source()/reload() on PYTHONPATH.
    DISPLAY=:77 ORCA42_PATH=orca42/usr/lib/python3/dist-packages \\
    UPSTREAM_REMOTE_CONTROLLER=remote_controller.py \\
    PYTHONPATH=shim:$ORCA42_PATH dbus-run-session -- sh -c \\
      '/usr/libexec/at-spi-bus-launcher --launch-immediately & sleep 2; \\
       python3 tools/orca42_d_landmark_check.py'

Expected: remote D/Shift+D -> next/previous landmark (and their releases);
focus mode, local D and Ctrl+D untouched; hw_code always restored.
"""
import os, pathlib, shutil, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import remote_access

_tmp = pathlib.Path(tempfile.mkdtemp()) / "remote_controller.py"
sys.path.insert(0, os.path.dirname(os.path.abspath(os.environ["UPSTREAM_REMOTE_CONTROLLER"])))  # upstream siblings
shutil.copy(os.environ["UPSTREAM_REMOTE_CONTROLLER"], _tmp)
remote_access.patch_legacy_orca_remote_controller(_tmp)
import types, importlib.util
import gi
gi.require_version("Gtk","3.0"); gi.require_version("Gdk","3.0"); gi.require_version("Atspi","2.0")
from orca import keybindings, input_event, orca_state, settings
from orca import input_event as ie

# load the real patched upstream controller as a module (Orca-side pieces only)
spec = importlib.util.spec_from_file_location("rc_patched", str(_tmp))
rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)

# real bindings: M = landmark (structural nav), D = live region, like Orca 42
nav_calls = []
landmark_next = input_event.InputEventHandler(lambda s, e=None: nav_calls.append("landmark_next"), "next landmark")
landmark_prev = input_event.InputEventHandler(lambda s, e=None: nav_calls.append("landmark_prev"), "prev landmark")
live = input_event.InputEventHandler(lambda s, e=None: nav_calls.append("live_region"), "live region")
kb = keybindings.KeyBindings()
kb.add(keybindings.KeyBinding("m", keybindings.defaultModifierMask, keybindings.NO_MODIFIER_MASK, landmark_next))
kb.add(keybindings.KeyBinding("m", keybindings.defaultModifierMask, keybindings.SHIFT_MODIFIER_MASK, landmark_prev))
kb.add(keybindings.KeyBinding("d", keybindings.defaultModifierMask, keybindings.NO_MODIFIER_MASK, live))

class Script:
    __module__ = "orca.scripts.web.script"
    keyBindings = kb
    structuralNavigation = types.SimpleNamespace(functions=[landmark_next.function, landmark_prev.function])
    browse = True
    def useStructuralNavigationModel(self): return self.browse
    def consumesKeyboardEvent(self, ev):
        h = self.keyBindings.getInputHandler(ev)
        if h and h.function in self.structuralNavigation.functions:
            return self.useStructuralNavigationModel()
        return h is not None
script = Script()

def make_event(string, hw, mods=0, pressed=True):
    ev = object.__new__(ie.KeyboardEvent)
    ev.timestamp = 1; ev._script = script; ev.is_duplicate = False
    ev.hw_code, ev.modifiers, ev.event_string = hw, mods, string
    ev.id = ord(string); ev.keyval_name = string
    ev._handler = None; ev._consumer = None; ev._is_kp_with_numlock = False
    ev.type = ie.pyatspi.KEY_PRESSED_EVENT if pressed else ie.pyatspi.KEY_RELEASED_EVENT
    ev.getClickCount = lambda: 1
    return ev

orca_state.capturingKeys = False; orca_state.bypassNextCommand = False
orca_state.lastNonModifierKeyEvent = None; orca_state.learnModeEnabled = False
orca_state.listNotificationsModeEnabled = False; orca_state.activeScript = script
ie.KeyboardEvent._getUserHandler = lambda self: None
ie.KeyboardEvent.isModifierKey = lambda self: False
ie.KeyboardEvent.isOrcaModifier = lambda self: False

assert rc._lrd_install_orca_hook(), "Orca keyboard hook did not install"
print("hook installed:", True)

def run(label, string, hw, mods=0, pressed=True, remote=True, browse=True,
        expected_handler=None, expected_consume=False):
    script.browse = browse
    blocked = (keybindings.CTRL_MODIFIER_MASK | keybindings.ALT_MODIFIER_MASK
               | keybindings.ORCA_MODIFIER_MASK)
    if remote and pressed and string in ("d", "D") and not mods & blocked:
        rc._lrd_publish_navigation_marker(rc._LRD_D, "d")
    ev = make_event(string, hw, mods, pressed)
    consume, reason = ev.shouldConsume()
    name = getattr(ev._handler, "description", None)
    assert name == expected_handler, (label, name, expected_handler)
    assert consume == expected_consume, (label, consume, reason)
    assert (ev.hw_code, ev.modifiers) == (hw, mods), label
    print("%-44s consume=%-5s handler=%-14s hw_code restored=%s" % (label, consume, name, ev.hw_code == hw))
    return ev

d_code = keybindings.getKeycode("d")
assert d_code, "D has no keycode in the isolated keyboard map"
run("remote D, browse mode", "d", d_code,
    expected_handler="next landmark", expected_consume=True)
run("  its release", "d", d_code, pressed=False,
    expected_handler="next landmark", expected_consume=True)
run("remote Shift+D, browse mode", "D", d_code, mods=keybindings.SHIFT_MODIFIER_MASK,
    expected_handler="prev landmark", expected_consume=True)
run("  its release", "D", d_code, mods=keybindings.SHIFT_MODIFIER_MASK, pressed=False,
    expected_handler="prev landmark", expected_consume=True)
run("remote D, focus mode / not document", "d", d_code, browse=False,
    expected_handler="live region", expected_consume=True)
run("local D (no remote marker)", "d", d_code, remote=False,
    expected_handler="live region", expected_consume=True)
run("remote Ctrl+D", "d", d_code, mods=keybindings.CTRL_MODIFIER_MASK)
assert not rc._LRD_D["pending"], "Unexpected pending landmark claims"


# --- Orca+Z (single-letter nav toggle) and Orca+BackSpace (pass next key) -----
# Orca matches the modifier state exactly, so the shim releases Shift around
# these; this proves why (Shift still held => no match).
toggle = input_event.InputEventHandler(lambda *a: None, "toggle structural navigation")
bypass = input_event.InputEventHandler(lambda *a: None, "bypass next command")
b2 = keybindings.KeyBindings()
b2.add(keybindings.KeyBinding("z", keybindings.defaultModifierMask, keybindings.ORCA_MODIFIER_MASK, toggle))
b2.add(keybindings.KeyBinding("BackSpace", keybindings.defaultModifierMask, keybindings.ORCA_MODIFIER_MASK, bypass))
for _label, _key, _mods in (
        ("Orca+Z", "z", keybindings.ORCA_MODIFIER_MASK),
        ("Orca+Shift+Z (Shift still held)", "z", keybindings.ORCA_MODIFIER_MASK | keybindings.SHIFT_MODIFIER_MASK),
        ("Orca+BackSpace", "BackSpace", keybindings.ORCA_MODIFIER_MASK)):
    _ev = types.SimpleNamespace(hw_code=keybindings.getKeycode(_key), modifiers=_mods,
                                getClickCount=lambda: 1, isKeyPadKeyWithNumlockOn=lambda: False)
    _h = b2.getInputHandler(_ev)
    print("%-44s -> %s" % (_label, _h.description if _h else None))
