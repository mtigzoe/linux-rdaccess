"""Autostart desktop-entry management for the user-level installation."""
from __future__ import annotations
from pathlib import Path


def write_autostart_file(*, autostart_path: Path, bin_path: Path) -> None:
    autostart_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Desktop Entry]
Type=Application
Name=linux-rdaccess
Comment=Connect Orca Remote for Windows NVDA accessibility
Exec={bin_path} connect --quiet
Terminal=false
X-GNOME-Autostart-enabled=true
"""
    autostart_path.write_text(content, encoding="utf-8")


def remove_autostart_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
