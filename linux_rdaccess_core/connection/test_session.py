"""Authorized Windows connection orchestration without restarting Orca or NVDA."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .nvda_test_client import AuthorizedClient


def windows_operation(action: str, path: Path | None = None) -> tuple[dict, int]:
    client = None
    try:
        client = AuthorizedClient(path)
        reply = client.operation(action)
    except (OSError, ValueError, ImportError, EOFError, TimeoutError):
        if action == "braille_message_route":
            # A request may have executed before the response was lost. Never retry.
            return {"windows_authorization": "unavailable_or_expired",
                    "message_route": {"outcome": "unknown", "simulated": True},
                    "physical_braille": "unverified"}, 2
        if action in ("braille_trace", "braille_outcomes") and client is not None:
            try:
                status = client.operation("status")
            except (OSError, ValueError, ImportError, EOFError, TimeoutError):
                pass
            else:
                return {"windows_authorization": "active", **status,
                        "routing_trace": "unavailable_or_unsupported"}, 2
        return {"windows_authorization": "required_or_expired", "physical_braille": "unverified"}, 2
    code = 0
    if action == "braille_message_route" and reply["message_route"]["outcome"] != "queued":
        code = 2
    return {"windows_authorization": "active", **reply}, code


def start_all(
    probe: Callable, *, path: Path | None = None,
    client_factory: Callable = AuthorizedClient, timeout: float = 30,
) -> tuple[dict, int]:
    result = {
        "mode": "start-all", "windows_authorization": "required_or_expired",
        "windows_remote_connected": False, "semantic_braille_negotiated": False,
        "physical_braille": "unverified", "linux_session": "not_checked",
        "cleanup": "not_needed",
    }
    try:
        client = client_factory(path)
    except (OSError, ValueError, ImportError):
        result["next_step"] = "Authorize a five-minute test session in NVDA Tools"
        return result, 2
    result["windows_authorization"] = "active"
    # This probe is read-only. The existing Linux connect command can restart
    # Orca and is deliberately never invoked by start-all.
    linux, code = probe(start=False)
    result["linux_ssh"] = linux["linux_ssh"]
    result["linux_config"] = linux["linux_config"]
    if code or any(linux["linux_config"].get(field) is not True for field in (
        "ready", "orca_remote_config_found",
    )):
        result["linux_session"] = "setup_required"
        result["next_step"] = "Complete Linux Remote Access setup; start-all will not restart Orca"
        return result, 2
    result["linux_session"] = "configured_existing_session"
    attempted = False
    succeeded = False
    try:
        reply = client.operation("status")
        if reply["result"] != "connected":
            attempted = True
            reply = client.operation("connect")
        deadline = time.monotonic() + timeout
        while reply["result"] == "connecting" and time.monotonic() < deadline:
            time.sleep(0.25)
            reply = client.operation("status")
        result["windows_result"] = reply["result"]
        if reply["result"] not in ("connected", "already_connected"):
            result["next_step"] = "Check NVDA authorization and saved controlling relay settings"
            return result, 1
        result["windows_remote_connected"] = True
        result["semantic_braille_negotiated"] = reply["status"]["semantic_braille_negotiated"]
        result["windows_status"] = reply["status"]
        result["next_step"] = (
            "Use the normal NVDA Remote control shortcut when ready; "
            "speech and physical braille need live verification"
        )
        succeeded = True
        return result, 0
    except (OSError, ValueError, ImportError, EOFError, TimeoutError):
        result["windows_result"] = "ipc_failed_or_revoked"
        return result, 1
    except KeyboardInterrupt:
        result["windows_result"] = "cancelled"
        return result, 130
    finally:
        if attempted and not succeeded:
            try:
                client.operation("cancel")
                result["cleanup"] = "session_owned_connection_cancelled"
            except (OSError, ValueError, ImportError, EOFError, TimeoutError):
                result["cleanup"] = "authorization_expiry_will_cleanup"
