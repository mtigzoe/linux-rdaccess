"""Coordinate read-only message detection and one separately authorized route."""

from datetime import datetime, timezone
import math
import time


def checked_trace(reply, *, require_control=True):
    status = reply["status"]
    trace = reply["braille_trace"]
    if (reply["result"] != "connected" or (require_control and status["remote_control_active"] is not True)
            or status["semantic_braille_negotiated"] is not True
            or trace["available"] is not True or trace["dropped"]):
        raise ValueError("Active control and complete numeric diagnostics required")
    return trace


def wait_and_route(client, *, emit=lambda _item: None, wait_seconds=30,
                   clock=time.monotonic, sleep=time.sleep, on_route_attempt=lambda: None):
    """Wait for a NEW message after arming; send at most one v4 request.

    The caller starts the Linux observer first. This function never creates a
    message, sends keyboard input, reconnects, renews consent or retries a route.
    Exceptions after dispatch leave the action outcome unknown.
    """
    if not math.isfinite(wait_seconds) or not 1 <= wait_seconds <= 30:
        raise ValueError("Invalid bounded wait")
    # Arm while Windows is local; do not leave Linux controlled during setup.
    initial = checked_trace(client.operation("braille_trace"), require_control=False)
    outcomes_before = client.operation("braille_outcomes")["braille_outcomes"]
    if not outcomes_before["available"] or outcomes_before["dropped"]:
        raise ValueError("Complete numeric outcomes required")
    previous_count = len(initial["events"])
    emit({"recorder": "armed", "waiting_for": "new_linux_temporary_message",
          "routing_index": 0, "simulated": True})
    deadline = clock() + wait_seconds
    while clock() < deadline:
        reply = client.operation("braille_trace")
        trace = checked_trace(reply, require_control=False)
        new = trace["events"][previous_count:]
        if (reply["status"]["remote_control_active"] is True
                and any(event["event"] == "message_shown" and event["linux_owned"]
                        and event["control"] and not event["capture"] for event in new)):
            started = datetime.now(timezone.utc).isoformat()
            # Exactly one attempt; timeout, refusal and unknown results are final.
            on_route_attempt()
            route = client.operation("braille_message_route")
            replied = datetime.now(timezone.utc).isoformat()
            if route["message_route"]["outcome"] == "queued":
                sleep(0.3)  # Allow the guarded NVDA queue callback to execute.
            return {
                "kind": "scripted-nvda-message-route", "simulated": True,
                "request_started_utc": started, "reply_received_utc": replied,
                "route_reply": route, "trace_before": initial,
                "trace_at_dispatch": trace, "outcomes_before": outcomes_before,
                "trace_after": client.operation("braille_trace")["braille_trace"],
                "outcomes_after": client.operation("braille_outcomes")["braille_outcomes"],
                "physical_braille": "unverified",
            }
        previous_count = len(trace["events"])
        sleep(0.15)
    return {"kind": "scripted-nvda-message-route", "simulated": True,
            "outcome": "no_new_message_no_route_sent", "physical_braille": "unverified"}
