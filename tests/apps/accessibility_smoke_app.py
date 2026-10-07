#!/usr/bin/env python3
"""Deterministic GTK3 control gallery for linux-rdaccess live compatibility checks.

CI can inspect the declared control matrix without GTK installed:

    python tests/apps/accessibility_smoke_app.py --list-controls

Launch the real UI inside the Linux desktop for AT-SPI/NVDA acceptance testing:

    python tests/apps/accessibility_smoke_app.py
"""

from __future__ import annotations

import json
import sys


CONTROL_SPECS = (
    {"id": "primary-button", "label": "Apply changes", "pattern": "button", "expected_role": "push button"},
    {"id": "feature-checkbox", "label": "Enable notifications", "pattern": "checkbox", "expected_role": "check box"},
    {"id": "choice-radio", "label": "Choice alpha", "pattern": "radio", "expected_role": "radio button"},
    {"id": "mode-combo", "label": "Display mode", "pattern": "combobox", "expected_role": "combo box"},
    {"id": "volume-slider", "label": "Volume", "pattern": "slider", "expected_role": "slider"},
    {"id": "single-entry", "label": "Account name", "pattern": "entry", "expected_role": "entry"},
    {"id": "multiline-editor", "label": "Notes", "pattern": "multiline-text", "expected_role": "text"},
    {"id": "items-list", "label": "Files", "pattern": "list-tree", "expected_role": "tree table"},
    {"id": "settings-tabs", "label": "Settings pages", "pattern": "tabs", "expected_role": "page tab list"},
    {"id": "file-menu", "label": "File", "pattern": "menu", "expected_role": "menu"},
    {"id": "progress", "label": "Update progress", "pattern": "progress", "expected_role": "progress bar"},
    {"id": "calendar", "label": "Test calendar", "pattern": "calendar", "expected_role": "calendar"},
    {"id": "dialog-button", "label": "Open test dialog", "pattern": "dialog", "expected_role": "push button"},
    {"id": "status", "label": "Ready", "pattern": "status", "expected_role": "label"},
)


def _set_accessible(widget, name: str, description: str = "") -> None:
    accessible = widget.get_accessible()
    accessible.set_name(name)
    if description:
        accessible.set_description(description)


def build_window(app):
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    window = Gtk.ApplicationWindow(application=app)
    window.set_title("linux-rdaccess accessibility smoke test")
    window.set_default_size(760, 720)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    outer.set_border_width(12)
    window.add(outer)

    menubar = Gtk.MenuBar()
    file_item = Gtk.MenuItem.new_with_mnemonic("_File")
    file_menu = Gtk.Menu()
    close_item = Gtk.MenuItem.new_with_mnemonic("_Close")
    close_item.connect("activate", lambda *_: window.close())
    file_menu.append(close_item)
    file_item.set_submenu(file_menu)
    menubar.append(file_item)
    _set_accessible(file_item, "File", "Application menu")
    outer.pack_start(menubar, False, False, 0)

    heading = Gtk.Label()
    heading.set_markup("<b>linux-rdaccess control-pattern smoke test</b>")
    heading.set_xalign(0)
    outer.pack_start(heading, False, False, 0)

    grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    outer.pack_start(grid, False, False, 0)

    button = Gtk.Button.new_with_label("Apply changes")
    _set_accessible(button, "Apply changes", "Commits the sample settings")
    grid.attach(button, 0, 0, 1, 1)

    checkbox = Gtk.CheckButton.new_with_label("Enable notifications")
    checkbox.set_active(True)
    _set_accessible(checkbox, "Enable notifications")
    grid.attach(checkbox, 1, 0, 1, 1)

    radio_a = Gtk.RadioButton.new_with_label_from_widget(None, "Choice alpha")
    radio_b = Gtk.RadioButton.new_with_label_from_widget(radio_a, "Choice bravo")
    radio_a.set_active(True)
    _set_accessible(radio_a, "Choice alpha")
    _set_accessible(radio_b, "Choice bravo")
    grid.attach(radio_a, 0, 1, 1, 1)
    grid.attach(radio_b, 1, 1, 1, 1)

    combo_label = Gtk.Label(label="Display mode")
    combo_label.set_xalign(0)
    combo = Gtk.ComboBoxText()
    for item in ("Automatic", "Light", "Dark"):
        combo.append_text(item)
    combo.set_active(0)
    _set_accessible(combo, "Display mode", "Choose a sample display mode")
    grid.attach(combo_label, 0, 2, 1, 1)
    grid.attach(combo, 1, 2, 1, 1)

    slider_label = Gtk.Label(label="Volume")
    slider_label.set_xalign(0)
    slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
    slider.set_value(65)
    slider.set_value_pos(Gtk.PositionType.RIGHT)
    _set_accessible(slider, "Volume", "Sample percentage slider")
    grid.attach(slider_label, 0, 3, 1, 1)
    grid.attach(slider, 1, 3, 1, 1)

    entry_label = Gtk.Label(label="Account name")
    entry_label.set_xalign(0)
    entry = Gtk.Entry()
    entry.set_text("sample-user")
    _set_accessible(entry, "Account name", "Single-line editable text")
    grid.attach(entry_label, 0, 4, 1, 1)
    grid.attach(entry, 1, 4, 1, 1)

    notebook = Gtk.Notebook()
    _set_accessible(notebook, "Settings pages")
    outer.pack_start(notebook, True, True, 0)

    notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    notes_label = Gtk.Label(label="Notes")
    notes_label.set_xalign(0)
    notes_box.pack_start(notes_label, False, False, 0)
    notes_scroll = Gtk.ScrolledWindow()
    notes_scroll.set_min_content_height(100)
    notes = Gtk.TextView()
    notes.get_buffer().set_text("Line one.\nLine two.\nLine three.")
    _set_accessible(notes, "Notes", "Multiline editable text")
    notes_scroll.add(notes)
    notes_box.pack_start(notes_scroll, True, True, 0)
    notebook.append_page(notes_box, Gtk.Label(label="Editor"))

    list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    store = Gtk.ListStore(str, str)
    for row in (("Document.txt", "Text"), ("Pictures", "Folder"), ("Report.pdf", "PDF")):
        store.append(row)
    tree = Gtk.TreeView(model=store)
    for index, title in enumerate(("Name", "Type")):
        renderer = Gtk.CellRendererText()
        tree.append_column(Gtk.TreeViewColumn(title, renderer, text=index))
    tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
    _set_accessible(tree, "Files", "Sample file list")
    tree_scroll = Gtk.ScrolledWindow()
    tree_scroll.set_min_content_height(110)
    tree_scroll.add(tree)
    list_box.pack_start(tree_scroll, True, True, 0)
    notebook.append_page(list_box, Gtk.Label(label="List"))

    lower = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    outer.pack_start(lower, False, False, 0)

    progress = Gtk.ProgressBar()
    progress.set_fraction(0.42)
    progress.set_show_text(True)
    progress.set_text("42 percent")
    _set_accessible(progress, "Update progress", "Sample progress indicator")
    lower.pack_start(progress, True, True, 0)

    calendar = Gtk.Calendar()
    _set_accessible(calendar, "Test calendar", "Navigate dates with arrow keys")
    lower.pack_start(calendar, False, False, 0)

    def open_dialog(_button):
        dialog = Gtk.Dialog(
            title="Sample confirmation",
            transient_for=window,
            modal=True,
        )
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("_OK", Gtk.ResponseType.OK)
        area = dialog.get_content_area()
        prompt = Gtk.Label(label="Confirm the sample action.")
        prompt.set_margin_top(12)
        prompt.set_margin_bottom(12)
        area.add(prompt)
        _set_accessible(dialog, "Sample confirmation", "Modal test dialog")
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    dialog_button = Gtk.Button.new_with_label("Open test dialog")
    _set_accessible(dialog_button, "Open test dialog")
    dialog_button.connect("clicked", open_dialog)
    outer.pack_start(dialog_button, False, False, 0)

    status = Gtk.Label(label="Ready")
    status.set_xalign(0)
    _set_accessible(status, "Ready", "Application status")
    outer.pack_start(status, False, False, 0)

    button.connect("clicked", lambda *_: status.set_text("Changes applied"))
    checkbox.connect(
        "toggled",
        lambda widget: status.set_text(
            "Notifications enabled" if widget.get_active() else "Notifications disabled"
        ),
    )

    window.show_all()
    return window


def run_gui() -> int:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except (ImportError, ValueError) as exc:
        print(f"GTK3 is unavailable: {exc}", file=sys.stderr)
        return 2

    class SmokeApplication(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="io.github.mtigzoe.LinuxRdaccessSmoke")

        def do_activate(self):
            build_window(self)

    return SmokeApplication().run(sys.argv)


def main() -> int:
    if "--list-controls" in sys.argv:
        print(json.dumps(CONTROL_SPECS, indent=2, sort_keys=True))
        return 0
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
