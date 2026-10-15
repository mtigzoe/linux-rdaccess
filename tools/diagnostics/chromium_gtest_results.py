#!/usr/bin/env python3
"""Require complete, passing selection gtest evidence from a Chromium build.

This validates a compiled test binary's reports; it does not build Chromium or
establish native application, NVDA, speech, or physical braille acceptance.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TEST_FILTER = (
    "AXPlatformNodeAuraLinuxTest.TestAtkText*Selection*:"
    "AXPlatformNodeAuraLinuxTest.TestAtkTextFindInPageUnicodeOffsets"
)
REQUIRED_TESTS = frozenset(
    f"AXPlatformNodeAuraLinuxTest.{name}"
    for name in (
        "TestAtkTextGetSelectionUnicodeOffsets",
        "TestAtkTextGetSelectionBmpUnicodeOffsets",
        "TestAtkTextGetSelectionMultilineUnicodeOffsets",
        "TestAtkTextGetSelectionTwoSupplementaryChars",
        "TestAtkTextFindInPageUnicodeOffsets",
    )
)


def selected_inventory(listing: str) -> set[str]:
    """Read the filtered gtest list, ignoring launcher preamble and comments."""
    suite = None
    names = set()
    for line in listing.splitlines():
        entry = line.split("#", 1)[0].rstrip()
        if re.fullmatch(r"\S+\.", entry):
            suite = entry[:-1]
        elif suite and re.fullmatch(r"  \S+", entry):
            name = f"{suite}.{entry.strip()}"
            if not any(
                fnmatch.fnmatchcase(name, part) for part in TEST_FILTER.split(":")
            ):
                raise ValueError(f"Unselected test in filtered inventory: {name}")
            if name in names:
                raise ValueError(f"Duplicate listed test: {name}")
            names.add(name)
    missing = REQUIRED_TESTS - names
    if missing:
        raise ValueError(
            f"Required gtests not linked/listed: {', '.join(sorted(missing))}"
        )
    return names


def _check_counts(element: ET.Element, count: int) -> None:
    if element.get("tests") != str(count):
        raise ValueError(f"Incorrect test count in {element.tag}")
    for attribute in ("failures", "errors", "disabled", "skipped"):
        if element.get(attribute, "0") != "0":
            raise ValueError(f"Nonzero {attribute} in {element.tag}")


def validate_results(listing: str, xml: str) -> list[str]:
    """Require every selected test exactly once, executed and passed."""
    inventory = selected_inventory(listing)
    root = ET.fromstring(xml)
    if root.tag != "testsuites":
        raise ValueError("Expected a gtest testsuites XML report")
    observed = set()
    for suite in root.findall("testsuite"):
        cases = suite.findall("testcase")
        _check_counts(suite, len(cases))
        for case in cases:
            name = f"{case.get('classname')}.{case.get('name')}"
            if case.get("classname") != suite.get("name"):
                raise ValueError(f"Test suite/class mismatch: {name}")
            if name in observed:
                raise ValueError(f"Duplicate XML test: {name}")
            observed.add(name)
            # Chromium's merged launcher XML omits result; direct GoogleTest XML
            # emits completed/skipped/suppressed. Both must record a real run.
            if (
                case.get("status") != "run"
                or case.get("result", "completed") != "completed"
            ):
                raise ValueError(f"Test did not run to completion: {name}")
            if any(child.tag in {"failure", "error", "skipped"} for child in case):
                raise ValueError(f"Failed or skipped test: {name}")
    _check_counts(root, len(observed))
    if len(list(root.iter("testcase"))) != len(observed):
        raise ValueError("Unexpected nested or unscoped XML testcases")
    if observed != inventory:
        missing = sorted(inventory - observed)
        extra = sorted(observed - inventory)
        raise ValueError(
            f"Executed inventory differs: missing={missing}, extra={extra}"
        )
    return sorted(observed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-filter", action="store_true")
    parser.add_argument("--test-list", type=Path)
    parser.add_argument("--xml", type=Path)
    args = parser.parse_args()
    if args.print_filter:
        if args.test_list or args.xml:
            parser.error("--print-filter cannot be combined with report paths")
        print(TEST_FILTER)
        return 0
    if not args.test_list or not args.xml:
        parser.error("--test-list and --xml are required")
    try:
        names = validate_results(
            args.test_list.read_text(encoding="utf-8"),
            args.xml.read_text(encoding="utf-8"),
        )
    except (OSError, ValueError, ET.ParseError) as error:
        print(f"ERROR: Incomplete Chromium gtest evidence: {error}", file=sys.stderr)
        return 1
    print(
        f"Verified {len(names)} executed, passing selection gtests (all five patch tests)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
