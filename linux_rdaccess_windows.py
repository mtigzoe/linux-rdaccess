#!/usr/bin/env python3
"""Accessible Windows SSH controller for an installed Linux linux-rdaccess CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

APP = "linux-rdaccess"
COMMANDS = ("connect", "disconnect", "status", "doctor", "compatibility", "shortcuts")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def config_path() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP / "windows-config.json"
    return Path.home() / ".config" / APP / "windows-config.json"


def validate(host: str, username: str, port: int) -> None:
    if not HOST_RE.fullmatch(host) or host.startswith("-") or ".." in host:
        raise ValueError("Invalid SSH hostname or IP address.")
    if not USER_RE.fullmatch(username) or username.startswith("-"):
        raise ValueError("Invalid SSH username.")
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535.")


def save_config(host: str, username: str, port: int, path: Path | None = None) -> None:
    validate(host, username, port)
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"ssh": {"host": host, "username": username, "port": port}}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))["ssh"]
        host, username, port = data["host"], data["username"], data["port"]
        if not isinstance(host, str) or not isinstance(username, str) or type(port) is not int:
            raise ValueError("Invalid SSH configuration types.")
        validate(host, username, port)
        return data
    except FileNotFoundError as exc:
        raise ValueError("No saved SSH connection. Run 'configure' first.") from exc
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("SSH configuration is invalid. Run 'configure' again.") from exc


def configure() -> int:
    print("Linux Remote Access — first-time SSH setup")
    host = input("Linux hostname or IP address: ").strip()
    username = input("Linux SSH username: ").strip()
    port_text = input("SSH port [22]: ").strip()
    try:
        port = int(port_text) if port_text else 22
        save_config(host, username, port)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    print(f"Connection saved to {config_path()}. No password or key was stored.")
    return 0


def ssh_arguments(config: dict, action: str) -> list[str]:
    if action not in COMMANDS:
        raise ValueError("Unsupported remote action.")
    validate(config["host"], config["username"], config["port"])
    return [
        "ssh",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=ask",
        "-p", str(config["port"]),
        "--",
        f'{config["username"]}@{config["host"]}',
        f"~/.local/bin/linux-rdaccess {action}",
    ]


def execute(action: str) -> int:
    try:
        config = load_config()
        command = ssh_arguments(config, action)
        completed = subprocess.run(command, check=False)
        return completed.returncode
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def menu() -> int:
    actions = [("Connect to Linux", "connect"),
               ("Disconnect from Linux", "disconnect"),
               ("Check status", "status"),
               ("Run diagnostics", "doctor"),
               ("Check compatibility", "compatibility"),
               ("Show shortcuts", "shortcuts"),
               ("Configure SSH connection", "configure")]
    while True:
        print("\nLinux Remote Access — Windows Controller")
        for index, (label, _) in enumerate(actions, 1):
            print(f"{index}. {label}")
        print("0. Exit")
        try:
            selection = input("Select an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if selection == "0":
            return 0
        if not selection.isdecimal() or not 1 <= int(selection) <= len(actions):
            print("Invalid selection.")
            continue
        action = actions[int(selection) - 1][1]
        result = configure() if action == "configure" else execute(action)
        if result:
            print(f"Command failed (exit code {result}).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("configure", *COMMANDS))
    args = parser.parse_args(argv)
    if args.action == "configure":
        return configure()
    if args.action:
        return execute(args.action)
    return menu()


if __name__ == "__main__":
    raise SystemExit(main())
