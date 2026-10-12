#!/usr/bin/env python3
"""Safe Windows-side readiness probe for AI-assisted linux-rdaccess testing.

Does not control NVDA or claim a live semantic-braille connection.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys

from linux_rdaccess_core.connection import windows_controller as controller

STATUS_FLAGS = ("key_configured", "ready", "autostart_enabled",
                "command_installed", "orca_remote_config_found")


def _windows_nvda() -> str:
    """Return running/not_running/unavailable without exposing process details."""
    if os.name != "nt":
        return "unavailable"
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq nvda.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if result.returncode:
            return "unavailable"
        rows = list(csv.reader(io.StringIO(result.stdout)))
        return "running" if any(row and row[0].casefold() == "nvda.exe" for row in rows) else "not_running"
    except (OSError, subprocess.TimeoutExpired, csv.Error):
        return "unavailable"


def _ssh(action: str) -> tuple[bool, str]:
    """Run only allowlisted controller commands; never surface remote output."""
    config = controller.load_config()
    command = controller.ssh_arguments(config, action)
    # Noninteractive and pinning required; never accept an unverified host key.
    flag = command.index("StrictHostKeyChecking=ask")
    command[flag] = "StrictHostKeyChecking=yes"
    command[1:1] = ["-o", "BatchMode=yes", "-o", "ConnectionAttempts=1"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                check=False, timeout=35)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return result.returncode == 0, result.stdout if result.returncode == 0 else ""


def _flags(raw: str) -> dict[str, bool | None]:
    parsed = {}
    for line in raw.splitlines():
        field, separator, value = line.partition(":")
        if separator and field.strip() in STATUS_FLAGS:
            value = value.strip().lower()
            parsed[field.strip()] = {"true": True, "false": False}.get(value)
    return {field: parsed.get(field) for field in STATUS_FLAGS}


def probe(*, start: bool = False) -> tuple[dict, int]:
    result = {
        "linux_ssh": "unavailable",
        "linux_config": {field: None for field in STATUS_FLAGS},
        "windows_nvda": _windows_nvda(),
        "windows_remote_connected": "unverified",
        "semantic_braille_negotiated": "unverified",
        "physical_braille": "unverified",
        "started_linux_connection": False,
    }
    try:
        controller.load_config()
    except ValueError:
        result["linux_ssh"] = "not_configured"
        return result, 2
    if start:
        success, _ = _ssh("connect")
        if not success:
            result["linux_ssh"] = "command_failed"
            return result, 1
        result["started_linux_connection"] = True
    success, raw = _ssh("status")
    if not success:
        result["linux_ssh"] = "command_failed"
        return result, 1
    result["linux_ssh"] = "reachable"
    result["linux_config"] = _flags(raw)
    return result, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "doctor", "start"))
    parser.add_argument("--confirm-start", action="store_true",
                        help="Explicit authorization to run Linux connect (may restart Orca)")
    args = parser.parse_args(argv)
    if args.command == "start" and not args.confirm_start:
        parser.error("start requires --confirm-start; it may restart Orca")
    if args.command != "start" and args.confirm_start:
        parser.error("--confirm-start only applies to start")
    result, code = probe(start=args.command == "start")
    result["mode"] = args.command
    if args.command == "doctor":
        result["limitations"] = [
            "SSH readiness is not an NVDA Remote connection check",
            "Live keyboard, speech, and physical braille require user confirmation",
            "Stage 2 Windows add-on local IPC is not implemented",
        ]
    print(json.dumps(result, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
