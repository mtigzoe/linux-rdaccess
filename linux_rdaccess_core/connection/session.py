"""Coordinate Linux Orca Remote connection lifecycle without changing CLI behavior."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Any


def connect_session(
    *, config_path: Path, orca_config: Path, restart: bool, quiet: bool,
    load_config: Callable[[Path], Any],
    update_customizations: Callable[[Any, Path], Any],
    restart_orca: Callable[[], int],
) -> int:
    config = load_config(config_path)
    if not config.ready:
        if not quiet:
            print("Remote Access configuration is incomplete.")
            print("Run: linux-rdaccess configure --role host --generate-key")
        return 1
    if not orca_config.exists():
        if not quiet:
            print(f"Orca Remote legacy config not found: {orca_config}")
        return 1
    update_customizations(config, orca_config)
    if not quiet:
        print(f"Configured {config.host}:{config.port} as role {config.role}.")
        print("Remote Access key remains hidden.")
    if restart:
        return restart_orca()
    return 0


def disconnect_session(
    *, orca_config: Path, restart: bool, quiet: bool,
    disable_connection: Callable[[Path], Any],
    restart_orca: Callable[[], int],
) -> int:
    if not orca_config.exists():
        if not quiet:
            print(f"Orca Remote legacy config not found: {orca_config}")
        return 1
    disable_connection(orca_config)
    if not quiet:
        print("Disabled Orca Remote auto-connect. Saved linux-rdaccess settings were kept.")
    if restart:
        return restart_orca()
    return 0
