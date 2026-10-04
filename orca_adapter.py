#!/usr/bin/env python3
"""Small compatibility adapter around Orca's in-process Python runtime.

The adapter is intentionally narrow: linux-rdaccess asks Orca's active script
to perform screen-reader operations instead of duplicating AT-SPI/application
logic. It supports the camelCase names used by Orca 42 and snake_case aliases
used by newer code when available.
"""

from __future__ import annotations

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
    ) -> bool:
        """Invoke the first supported handler on the active application script."""
        script = cls.active_script()
        if script is None:
            return False
        if isinstance(names, str):
            names = (names,)
        for name in names:
            handler = getattr(script, name, None)
            if not callable(handler):
                continue
            if default_event and not args:
                handler(None)
            else:
                handler(*args)
            return True
        return False

    @classmethod
    def pan_braille_left(cls) -> bool:
        return cls.call_script(
            ("panBrailleLeft", "pan_braille_left"),
            default_event=True,
        )

    @classmethod
    def pan_braille_right(cls) -> bool:
        return cls.call_script(
            ("panBrailleRight", "pan_braille_right"),
            default_event=True,
        )

    @classmethod
    def route_braille(cls, index: int) -> bool:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 1024:
            return False
        event = SimpleNamespace(event={"argument": index})
        return cls.call_script(
            ("processRoutingKey", "process_routing_key"),
            event,
        )

    @classmethod
    def bypass_next_command(cls) -> bool:
        return cls.call_script(
            ("bypassNextCommand", "bypass_next_command"),
            default_event=True,
        )

    @classmethod
    def to_braille_focus(cls) -> bool:
        return cls.call_script(
            ("goBrailleHome", "go_braille_home"),
            default_event=True,
        )

    @classmethod
    def toggle_presentation_mode(cls) -> bool:
        return cls.call_script(
            ("togglePresentationMode", "toggle_presentation_mode"),
            default_event=True,
        )

    @classmethod
    def toggle_structural_navigation(cls) -> bool:
        script = cls.active_script()
        if script is None:
            return False
        nav = getattr(script, "structuralNavigation", None)
        if nav is None:
            nav = getattr(script, "structural_navigation", None)
        if nav is None:
            return False
        handler = getattr(nav, "toggleStructuralNavigation", None)
        if not callable(handler):
            handler = getattr(nav, "toggle_structural_navigation", None)
        if not callable(handler):
            return False
        handler(script, None)
        return True

    @classmethod
    def say_all(cls) -> bool:
        return cls.call_script(
            ("sayAll", "say_all"),
            default_event=True,
        )

    @classmethod
    def present_title(cls) -> bool:
        return cls.call_script(
            ("presentTitle", "present_title"),
            default_event=True,
        )

    @classmethod
    def present_status_bar(cls) -> bool:
        return cls.call_script(
            ("presentStatusBar", "present_status_bar"),
            default_event=True,
        )

    @classmethod
    def where_am_i(cls) -> bool:
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
