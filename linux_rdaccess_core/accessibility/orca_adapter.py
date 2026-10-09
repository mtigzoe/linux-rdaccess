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




def _a11y_model():
    """Use the package model, or its standalone copy in Orca's scripts directory."""
    if __package__:
        from . import a11y_model
    else:
        import linux_rdaccess_a11y_model as a11y_model
    return a11y_model


ELEMENT_LIST_TYPES = (
    ("Links", "k"),
    ("Headings", "h"),
    ("Form fields", "f"),
    ("Buttons", "b"),
    ("Landmarks", "m"),
)

_ELEMENT_LIST_LAST_INDEX = 0
_REMOTE_BRAILLE_DISPLAY = None
_REMOTE_SEMANTIC_OBJECTS: dict[str, object] = {}
_REMOTE_SEMANTIC_FOCUS_ID: str | None = None
_REMOTE_SEMANTIC_CONTEXT: object | None = None


def show_elements_list(send_structural_list: Callable[[str], Any]) -> bool | None:
    """Show an NVDA-style element-type chooser, then delegate to Orca.

    Orca owns the actual structural-navigation result list. linux-rdaccess only
    provides the familiar NVDA+F7 entry point and category selection.
    """
    global _ELEMENT_LIST_LAST_INDEX
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
    combo.set_active(_ELEMENT_LIST_LAST_INDEX)

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
    if key:
        try:
            _ELEMENT_LIST_LAST_INDEX = next(
                index for index, (_name, item_key) in enumerate(ELEMENT_LIST_TYPES)
                if item_key == key
            )
        except StopIteration:
            pass
    dialog.destroy()
    if response != Gtk.ResponseType.OK or not key:
        # The dialog was shown and the user's Cancel/Escape must be treated as
        # a completed gesture, not as a failure that opens a fallback list.
        return False
    send_structural_list(key)
    return True


def _show_guarded_structural_list(
    handler: Callable[..., Any], script: Any,
    lifetime_valid: Callable[[], bool] | None,
) -> Any:
    """Keep Orca 42's native list, guarding its later target callbacks.

    Orca stores the result accessibles and originating document in its GTK
    list. Reloading Firefox while that dialog is open destroys those objects;
    Orca 42's Jump/Activate callbacks otherwise still use the stored objects.
    The temporary showUI wrapper only applies to lists opened by this bridge.
    """
    try:
        from orca import orca_gui_navlist, orca_state
    except ImportError:
        return handler(script, None)
    native_class = getattr(orca_gui_navlist, "OrcaNavListGUI", None)
    native_show = getattr(orca_gui_navlist, "showUI", None)
    if not isinstance(native_class, type) or not callable(native_show):
        return handler(script, None)

    window = getattr(orca_state, "activeWindow", None)
    if window is None:
        window = getattr(orca_state, "active_window", None)

    class RemoteNavListGUI(native_class):
        def _target_is_current(self) -> bool:
            try:
                if lifetime_valid is not None and not lifetime_valid():
                    return False
                if self._script is not script or self._document is None:
                    return False
                utilities = script.utilities
                active_document = getattr(utilities, "activeDocument", None)
                if not callable(active_document):
                    active_document = getattr(utilities, "active_document", None)
                if (not callable(active_document) or window is None
                        or active_document(window) != self._document):
                    return False
                obj, _offset = self._getSelectedAccessibleAndOffset()
                if obj is None:
                    return False
                for name, alias in (("isDead", "is_dead"), ("isZombie", "is_zombie")):
                    check = getattr(utilities, name, None)
                    if not callable(check):
                        check = getattr(utilities, alias, None)
                    if callable(check) and (check(self._document) or check(obj)):
                        return False
                get_document = getattr(utilities, "getTopLevelDocumentForObject", None)
                if not callable(get_document):
                    get_document = getattr(utilities, "get_top_level_document_for_object", None)
                return callable(get_document) and get_document(obj) == self._document
            except Exception:
                # A disappearing AT-SPI object can raise even before isDead.
                return False

        def _onJumpToClicked(self, widget):
            if not self._target_is_current():
                self._gui.destroy()
                return
            return super()._onJumpToClicked(widget)

        def _onActivateClicked(self, widget):
            if not self._target_is_current():
                self._gui.destroy()
                return
            return super()._onActivateClicked(widget)

    def show_guarded(*args, **kwargs):
        gui = RemoteNavListGUI(*args, **kwargs)
        gui.showGUI()

    orca_gui_navlist.showUI = show_guarded
    try:
        return handler(script, None)
    finally:
        if orca_gui_navlist.showUI is show_guarded:
            orca_gui_navlist.showUI = native_show


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

    @staticmethod
    def set_remote_braille_width(width: int, owner: Any) -> bool:
        """Size Orca 42's native viewport for a remote display on the main loop."""
        global _REMOTE_BRAILLE_DISPLAY
        if type(width) is not int or not 0 <= width <= 1024:
            return False
        if width == 0:
            return OrcaRuntimeAdapter.restore_remote_braille_width(owner)
        from orca import braille

        size = getattr(braille, "_displaySize", None)
        if (not isinstance(size, list) or len(size) != 2
                or type(size[0]) is not int or size[0] <= 0):
            return False
        previous = _REMOTE_BRAILLE_DISPLAY
        original = (previous["original"]
                    if (previous is not None and previous["module"] is braille
                        and previous["size"] is size and size[0] == previous["width"])
                    else size[0])
        request = {
            "owner": owner, "module": braille, "size": size,
            "original": original, "width": width,
        }
        _REMOTE_BRAILLE_DISPLAY = request
        if size[0] != width:
            old_width = size[0]
            size[0] = width
            try:
                braille.refresh(True)
            except Exception:
                # Preserve a usable geometry and its original-width owner if
                # the current accessibility object disappears during refresh.
                if _REMOTE_BRAILLE_DISPLAY is request:
                    _REMOTE_BRAILLE_DISPLAY = previous
                    if getattr(braille, "_displaySize", None) is size and size[0] == width:
                        size[0] = old_width
                raise
        return True

    @staticmethod
    def restore_remote_braille_width(owner: Any) -> bool:
        """Release only this session's override, including delayed cleanup."""
        global _REMOTE_BRAILLE_DISPLAY
        previous = _REMOTE_BRAILLE_DISPLAY
        if previous is None or previous["owner"] is not owner:
            return True
        _REMOTE_BRAILLE_DISPLAY = None
        braille = previous["module"]
        size = getattr(braille, "_displaySize", None)
        # A local BrlAPI display can reconnect independently and replace its
        # width. Preserve that change rather than restoring an obsolete size.
        if (size is previous["size"] and isinstance(size, list) and len(size) == 2
                and size[0] == previous["width"] and size[0] != previous["original"]):
            size[0] = previous["original"]
            braille.refresh(True)
        return True

    @staticmethod
    def semantic_focus_payload() -> dict[str, Any] | None:
        """Build a bounded AT-SPI focus snapshot for NVDA-native braille."""
        global _REMOTE_SEMANTIC_OBJECTS, _REMOTE_SEMANTIC_FOCUS_ID, _REMOTE_SEMANTIC_CONTEXT
        # Re-entrant actions cannot use the old registry while rebuilding.
        # Retain the receipt context until publication so the network thread
        # can queue commands during a same-focus refresh. Failed builds clear
        # both fields; commands execute only later on this main loop.
        _REMOTE_SEMANTIC_OBJECTS = {}
        try:
            from orca import orca_state
            build_focus_payload = _a11y_model().build_focus_payload
        except Exception:
            OrcaRuntimeAdapter.clear_semantic_focus()
            return None

        focus = getattr(orca_state, "locusOfFocus", None)
        if focus is None:
            focus = getattr(orca_state, "locus_of_focus", None)
        if focus is None:
            OrcaRuntimeAdapter.clear_semantic_focus()
            return None
        registry: dict[str, object] = {}
        try:
            payload = build_focus_payload(
                "object:state-changed:focused",
                1,
                focus,
                max_objects=32,
                object_registry=registry,
            )
        except Exception:
            OrcaRuntimeAdapter.clear_semantic_focus()
            return None
        if payload is not None:
            try:
                import json
                encoded = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            except Exception:
                OrcaRuntimeAdapter.clear_semantic_focus()
                return None
            # Leave headroom for the Remote Access type/version envelope.
            if len(encoded) > 60 * 1024:
                OrcaRuntimeAdapter.clear_semantic_focus()
                return None
            if _REMOTE_SEMANTIC_FOCUS_ID != payload["focus_id"] or _REMOTE_SEMANTIC_CONTEXT is None:
                _REMOTE_SEMANTIC_CONTEXT = object()
            _REMOTE_SEMANTIC_OBJECTS = registry
            _REMOTE_SEMANTIC_FOCUS_ID = payload["focus_id"]
        else:
            OrcaRuntimeAdapter.clear_semantic_focus()
        return payload

    @staticmethod
    def clear_semantic_focus() -> None:
        global _REMOTE_SEMANTIC_OBJECTS, _REMOTE_SEMANTIC_FOCUS_ID, _REMOTE_SEMANTIC_CONTEXT
        _REMOTE_SEMANTIC_OBJECTS = {}
        _REMOTE_SEMANTIC_FOCUS_ID = None
        _REMOTE_SEMANTIC_CONTEXT = None

    @staticmethod
    def semantic_focus_context() -> object | None:
        """Read an opaque focus lifetime without querying Orca/AT-SPI."""
        return _REMOTE_SEMANTIC_CONTEXT

    @staticmethod
    def _semantic_target(object_id: str, expected_context: object | None):
        """Validate snapshot and live focus on Orca's main loop before acting."""
        if (_REMOTE_SEMANTIC_FOCUS_ID is None
                or (expected_context is not None
                    and expected_context is not _REMOTE_SEMANTIC_CONTEXT)):
            return None
        try:
            from orca import orca_state
            focus = getattr(orca_state, "locusOfFocus", None)
            if focus is None:
                focus = getattr(orca_state, "locus_of_focus", None)
            if focus is not None and _a11y_model().object_id(focus) == _REMOTE_SEMANTIC_FOCUS_ID:
                return _REMOTE_SEMANTIC_OBJECTS.get(object_id)
        except Exception:
            pass
        OrcaRuntimeAdapter.clear_semantic_focus()
        return None

    @staticmethod
    def perform_semantic_action(object_id: str, action_index: int, *,
                                expected_context: object | None = None) -> bool:
        if not isinstance(object_id, str) or not object_id or len(object_id) > 256:
            return False
        if type(action_index) is not int or not 0 <= action_index < 32:
            return False
        obj = OrcaRuntimeAdapter._semantic_target(object_id, expected_context)
        if obj is None:
            return False
        try:
            perform_action = _a11y_model().perform_action
            return bool(perform_action(obj, action_index))
        except Exception:
            return False


    @staticmethod
    def set_semantic_caret(object_id: str, offset: int, *,
                           expected_context: object | None = None) -> bool:
        """Route NVDA's semantic text position back to the current AT-SPI object."""
        if not isinstance(object_id, str) or not object_id or len(object_id) > 256:
            return False
        if type(offset) is not int or not 0 <= offset <= 8192:
            return False
        obj = OrcaRuntimeAdapter._semantic_target(object_id, expected_context)
        if obj is None:
            return False
        try:
            set_caret_offset = _a11y_model().set_caret_offset
            return bool(set_caret_offset(obj, offset))
        except Exception:
            return False

    @staticmethod
    def braille_cells(*, get_link_mask: bool = True) -> list[int]:
        """Serialize Orca 42's native cells without translating them again.

        Region.string is already contracted when contraction is enabled, and
        Orca's routing maps refer to positions in that string. charToDots only
        converts its display characters to dot patterns; it preserves both
        those positions and cursor-expanded words.
        """
        from orca import braille
        import louis

        width = braille._displaySize[0]
        if type(width) is not int or not 0 < width <= 1024:
            raise ValueError("invalid Orca braille display width")
        line = braille.getShowingLine()
        if line is None:
            return [0] * width
        start = braille.viewport[0]
        end = start + width
        # refresh() has already set viewport[0] to the wrapped range's start.
        # Preserve its shorter end so padding does not reveal the next word.
        wrap = getattr(braille, "_adjustForWordWrap", None)
        if callable(wrap):
            wrapped_start, wrapped_end = wrap(0)
            if wrapped_start == start:
                end = min(end, wrapped_end)
        _, _, attributes, _ = line.getLineInfo(get_link_mask)
        cells = []
        offset = 0
        for region in line.regions:
            string = region.string
            region_end = offset + len(string)
            visible = string[max(0, start - offset):max(0, end - offset)]
            if visible:
                table = (region.contractionTable if region.contracted
                         else "en-us-comp8.ctb")
                dots = louis.charToDots([table], visible, mode=louis.ucBrl)
                if (len(dots) != len(visible)
                        or any(not 0x2800 <= ord(dot) <= 0x28ff for dot in dots)):
                    raise ValueError("braille display conversion changed cell positions")
                cells.extend(
                    ord(ch) - 0x2800 if 0x2800 <= ord(ch) <= 0x28ff
                    else ord(dot) - 0x2800
                    for ch, dot in zip(visible, dots))
            offset = region_end
            if offset >= end:
                break
        cells += [0] * (width - len(cells))
        if attributes:
            for index, attribute in enumerate(attributes[start:end]):
                cells[index] |= ord(attribute)
        cursor = getattr(braille, "cursorCell", 0)
        if type(cursor) is int and 1 <= cursor <= width:
            cells[cursor - 1] |= 0xc0
        return cells

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
    def show_structural_list(
        cls, key: str, *, script: Any | None = None,
        lifetime_valid: Callable[[], bool] | None = None,
    ) -> bool | None:
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
            return _show_guarded_structural_list(handler, script, lifetime_valid) is not False
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

        utilities = getattr(script, "utilities", None)
        in_document = getattr(utilities, "inDocumentContent", None)
        if not callable(in_document):
            in_document = getattr(utilities, "in_document_content", None)
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
    def present_focus_accelerator(cls) -> bool | None:
        """Report focused-object shortcuts using Orca's speech/braille presenter.

        NVDA's command reports focus, even when its review position differs.
        Orca's utility returns localized mnemonic, full menu path and direct
        accelerator strings. Prefer the direct accelerator, then the mnemonic,
        then the full path so this remains a single NVDA-like shortcut report.
        This operation does not enter flat review or detailed Where Am I.
        """
        script = cls.active_script()
        if script is None:
            return None
        utilities = getattr(script, "utilities", None)
        get_keys = getattr(utilities, "mnemonicShortcutAccelerator", None)
        if not callable(get_keys):
            get_keys = getattr(utilities, "mnemonic_shortcut_accelerator", None)
        present = getattr(script, "presentMessage", None)
        if not callable(present):
            present = getattr(script, "present_message", None)
        if not callable(get_keys) or not callable(present):
            return None
        try:
            from orca import orca_state
            focus = getattr(orca_state, "locusOfFocus", None)
            if focus is None:
                focus = getattr(orca_state, "locus_of_focus", None)
            if focus is None:
                return False
            keys = get_keys(focus)
            if not isinstance(keys, (tuple, list)) or len(keys) != 3 \
                    or not all(isinstance(key, str) for key in keys):
                return False
            mnemonic, shortcut, accelerator = keys
            key = accelerator or mnemonic or shortcut
            return present(key if key else "No shortcut key") is not False
        except Exception:
            # A presenter can speak before raising. Do not permit a fallback
            # which retries that partial operation or persists application text.
            return False

    @classmethod
    def present_time(cls) -> bool | None:
        """Present the time using Orca's configured format and output."""
        return cls.call_script(
            ("presentTime", "present_time"),
            default_event=True,
        )

    @classmethod
    def present_date(cls) -> bool | None:
        """Present the date using Orca's configured format and output."""
        return cls.call_script(
            ("presentDate", "present_date"),
            default_event=True,
        )

    @classmethod
    def present_current_line(cls) -> bool | None:
        """Speak the native caret line without entering or moving flat review."""
        script = cls.active_script()
        if script is None:
            return None
        handler = getattr(script, "sayLine", None)
        if not callable(handler):
            handler = getattr(script, "say_line", None)
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
        if not callable(get_context):
            get_context = getattr(utilities, "get_caret_context", None)
        in_document = getattr(utilities, "inDocumentContent", None)
        if not callable(in_document):
            in_document = getattr(utilities, "in_document_content", None)
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
        name = {0x14: "Caps Lock", 0x90: "Num Lock", 0x91: "Scroll Lock"}.get(vk_code)
        return cls._xkb_named_lock_state(name) if name is not None else None

    @classmethod
    def present_lock_state(cls, vk_code: int, enabled: bool | None = None) -> bool | None:
        """Present a completed gesture's snapshot through Orca speech/braille."""
        name = {0x14: "Caps Lock", 0x90: "Num Lock", 0x91: "Scroll Lock"}.get(vk_code)
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
