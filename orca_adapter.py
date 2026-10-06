#!/usr/bin/env python3
"""Small compatibility adapter around Orca's in-process Python runtime.

The adapter is intentionally narrow: linux-rdaccess asks Orca's active script
to perform screen-reader operations instead of duplicating AT-SPI/application
logic. It supports the camelCase names used by Orca 42 and snake_case aliases
used by newer code when available.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from types import SimpleNamespace
from typing import Any, Callable, Iterable




ELEMENT_LIST_TYPES = (
    ("Headings", "h"),
    ("Links", "k"),
    ("Form fields", "f"),
    ("Buttons", "b"),
    ("Edit fields", "e"),
    ("Checkboxes", "x"),
    ("Combo boxes", "c"),
    ("Radio buttons", "r"),
    ("Lists", "l"),
    ("List items", "i"),
    ("Tables", "t"),
    ("Landmarks", "m"),
    ("Images", "g"),
    ("Paragraphs", "p"),
)


def show_elements_list(send_structural_list: Callable[[str], Any]) -> bool | None:
    """Show an NVDA-style element-type chooser, then delegate to Orca.

    Orca owns the actual structural-navigation result list. linux-rdaccess only
    provides the familiar NVDA+F7 entry point and category selection.
    """
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception:
        return None

    dialog = Gtk.Dialog(title="Elements List")
    dialog.set_modal(True)
    dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
    dialog.add_button("_Show", Gtk.ResponseType.OK)

    box = dialog.get_content_area()
    combo = Gtk.ComboBoxText()
    for name, key in ELEMENT_LIST_TYPES:
        combo.append(key, name)
    combo.set_active(0)

    label = Gtk.Label(label="_Element type:")
    label.set_use_underline(True)
    label.set_xalign(0)
    label.set_mnemonic_widget(combo)

    box.pack_start(label, False, False, 6)
    box.pack_start(combo, False, False, 6)
    dialog.show_all()
    # Put the screen reader immediately on the category control. The mnemonic
    # relation gives Orca a stable accessible label instead of relying on visual
    # proximity to "Element type".
    combo.grab_focus()

    response = dialog.run()
    key = combo.get_active_id()
    dialog.destroy()
    if response != Gtk.ResponseType.OK or not key:
        # The dialog was shown and the user's Cancel/Escape must be treated as
        # a completed gesture, not as a failure that opens a fallback list.
        return False
    send_structural_list(key)
    return True


class OrcaRuntimeAdapter:
    """Resolve and invoke the active Orca script without owning Orca state."""

    @staticmethod
    def active_script() -> Any | None:
        from orca import orca_state

        script = getattr(orca_state, "activeScript", None)
        if script is not None:
            return script
        return getattr(orca_state, "active_script", None)

    @staticmethod
    def run_on_main(callback: Callable[[], Any]) -> None:
        """Schedule Orca work on GLib's main loop when GI is available."""
        try:
            from gi.repository import GLib
        except Exception:
            callback()
            return

        def invoke() -> bool:
            callback()
            return False

        GLib.idle_add(invoke)

    @classmethod
    def call_script(
        cls,
        names: str | Iterable[str],
        *args: Any,
        default_event: bool = False,
    ) -> bool | None:
        """Invoke one supported handler, or return None when none is available.

        Orca commands may return False after handling a gesture or reporting
        that it cannot act here. Preserve that result so callers do not retry
        the same command through a legacy fallback. A void handler is handled.
        """
        script = cls.active_script()
        if script is None:
            return None
        if isinstance(names, str):
            names = (names,)
        for name in names:
            handler = getattr(script, name, None)
            if not callable(handler):
                continue
            if default_event and not args:
                result = handler(None)
            else:
                result = handler(*args)
            return result is not False
        return None

    @classmethod
    def pan_braille_left(cls) -> bool | None:
        return cls.call_script(
            ("panBrailleLeft", "pan_braille_left"),
            default_event=True,
        )

    @classmethod
    def pan_braille_right(cls) -> bool | None:
        return cls.call_script(
            ("panBrailleRight", "pan_braille_right"),
            default_event=True,
        )

    @classmethod
    def route_braille(cls, index: int) -> bool | None:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 1024:
            return False
        event = SimpleNamespace(event={"argument": index})
        return cls.call_script(
            ("processRoutingKey", "process_routing_key"),
            event,
        )

    @classmethod
    def show_structural_list(cls, key: str, *, script: Any | None = None) -> bool | None:
        """Open Orca's native structural-navigation list for one shortcut key."""
        if script is None:
            script = cls.active_script()
        if script is None:
            return None
        nav = getattr(script, "structuralNavigation", None)
        if nav is None:
            nav = getattr(script, "structural_navigation", None)
        objects = getattr(nav, "enabledObjects", None) if nav is not None else None
        if objects is None and nav is not None:
            objects = getattr(nav, "enabled_objects", None)
        values = objects.values() if isinstance(objects, dict) else ()
        wanted = str(key).lower()
        for obj in values:
            bindings = getattr(obj, "bindings", None)
            list_binding = bindings.get("list") if isinstance(bindings, dict) else None
            if not list_binding or str(list_binding[0]).lower() != wanted:
                continue
            handler = getattr(obj, "showList", None)
            if not callable(handler):
                handler = getattr(obj, "show_list", None)
            if not callable(handler):
                continue
            return handler(script, None) is not False
        return None

    @classmethod
    def cycle_progress_bar_output(cls) -> bool | None:
        """Cycle NVDA-style progress output without changing braille updates."""
        script = cls.active_script()
        if script is None:
            return None
        try:
            from orca import settings_manager
            manager = settings_manager.getManager()
        except Exception:
            return None
        get_setting = getattr(manager, "getSetting", None)
        set_setting = getattr(manager, "setSetting", None)
        if not callable(get_setting) or not callable(set_setting):
            return None
        current = (
            bool(get_setting("speakProgressBarUpdates")),
            bool(get_setting("beepProgressBarUpdates")),
        )
        states = (
            (False, False, "No progress bar updates"),
            (True, False, "Speak progress bar updates"),
            (False, True, "Beep for progress bar updates"),
            (True, True, "Beep and speak progress bar updates"),
        )
        index = next(
            (i for i, (speak, beep, _label) in enumerate(states)
             if (speak, beep) == current),
            len(states) - 1,
        )
        speak, beep, label = states[(index + 1) % len(states)]
        try:
            set_setting("speakProgressBarUpdates", speak)
            set_setting("beepProgressBarUpdates", beep)
            presenter = getattr(script, "presentMessage", None)
            if not callable(presenter):
                presenter = getattr(script, "present_message", None)
            if callable(presenter):
                presenter(label)
            return True
        except Exception:
            return False

    @classmethod
    def toggle_mouse_review(cls) -> bool | None:
        """Toggle Orca mouse review, the native counterpart of NVDA+M."""
        script = cls.active_script()
        if script is None:
            return None
        handlers = getattr(script, "inputEventHandlers", None)
        if handlers is None:
            handlers = getattr(script, "input_event_handlers", None)
        if not isinstance(handlers, dict):
            return None
        handler = handlers.get("toggleMouseReviewHandler")
        if handler is None:
            handler = handlers.get("toggle_mouse_review_handler")
        function = getattr(handler, "function", None)
        if not callable(function):
            return None
        try:
            return function(script, None) is not False
        except Exception:
            return False

    @classmethod
    def toggle_input_help(cls) -> bool | None:
        """Toggle Orca learn mode to match NVDA's NVDA+1 input-help gesture."""
        script = cls.active_script()
        if script is None:
            return None
        try:
            from orca import orca_state
        except Exception:
            return None
        enabled = getattr(orca_state, "learnModeEnabled", None)
        if enabled is None:
            enabled = getattr(orca_state, "learn_mode_enabled", False)
        names = (
            ("exitLearnMode", "exit_learn_mode")
            if bool(enabled)
            else ("enterLearnMode", "enter_learn_mode")
        )
        return cls.call_script(names, default_event=True)

    @classmethod
    def bypass_next_command(cls) -> bool | None:
        return cls.call_script(
            ("bypassNextCommand", "bypass_next_command"),
            default_event=True,
        )

    @classmethod
    def to_braille_focus(cls) -> bool | None:
        return cls.call_script(
            ("goBrailleHome", "go_braille_home"),
            default_event=True,
        )

    @classmethod
    def toggle_presentation_mode(cls) -> bool | None:
        script = cls.active_script()
        if script is None:
            return None
        handler = getattr(script, "togglePresentationMode", None)
        if not callable(handler):
            handler = getattr(script, "toggle_presentation_mode", None)
        if not callable(handler):
            return None

        in_document = getattr(getattr(script, "utilities", None), "inDocumentContent", None)
        if callable(in_document):
            from orca import orca_state
            focus = getattr(orca_state, "locusOfFocus", None)
            if focus is None:
                focus = getattr(orca_state, "locus_of_focus", None)
            if not in_document(focus):
                # Browser scripts retain their document caret while toolbar
                # controls have focus. A mode command here must not grab that
                # cached page object and move focus out of the address bar.
                return False

        # Orca's web script distinguishes an explicit command from an automatic
        # switch by inputEvent truthiness. None can announce focus mode without
        # focusing the caret object, so subsequent arrows/typing reach the old
        # application focus instead of the entry selected in browse mode.
        event = SimpleNamespace(type="keyboard", event_string="space")
        return handler(event) is not False

    @classmethod
    def toggle_structural_navigation(cls) -> bool | None:
        script = cls.active_script()
        if script is None:
            return None
        nav = getattr(script, "structuralNavigation", None)
        if nav is None:
            nav = getattr(script, "structural_navigation", None)
        if nav is None:
            return None
        handler = getattr(nav, "toggleStructuralNavigation", None)
        if not callable(handler):
            handler = getattr(nav, "toggle_structural_navigation", None)
        if not callable(handler):
            return None
        return handler(script, None) is not False

    @classmethod
    def show_preferences(cls) -> bool | None:
        """Open Orca's global preferences dialog using Orca's own command."""
        try:
            from orca import orca as orca_module
        except Exception:
            return None
        handler = getattr(orca_module, "showPreferencesGUI", None)
        if not callable(handler):
            handler = getattr(orca_module, "show_preferences_gui", None)
        if not callable(handler):
            return None
        result = handler(cls.active_script(), None)
        return result is not False

    @classmethod
    def say_all(cls) -> bool | None:
        return cls.call_script(
            ("sayAll", "say_all"),
            default_event=True,
        )

    @classmethod
    def present_title(cls) -> bool | None:
        return cls.call_script(
            ("presentTitle", "present_title"),
            default_event=True,
        )

    @classmethod
    def present_status_bar(cls) -> bool | None:
        return cls.call_script(
            ("presentStatusBar", "present_status_bar"),
            default_event=True,
        )

    @classmethod
    def present_time(cls) -> bool | None:
        """Present the time using Orca's configured format and output."""
        return cls.call_script("presentTime", default_event=True)

    @classmethod
    def present_date(cls) -> bool | None:
        """Present the date using Orca's configured format and output."""
        return cls.call_script("presentDate", default_event=True)

    @classmethod
    def present_current_line(cls) -> bool | None:
        """Speak the native caret line without entering or moving flat review."""
        script = cls.active_script()
        if script is None:
            return None
        handler = getattr(script, "sayLine", None)
        if not callable(handler):
            return None

        from orca import orca_state
        focus = getattr(orca_state, "locusOfFocus", None)
        if focus is None:
            focus = getattr(orca_state, "locus_of_focus", None)

        # Web scripts can keep a browse caret separate from locusOfFocus, even
        # while Firefox's address bar is focused. Consult it only when focus
        # belongs to document content; otherwise report the focused control.
        obj = focus
        utilities = getattr(script, "utilities", None)
        get_context = getattr(utilities, "getCaretContext", None)
        in_document = getattr(utilities, "inDocumentContent", None)
        document_focus = bool(in_document(focus)) if callable(in_document) else None
        browse_focus = document_focus is True and not bool(
            getattr(script, "_inFocusMode", False))
        if callable(get_context) and (
            document_focus is None or browse_focus
        ):
            caret_obj, _offset = get_context()
            if caret_obj is not None:
                obj = caret_obj
        if obj is None:
            return False

        # Orca 42's web sayLine chooses its virtual or physical caret branch
        # using the previous command's navigation flags. This explicit report
        # must reflect current browse/focus context, including after a toolbar
        # focus change which leaves those flags stale. Preserve native handler
        # overrides and restore the original flags even if presentation fails.
        flag_names = ("_lastCommandWasCaretNav", "_lastCommandWasStructNav")
        saved_flags = {
            name: getattr(script, name) for name in flag_names if hasattr(script, name)
        }
        adjust_flags = document_focus is not None and len(saved_flags) == len(flag_names)
        try:
            if adjust_flags:
                script._lastCommandWasCaretNav = False
                script._lastCommandWasStructNav = browse_focus
            return handler(obj) is not False
        finally:
            if adjust_flags:
                for name, value in saved_flags.items():
                    setattr(script, name, value)

    @staticmethod
    def _xkb_named_lock_state(name: str) -> bool | None:
        """Read an authoritative named XKB indicator from the active X11 display."""
        try:
            x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XInternAtom.restype = ctypes.c_ulong
            x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            x11.XkbGetNamedIndicator.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
            ]
            x11.XkbGetNamedIndicator.restype = ctypes.c_int
            display = x11.XOpenDisplay(None)
            if not display:
                return None
            try:
                atom = x11.XInternAtom(display, name.encode("ascii"), 1)
                if not atom:
                    return None
                index, on, real = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
                if not x11.XkbGetNamedIndicator(
                    display, atom, ctypes.byref(index), ctypes.byref(on), None,
                    ctypes.byref(real)
                ):
                    return None
                return bool(on.value)
            finally:
                x11.XCloseDisplay(display)
        except Exception:
            return None

    @classmethod
    def read_lock_state(cls, vk_code: int) -> bool | None:
        """Snapshot an XKB lock using a private Xlib display and no Orca API."""
        name = {0x14: "Caps Lock", 0x90: "Num Lock"}.get(vk_code)
        return cls._xkb_named_lock_state(name) if name is not None else None

    @classmethod
    def present_lock_state(cls, vk_code: int, enabled: bool | None = None) -> bool | None:
        """Present a completed gesture's snapshot through Orca speech/braille."""
        name = {0x14: "Caps Lock", 0x90: "Num Lock"}.get(vk_code)
        if name is None:
            return False
        if enabled is None:
            enabled = cls.read_lock_state(vk_code)
        if type(enabled) is not bool:
            return False
        return cls.call_script(
            ("presentMessage", "present_message"),
            f"{name} {'on' if enabled else 'off'}",
        )

    @classmethod
    def where_am_i(cls) -> bool | None:
        # Orca 42's default script exposes whereAmIBasic(inputEvent), not
        # whereAmI. Keep older/newer aliases as fallbacks.
        return cls.call_script(
            (
                "whereAmIBasic",
                "where_am_i_basic",
                "whereAmI",
                "where_am_i",
                "presentCurrentObject",
                "present_current_object",
            ),
            default_event=True,
        )
