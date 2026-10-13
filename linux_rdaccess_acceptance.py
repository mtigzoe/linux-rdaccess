#!/usr/bin/env python3
"""Offline, accessible evidence tracker for NVDA–Orca live acceptance.

Never sends input, connects remotely, or claims a test passed automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from linux_rdaccess_core import acceptance_report

CASES = (
    ("keyboard.caps_toggle", 57, "Caps Lock toggles Linux XKB state on and off"),
    ("keyboard.num_toggle", 57, "Num Lock toggles Linux XKB state on and off"),
    ("keyboard.nvda_modifier", 57, "Caps Lock as NVDA modifier does not toggle the lock"),
    ("speech.interrupt", 58, "Ctrl interrupts remote speech without stale output"),
    ("speech.say_all", 58, "Say All starts and stops without stale callbacks"),
    ("braille.route", 59, "Physical braille routing moves the intended caret"),
    ("braille.pan", 59, "Physical braille pan maintains NVDA presentation"),
    ("applications.settings", 60, "Settings navigation and focus are announced"),
    ("applications.firefox", 60, "Firefox structural navigation and element list work"),
    ("applications.vscode", 60, "VS Code focus and caret are announced"),
    ("lifecycle.handoff", 61, "Local-to-remote control restores focus with no stuck keys"),
    ("lifecycle.reconnect", 61, "Reconnect does not replay stale speech, keys or braille"),
    ("messages.flash", 72, "Orca transient status displays through Windows NVDA"),
    ("messages.dismiss", 72, "Routing dismisses temporary message without activation"),
    ("messages.restore", 72, "Temporary message expiry restores focus/caret"),
)
STATUSES = ("unverified", "pass", "fail", "blocked")


def template() -> dict:
    return {
        "schema_version": 1,
        "kind": "human-observed-live-acceptance",
        "notes": "Results must be manually observed; automated scripts cannot certify NVDA speech or physical braille.",
        "cases": [
            {"id": case_id, "issue": issue, "expected": expected,
             "status": "unverified", "observed": ""}
            for case_id, issue, expected in CASES
        ],
    }


def validate(report: dict) -> None:
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("invalid report schema")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != len(CASES):
        raise ValueError("invalid case list")
    for case, (case_id, issue, expected) in zip(cases, CASES):
        if not isinstance(case, dict) or case.get("id") != case_id:
            raise ValueError("invalid or reordered case")
        if case.get("issue") != issue or case.get("expected") != expected:
            raise ValueError("case metadata changed")
        if case.get("status") not in STATUSES:
            raise ValueError("invalid case status")
        if not isinstance(case.get("observed"), str) or len(case["observed"]) > 500:
            raise ValueError("observation must contain at most 500 characters")
        if case["status"] in ("pass", "fail") and not case["observed"].strip():
            raise ValueError("pass/fail requires human observation")


def summary(report: dict) -> dict:
    validate(report)
    counts = {state: 0 for state in STATUSES}
    for case in report["cases"]:
        counts[case["status"]] += 1
    return {"total": len(CASES), **counts,
            "live_accepted": counts["pass"] == len(CASES),
            "physical_braille_verified": all(
                c["status"] == "pass" for c in report["cases"] if c["issue"] in (59, 72)
            )}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("template", "summary", "session-template", "session-summary"))
    parser.add_argument("--file", type=Path, help="Manual evidence JSON file")
    args = parser.parse_args(argv)
    if args.action == "template":
        result = template()
    elif args.action == "session-template":
        result = acceptance_report.template()
    else:
        if not args.file:
            parser.error(f"{args.action} requires --file")
        try:
            report = json.loads(args.file.read_text(encoding="utf-8"))
            result = acceptance_report.summary(report) if args.action == "session-summary" else summary(report)
        except (OSError, UnicodeError, ValueError) as error:
            parser.error(f"invalid evidence file: {error}")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
