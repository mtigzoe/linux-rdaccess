#!/usr/bin/env python3
"""Validate and decode one rdAccess -> Linux remote A11Y action request."""

from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from a11y_link import decode_action_request

raw = json.load(sys.stdin)
decoded = decode_action_request(raw)
if decoded is None:
    raise SystemExit("invalid remote A11Y action request")
object_id, action_index = decoded
print(
    json.dumps(
        {"object_id": object_id, "action_index": action_index},
        separators=(",", ":"),
    )
)
