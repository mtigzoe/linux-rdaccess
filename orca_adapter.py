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
