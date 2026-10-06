#!/usr/bin/env python3
"""Check an Orca Remote / NVDA Remote Linux endpoint without exposing secrets."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import shutil
from dataclasses import asdict, dataclass
from typing import Mapping

DEFAULT_CONFIG = Path("~/.local/share/orca/orca-customizations.py").expanduser()
_PLACEHOLDER_HOSTS = {"", "host"}
_PLACEHOLDER_KEYS = {"", "key"}


@dataclass(frozen=True)
class RemoteConfig:
    server: str | None
    port: int | None
    key_configured: bool


@dataclass(frozen=True)
class RemoteStatus:
    config_path: str
    config_exists: bool
    server: str | None
    port: int | None
    key_configured: bool
    display: str | None
    session_type: str | None
    xdotool_available: bool
    ydotool_available: bool
    ready: bool


def parse_remote_config(text: str) -> RemoteConfig:
    """Parse only non-secret Orca Remote settings.

    The key value is reduced to a boolean immediately and is never returned.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return RemoteConfig(server=None, port=None, key_configured=False)

    def value(name):
        assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                       and any(isinstance(target, ast.Name) and target.id == name
                               for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))]
        if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Constant):
            return None
        return assignments[0].value.value

    host = value("YOUR_NVDAREMOTE_SERVER_ADDRESS")
    server = host.strip() if isinstance(host, str) else None
    if server in _PLACEHOLDER_HOSTS:
        server = None

    port = value("YOUR_NVDAREMOTE_SERVER_PORT")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        port = None

    key_value = value("YOUR_NVDAREMOTE_KEY")
    key_configured = isinstance(key_value, str) and key_value not in _PLACEHOLDER_KEYS

    return RemoteConfig(server=server, port=port, key_configured=key_configured)


def collect_status(
    config_path: Path = DEFAULT_CONFIG,
    *,
    environ: Mapping[str, str] | None = None,
) -> RemoteStatus:
    environ = os.environ if environ is None else environ
    exists = config_path.is_file()
    config = RemoteConfig(server=None, port=None, key_configured=False)
    if exists:
        config = parse_remote_config(config_path.read_text(encoding="utf-8"))

    ready = bool(
        exists
        and config.server
        and config.port
        and config.key_configured
    )
    return RemoteStatus(
        config_path=str(config_path),
        config_exists=exists,
        server=config.server,
        port=config.port,
        key_configured=config.key_configured,
        display=environ.get("DISPLAY"),
        session_type=environ.get("XDG_SESSION_TYPE"),
        xdotool_available=shutil.which("xdotool") is not None,
        ydotool_available=shutil.which("ydotool") is not None,
        ready=ready,
    )


def _format_text(status: RemoteStatus) -> str:
    lines = [
        f"Config: {status.config_path}",
        f"Config exists: {'yes' if status.config_exists else 'no'}",
        f"Server: {status.server or 'not configured'}",
        f"Port: {status.port if status.port is not None else 'not configured'}",
        f"Remote key configured: {'yes' if status.key_configured else 'no'}",
        f"DISPLAY: {status.display or 'not set'}",
        f"Session type: {status.session_type or 'unknown'}",
        f"xdotool: {'available' if status.xdotool_available else 'not found'}",
        f"ydotool: {'available' if status.ydotool_available else 'not found'}",
        f"Configuration ready: {'yes' if status.ready else 'no'}",
    ]
    if status.server == "nvdaremote.com":
        lines.append(
            "Note: the public relay may be incompatible with older Linux TLS stacks; "
            "a Windows-hosted LAN session can be used instead."
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true", help="print redacted machine-readable status")
    args = parser.parse_args()

    status = collect_status(args.config.expanduser())
    if args.json:
        print(json.dumps(asdict(status), indent=2, sort_keys=True))
    else:
        print(_format_text(status))
    return 0 if status.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
