#!/usr/bin/env python3
"""Windows coordinator: observe Linux over SSH, then simulate one NVDA message route.

Requires the separately consented one-shot feature (development companion 20261014.0.4). No physical
key, SSH server on Windows, keyboard injection or active-desktop Linux input.
"""

import argparse
import json
import math
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from linux_rdaccess_core.connection.nvda_test_client import AuthorizedClient  # noqa: E402
from linux_rdaccess_core.routing_automation import wait_and_route  # noqa: E402


def public_observation(value):
    """Retain only numeric target state, never remote labels or error strings."""
    result = {}
    for key in ("before_caret", "after_caret", "dropped_events"):
        item = value.get(key)
        if item is None or (type(item) is int and item >= 0):
            result[key] = item
    for key in ("same_initial_focus", "focus_changed_during_observation"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    elapsed = value.get("elapsed_ms")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and 0 <= elapsed <= 90000:
        result["elapsed_ms"] = elapsed
    events = []
    for event in value.get("events", [])[:64]:
        if event.get("type") == "caret-moved" and type(event.get("caret_offset")) is int:
            when = event.get("elapsed_ms")
            if (event["caret_offset"] >= 0 and type(when) in (int, float)
                    and math.isfinite(when) and 0 <= when <= 90000):
                events.append({"caret_offset": event["caret_offset"], "elapsed_ms": when})
    result["caret_events"] = events
    return result


def software_check(result):
    """Classify only this scripted check, never hardware or issue acceptance."""
    try:
        if result["route_reply"]["message_route"]["outcome"] != "queued":
            return "inconclusive"
        linux = result["linux_observation"]
        trace, outcomes = result["trace_after"], result["outcomes_after"]
        if (result["linux_observer_exit_code"] != 0 or not trace["available"]
                or not outcomes["available"] or trace["dropped"] or outcomes["dropped"]
                or linux["dropped_events"] or not linux["same_initial_focus"]
                or linux["focus_changed_during_observation"]):
            return "inconclusive"
        if type(linux["before_caret"]) is not int or type(linux["after_caret"]) is not int:
            return "inconclusive"
        started = datetime.fromisoformat(result["request_started_utc"])
        linux_final = datetime.fromisoformat(result["linux_final_received_utc"])
        if not (datetime.fromisoformat(result["linux_ready_received_utc"]) <= started
                <= linux_final <= datetime.fromisoformat(result["windows_final_received_utc"])):
            return "inconclusive"
        fresh = outcomes["events"][len(result["outcomes_before"]["events"]):]
        forbidden = {"caret_attempted", "caret_rejected", "caret_send_returned",
                     "caret_send_failed", "activation_attempted"}
        if (linux["before_caret"] != linux["after_caret"]
                or any(event["caret_offset"] != linux["before_caret"] for event in linux["caret_events"])
                or any(event["event"] in forbidden for event in fresh)):
            return "fail"
        if any(event["event"] in {"outcome_unknown", "route_discarded"} for event in fresh):
            return "inconclusive"
        return "pass" if any(event["event"] == "message_dismissed" for event in fresh) else "inconclusive"
    except (KeyError, TypeError, ValueError):
        return "inconclusive"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--ssh-host", default="cyber", help="Existing verified SSH alias")
    parser.add_argument("--observer-path", required=True, help="Absolute reviewed Linux observe_routing.py path")
    args = parser.parse_args(argv)
    if (os.name != "nt" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.ssh_host)
            or not PurePosixPath(args.observer_path).is_absolute()
            or any(char in args.observer_path for char in "\r\n\0")):
        parser.error("Windows and a verified SSH alias/absolute observer path are required")
    process = None
    reader = None
    route_may_have_been_sent = False
    try:
        client = AuthorizedClient()
        status = client.operation("status")
        if status["result"] != "connected" or not status["status"]["semantic_braille_negotiated"]:
            raise ValueError("Connected semantic session required")
        remote = shlex.join(["python3", "-B", args.observer_path,
                             "--application", "mousepad", "--duration", "45"])
        process = subprocess.Popen(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
             "-o", "ConnectTimeout=8", args.ssh_host, remote],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        records = queue.Queue(maxsize=4)

        def read():
            try:
                for line in iter(lambda: process.stdout.readline(32769), ""):
                    if len(line) > 32768:
                        break
                    records.put_nowait(json.loads(line))
            except Exception:
                pass
            finally:
                try:
                    records.put_nowait(None)
                except queue.Full:
                    pass

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        ready = records.get(timeout=10)
        ready_received_utc = datetime.now(timezone.utc).isoformat()
        if (not isinstance(ready, dict) or ready.get("observer") != "ready"
                or ready.get("application") != "mousepad" or ready.get("input_sent") is not False):
            raise ValueError("Linux observer unavailable")
        print(json.dumps({"linux_observer": "ready", **public_observation(ready)}), flush=True)
        def attempted():
            nonlocal route_may_have_been_sent
            route_may_have_been_sent = True

        result = wait_and_route(client, emit=lambda item: print(json.dumps(item), flush=True),
                                on_route_attempt=attempted)
        final = records.get(timeout=50)
        if not isinstance(final, dict) or final.get("kind") != "linux-atspi-caret-observation":
            raise ValueError("Linux final observation unavailable")
        result["linux_observation"] = public_observation(final)
        result["linux_ready_received_utc"] = ready_received_utc
        result["linux_final_received_utc"] = datetime.now(timezone.utc).isoformat()
        result["linux_observer_exit_code"] = process.wait(timeout=5)
        # The early queue snapshot cannot cover delayed actions during the
        # remaining Linux observation. Preserve it, then collect both ledgers
        # after the observer finishes before classifying the whole trial.
        for ledger in ("trace", "outcomes"):
            key = ledger + "_after"
            if key in result:
                result[ledger + "_after_dispatch"] = result[key]
            result[key] = client.operation("braille_" + ledger)["braille_" + ledger]
        result["windows_final_received_utc"] = datetime.now(timezone.utc).isoformat()
        result["software_check"] = software_check(result)
        print(json.dumps(result), flush=True)
        return {"pass": 0, "fail": 1, "inconclusive": 2}[result["software_check"]]
    except (Exception, KeyboardInterrupt):
        print(json.dumps({"recorder": "stopped", "simulated": True,
                          "route_outcome": "unknown" if route_may_have_been_sent else "not_sent",
                          "physical_braille": "unverified", "automatic_retry": False}), flush=True)
        return 2
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        if reader is not None:
            reader.join(timeout=1)
        if process is not None and process.stdout is not None:
            process.stdout.close()


if __name__ == "__main__":
    raise SystemExit(main())
