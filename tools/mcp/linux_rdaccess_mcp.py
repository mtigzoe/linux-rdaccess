#!/usr/bin/env python3
"""Read-only stdio MCP adapter for existing linux-rdaccess diagnostics."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOLS = [
    {"name": "atspi_status", "description": "Count AT-SPI applications without revealing names.", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 0, "maximum": 20}}, "additionalProperties": False}},
    {"name": "atspi_event_counts", "description": "Observe redacted AT-SPI events for a bounded interval.", "inputSchema": {"type": "object", "properties": {"seconds": {"type": "integer", "minimum": 1, "maximum": 15}}, "additionalProperties": False}},
    {"name": "x11_status", "description": "Read X11 diagnostics; never inject input.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def tool_command(name: str, args: dict[str, Any]) -> tuple[list[str], int]:
    if name == "atspi_status":
        limit = args.get("limit", 0)
        if type(limit) is not int or not 0 <= limit <= 20:
            raise ValueError("limit must be an integer 0–20")
        return [sys.executable, str(ROOT / "diagnostics/atspi/atspi_probe.py"), "--limit", str(limit)], 10
    if name == "atspi_event_counts":
        seconds = args.get("seconds", 5)
        if type(seconds) is not int or not 1 <= seconds <= 15:
            raise ValueError("seconds must be an integer 1–15")
        return [sys.executable, str(ROOT / "diagnostics/atspi/atspi_event_probe.py"), "--seconds", str(seconds)], seconds + 8
    if name == "x11_status":
        display = os.environ.get("DISPLAY", "")
        if not display.startswith(":") or any(ch in display for ch in " \t\n\r"):
            raise ValueError("A local X11 DISPLAY is required")
        return [sys.executable, str(ROOT / "diagnostics/x11/live_x11.py"), "--display", display], 12
    raise ValueError("Unknown tool")


def dispatch(msg: dict[str, Any]) -> dict[str, Any] | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None

    def reply(result=None, error=None):
        return {"jsonrpc": "2.0", "id": mid, "error" if error else "result": error or result}

    if method == "initialize":
        return reply({"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "linux-rdaccess-diagnostics", "version": "0.1.0"}})
    if method == "ping":
        return reply({})
    if method == "tools/list":
        return reply({"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params")
        if not isinstance(params, dict):
            return reply(error={"code": -32602, "message": "Invalid params"})
        name, args = params.get("name"), params.get("arguments", {})
        match = next((tool for tool in TOOLS if tool["name"] == name), None)
        if match is None or not isinstance(args, dict) or set(args) - set(match["inputSchema"]["properties"]):
            return reply(error={"code": -32602, "message": "Invalid tool or arguments"})
        try:
            cmd, timeout = tool_command(name, args)
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout, check=False)
            output = result.stdout[:12000] if result.returncode == 0 else f"Diagnostic exited with status {result.returncode}; inspect local logs for details"
            return reply({"content": [{"type": "text", "text": output or "No diagnostic output"}], "isError": result.returncode != 0})
        except (ValueError, subprocess.TimeoutExpired, OSError) as exc:
            return reply({"content": [{"type": "text", "text": f"Diagnostic unavailable: {type(exc).__name__}"}], "isError": True})
    return reply(error={"code": -32601, "message": "Method not found"})


def main() -> None:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                continue
            response = dispatch(request)
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
