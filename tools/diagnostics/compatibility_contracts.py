#!/usr/bin/env python3
"""Focused NVDA-Orca behavioral contracts and honest coverage summary.

These checks exercise the Linux bridge through regression fixtures. They do not
assert that live Windows NVDA, audible speech, or physical braille was tested.
"""
from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

# Executing this script by path otherwise puts tools/diagnostics on sys.path,
# not the repository root that contains the tests and bridge packages.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

AREAS = {
    "keyboard-and-browse": {
        "tests.unit.accessibility.test_browser_command_context",
        "tests.unit.input.test_pass_next",
        "tests.unit.input.test_structural_list_ownership",
    },
    "braille": {
        "tests.unit.braille.test_braille_display_lifecycle",
        "tests.unit.braille.test_braille_cell_alignment",
        "tests.unit.braille.test_braille_routing_speech",
        "tests.unit.braille.test_nvda_native_braille",
    },
    "speech-and-focus": {
        "tests.unit.accessibility.test_say_all_presentation_lifetime",
    },
    "remote-protocol": {
        "tests.integration.test_nvda_remote_loopback",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", required=True, choices=sorted(AREAS))
    parser.add_argument("--modules", required=True)
    args = parser.parse_args()
    modules = args.modules.split()
    expected = AREAS[args.area]
    if len(modules) != len(set(modules)) or set(modules) != expected:
        parser.error("selected test modules differ from the declared contract inventory")

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(modules)
    count = suite.countTestCases()
    if loader.errors or count == 0:
        for error in loader.errors:
            print(error, file=sys.stderr)
        print("Contract inventory failed to load or contained zero tests", file=sys.stderr)
        return 2

    print(f"Contract area: {args.area}; discovered tests: {count}", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = (
        f"NVDA-Orca / {args.area}: tests={result.testsRun}; "
        f"failures={len(result.failures)}; errors={len(result.errors)}; "
        f"skips={len(result.skipped)}; status={'PASS' if result.wasSuccessful() and not result.skipped else 'INCOMPLETE'}"
    )
    print(summary, flush=True)
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as stream:
            stream.write(f"### {args.area}\n\n{summary}\n\n")
            stream.write("Scope: automated Linux compatibility fixtures only. ")
            stream.write("Live NVDA, physical braille, and real user acceptance: **not tested**.\n\n")
    # Unexpected skips are not considered verified behavioral coverage.
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
