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
    label = Gtk.Label(label="Element type:")
    label.set_xalign(0)
    combo = Gtk.ComboBoxText()
    for name, key in ELEMENT_LIST_TYPES:
        combo.append(key, name)
    combo.set_active(0)
    box.pack_start(label, False, False, 6)
    box.pack_start(combo, False, False, 6)
    dialog.show_all()

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

        return getattr(
            orca_state,
            "activeScript",
            getattr(orca_state, "active_script", None),
        )

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
    def where_am_i(cls) -> bool:
        return cls.call_script(
            ("whereAmI", "where_am_i", "presentCurrentObject", "present_current_object"),
            default_event=True,
        )
