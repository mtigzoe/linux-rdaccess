#!/usr/bin/env python3
"""Summarize a linux-rdaccess input trace (metadata only) and flag anomalies.

Usage: summarize_input_trace.py [TRACE] [--timeline] [--since SEQ]

The trace is written by Orca when LINUX_RDACCESS_TRACE=1 is set in Orca's
environment (default ~/.local/share/orca/orca-remote-input-trace.log). It never
contains typed text, braille keyboard input, speech, clipboard data or keys.
This script only reads the file and prints counts, findings and, optionally,
a compact timeline.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

DEFAULT = Path("~/.local/share/orca/orca-remote-input-trace.log").expanduser()


def load(path, since=0):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except ValueError:
                rows.append({"kind": "unreadable", "line": number, "seq": -1})
                continue
            if isinstance(row, dict) and row.get("seq", 0) >= since:
                rows.append(row)
    return rows


def findings(rows):
    out = []
    owned = {}
    for row in rows:
        kind = row.get("kind")
        seq = row.get("seq")
        if kind == "unreadable":
            out.append("line %s is not valid JSON (rotated or truncated?)" % row["line"])
        elif kind == "reset" and row.get("failed"):
            out.append("seq %s: reset (%s) could not release %s; those keys stay owned"
                       % (seq, row.get("reason"), ",".join(row["failed"])))
        elif kind == "forward" and row.get("result") in ("rejected", "raised"):
            out.append("seq %s: injecting %s (%s) %s" % (
                seq, row.get("id"), "down" if row.get("down") else "up", row["result"]))
        elif kind == "main" and row.get("state") == "stale_skipped":
            out.append("seq %s: queued Orca operation skipped, generation %s -> %s"
                       % (seq, row.get("sched_gen"), row.get("gen")))
        elif kind == "lock" and row.get("changed") is False and row.get("down"):
            out.append("seq %s: %s press did not change the XKB lock state"
                       % (seq, row.get("id")))
        elif kind == "lock" and row.get("changed") is None:
            out.append("seq %s: %s state could not be read" % (seq, row.get("id")))
        elif kind == "hook" and str(row.get("decision", "")).startswith("refused"):
            out.append("seq %s: %s %s refused in %s (editable=%s)" % (
                seq, row.get("hook"), row.get("cmd", "-"), row.get("ctx"),
                row.get("editable")))
        elif kind == "hook" and row.get("decision") == "consumer_stale":
            out.append("seq %s: delayed %s consumer found a stale object"
                       % (seq, row.get("hook")))
        elif kind == "key":
            own = row.get("own") or {}
            ident = row.get("id")
            if row.get("press") == "down" and row.get("disp") == "forwarded" and ident:
                owned[ident] = seq
            elif row.get("press") == "up" and ident:
                owned.pop(ident, None)
            both = [name for name in own.get("down", []) if name in ("Insert/ext", "CapsLock")]
            if len(both) == 2 and row.get("press") == "down":
                out.append("seq %s: both NVDA modifiers held; NVDA key = %s"
                           % (seq, own.get("nvda")))
    return out


def timeline(rows):
    lines = []
    for row in rows:
        kind = row.get("kind")
        if kind == "key":
            lines.append("%s key %s %s -> %s%s%s" % (
                row["seq"], row.get("id"), row.get("press"), row.get("disp"),
                " (%s)" % row["why"] if row.get("why") else "",
                " claim=%s%s" % (row["claim"], "/" + row["claim_cmd"]
                                 if row.get("claim_cmd") else "")
                if row.get("claim") else ""))
        else:
            detail = ", ".join("%s=%s" % (k, v) for k, v in sorted(row.items())
                               if k not in ("seq", "t", "kind", "own"))
            lines.append("%s %s %s" % (row.get("seq"), kind, detail))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", nargs="?", default=str(DEFAULT))
    parser.add_argument("--timeline", action="store_true")
    parser.add_argument("--since", type=int, default=0, metavar="SEQ")
    args = parser.parse_args(argv)
    try:
        rows = load(args.trace, args.since)
    except OSError as error:
        print("cannot read trace: %s" % error.strerror, file=sys.stderr)
        return 2
    print("records: %d" % len(rows))
    print("by kind: " + ", ".join("%s=%d" % kv for kv in sorted(
        Counter(row.get("kind") for row in rows).items())))
    keys = Counter(row.get("disp") for row in rows if row.get("kind") == "key")
    if keys:
        print("key dispositions: " + ", ".join("%s=%d" % kv for kv in sorted(keys.items())))
    generations = sorted({row["gen"] for row in rows if isinstance(row.get("gen"), int)})
    if generations:
        print("generations seen: %s" % ",".join(str(g) for g in generations))
    found = findings(rows)
    print("findings: %d" % len(found))
    for line in found:
        print("  " + line)
    if args.timeline:
        print("timeline:")
        for line in timeline(rows):
            print("  " + line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
