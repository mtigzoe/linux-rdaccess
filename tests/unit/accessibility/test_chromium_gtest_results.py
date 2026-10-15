"""Synthetic report/process regressions; these do not build or run Chromium."""

from __future__ import annotations

import copy
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.diagnostics import chromium_gtest_results as results

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/linux/run_chromium_selection_gtests.sh"
SUITE = "AXPlatformNodeAuraLinuxTest"
PATCH_TESTS = (
    "TestAtkTextGetSelectionUnicodeOffsets",
    "TestAtkTextGetSelectionBmpUnicodeOffsets",
    "TestAtkTextGetSelectionMultilineUnicodeOffsets",
    "TestAtkTextGetSelectionTwoSupplementaryChars",
    "TestAtkTextFindInPageUnicodeOffsets",
)
EXISTING_TEST = "TestAtkTextTextFieldGetSelection"
TEST_NAMES = (*PATCH_TESTS, EXISTING_TEST)


def listing(names=TEST_NAMES):
    return f"Launcher preamble\n{SUITE}.\n" + "".join(f"  {name}\n" for name in names)


def report(names=TEST_NAMES):
    root = ET.Element("testsuites", tests=str(len(names)), failures="0", disabled="0")
    suite = ET.SubElement(
        root, "testsuite", name=SUITE, tests=str(len(names)), failures="0", disabled="0"
    )
    for name in names:
        ET.SubElement(
            suite,
            "testcase",
            name=name,
            classname=SUITE,
            status="run",
            result="completed",
        )
    return root


def xml(root):
    return ET.tostring(root, encoding="unicode")


class ChromiumGtestResultsTests(unittest.TestCase):
    def test_filter_includes_every_patch_test_and_existing_selection_regression(self):
        for name in TEST_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    any(
                        fnmatch.fnmatchcase(f"{SUITE}.{name}", part)
                        for part in results.TEST_FILTER.split(":")
                    )
                )

    def test_complete_report_requires_all_selected_existing_tests_too(self):
        expected = sorted(f"{SUITE}.{name}" for name in TEST_NAMES)
        self.assertEqual(results.validate_results(listing(), xml(report())), expected)
        # Parameter comments in --gtest_list_tests are not part of test names.
        commented = listing().replace(
            f"  {PATCH_TESTS[0]}\n", f"  {PATCH_TESTS[0]} # info\n"
        )
        self.assertEqual(results.validate_results(commented, xml(report())), expected)

    def test_chromium_launcher_xml_without_result_attribute_passes(self):
        # Chromium 150 test_results_tracker.cc serializes successful merged
        # testcase nodes with status/name/time/classname, but no result field.
        root = report()
        root.set("name", "AllTests")
        for element in (root, root.find("testsuite")):
            element.set("errors", "0")
            element.set("time", "0.006")
            element.set("timestamp", "2026-10-15T12:00:00")
        for case in root.iter("testcase"):
            del case.attrib["result"]
            case.set("time", "0.001")
        expected = sorted(f"{SUITE}.{name}" for name in TEST_NAMES)
        self.assertEqual(results.validate_results(listing(), xml(root)), expected)
        ET.SubElement(root.find("testsuite/testcase"), "failure")
        with self.assertRaises(ValueError):
            results.validate_results(listing(), xml(root))

    def test_missing_linkage_execution_or_all_execution_is_rejected(self):
        without_find = tuple(name for name in TEST_NAMES if name != PATCH_TESTS[-1])
        cases = (
            (listing(without_find), xml(report(without_find))),
            (listing(), xml(report(without_find))),
            (listing(), xml(report(PATCH_TESTS))),
            (listing(), xml(report(()))),
            ("", xml(report())),
        )
        for listed, observed in cases:
            with (
                self.subTest(listed=listed, observed=observed),
                self.assertRaises(ValueError),
            ):
                results.validate_results(listed, observed)

    def test_failed_skipped_disabled_or_unfinished_test_is_rejected(self):
        for attribute, value in (
            ("status", "notrun"),
            ("status", ""),
            ("result", "suppressed"),
            ("result", "skipped"),
            ("result", ""),
        ):
            root = report()
            root.find("testsuite/testcase").set(attribute, value)
            with (
                self.subTest(attribute=attribute, value=value),
                self.assertRaises(ValueError),
            ):
                results.validate_results(listing(), xml(root))
        for tag in ("failure", "error", "skipped"):
            root = report()
            ET.SubElement(root.find("testsuite/testcase"), tag)
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                results.validate_results(listing(), xml(root))
        for target in ("root", "suite"):
            for counter in ("failures", "errors", "disabled", "skipped"):
                root = report()
                element = root if target == "root" else root.find("testsuite")
                element.set(counter, "1")
                with (
                    self.subTest(target=target, counter=counter),
                    self.assertRaises(ValueError),
                ):
                    results.validate_results(listing(), xml(root))

    def test_duplicate_unlisted_or_inconsistent_reports_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate listed"):
            results.validate_results(
                listing((*TEST_NAMES, PATCH_TESTS[0])), xml(report())
            )
        duplicate = report()
        duplicate.find("testsuite").append(
            copy.deepcopy(duplicate.find("testsuite/testcase"))
        )
        duplicate.set("tests", "7")
        duplicate.find("testsuite").set("tests", "7")
        with self.assertRaisesRegex(ValueError, "Duplicate XML"):
            results.validate_results(listing(), xml(duplicate))
        for target in ("root", "suite", "class"):
            root = report()
            if target == "class":
                root.find("testsuite/testcase").set("classname", "AnotherSuite")
            else:
                element = root if target == "root" else root.find("testsuite")
                element.set("tests", "0")
            with self.subTest(target=target), self.assertRaises(ValueError):
                results.validate_results(listing(), xml(root))
        with self.assertRaisesRegex(ValueError, "extra="):
            results.validate_results(
                listing(), xml(report((*TEST_NAMES, "UnexpectedTest")))
            )


# These executables deliberately fake the checkout, hash checks, build and gtest
# process so we can test shell orchestration without claiming source/native QA.
FAKE_COMMAND = r"""
import os
import sys

command = os.path.basename(sys.argv[0])
if command == 'sha256sum':
    sys.stdin.read()
    print('synthetic fixture hashes: OK')
elif command == 'git' and 'rev-parse' in sys.argv:
    print('a' * 40)
"""

FAKE_BINARY = r"""
import fnmatch
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

names = TEST_NAMES
mode = os.environ.get('FAKE_GTEST_MODE', 'pass')
with open(os.environ['FAKE_GTEST_CALLS'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps({
        'args': sys.argv[1:],
        'inherited': {key: value for key, value in os.environ.items()
                      if key.startswith('GTEST_') or key.startswith('TEST_SHARD')
                      or key == 'TEST_TOTAL_SHARDS'},
    }) + '\n')
pattern = next((value.split('=', 1)[1] for value in sys.argv if value.startswith('--gtest_filter=')), '*')
names = [name for name in names
         if any(fnmatch.fnmatchcase(SUITE + '.' + name, part) for part in pattern.split(':'))]
if mode == 'list_missing':
    names = [name for name in names if name != 'TestAtkTextFindInPageUnicodeOffsets']
if '--gtest_list_tests' in sys.argv:
    print(SUITE + '.')
    for name in names:
        print('  ' + name)
    sys.exit(0)
if mode == 'no_xml':
    sys.exit(0)
if mode == 'missing':
    names = [name for name in names if name != 'TestAtkTextFindInPageUnicodeOffsets']
elif mode == 'no_run':
    names = []
elif mode == 'duplicate':
    names.append(names[0])
root = ET.Element('testsuites', tests=str(len(names)), failures='0', disabled='0')
suite = ET.SubElement(root, 'testsuite', name=SUITE, tests=str(len(names)), failures='0', disabled='0')
for name in names:
    ET.SubElement(suite, 'testcase', name=name, classname=SUITE, status='run', result='completed')
case = suite.find('testcase')
if mode == 'skipped':
    case.set('result', 'skipped')
    ET.SubElement(case, 'skipped')
elif mode == 'disabled':
    case.set('status', 'notrun')
    case.set('result', 'suppressed')
elif mode == 'failed':
    ET.SubElement(case, 'failure')
output = next(value.split('xml:', 1)[1] for value in sys.argv if value.startswith('--gtest_output=xml:'))
ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)
sys.exit(19 if mode == 'nonzero' else 0)
"""


@unittest.skipUnless(
    sys.platform == "linux", "Synthetic shell orchestration requires Linux"
)
class ChromiumGtestRunnerResultsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "chromium"
        platform = self.source / "ui/accessibility/platform"
        platform.mkdir(parents=True)
        (self.source / ".gn").write_text("")
        for name in (
            "ax_platform_node_auralinux.cc",
            "ax_platform_node_auralinux_unittest.cc",
        ):
            (platform / name).write_text("synthetic source fixture")
        output = self.source / "out/Default"
        output.mkdir(parents=True)
        (output / "build.ninja").write_text("synthetic build fixture")
        commands = self.root / "bin"
        commands.mkdir()
        for name in ("git", "sha256sum", "gn", "autoninja"):
            self.executable(commands / name, FAKE_COMMAND)
        constants = f"SUITE = {SUITE!r}\nTEST_NAMES = {TEST_NAMES!r}\n"
        self.executable(output / "accessibility_unittests", constants + FAKE_BINARY)
        self.evidence = self.root / "evidence"
        self.calls = self.root / "calls.jsonl"
        self.environment = {
            **os.environ,
            "PATH": str(commands) + os.pathsep + os.environ.get("PATH", ""),
            "CHROMIUM_GTEST_EVIDENCE": str(self.evidence),
            "FAKE_GTEST_CALLS": str(self.calls),
        }

    @staticmethod
    def executable(path, content):
        path.write_text(f"#!{sys.executable}\n{content}", encoding="utf-8")
        path.chmod(0o755)

    def invoke(self, mode="pass", **environment):
        return subprocess.run(
            ["bash", str(RUNNER), str(self.source)],
            check=False,
            env={**self.environment, "FAKE_GTEST_MODE": mode, **environment},
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_runner_executes_complete_filter_once_without_inherited_sharding(self):
        result = self.invoke(
            GTEST_REPEAT="0",
            GTEST_TOTAL_SHARDS="8",
            GTEST_SHARD_INDEX="7",
            GTEST_LIST_TESTS="1",
            GTEST_FILTER="Unrelated.*",
            TEST_TOTAL_SHARDS="8",
            TEST_SHARD_INDEX="7",
            TEST_SHARD_STATUS_FILE="unwanted-status",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call["inherited"], {})
            self.assertIn(f"--gtest_filter={results.TEST_FILTER}", call["args"])
        self.assertIn("--gtest_repeat=1", calls[1]["args"])
        self.assertIn("--test-launcher-retry-limit=0", calls[1]["args"])
        self.assertIn("all five patch tests", result.stdout)

    def test_runner_filter_executes_find_and_existing_selection_tests(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = ET.parse(self.evidence / "selection-gtests.xml").getroot()
        self.assertEqual(
            {case.get("name") for case in root.iter("testcase")}, set(TEST_NAMES)
        )

    def test_zero_exit_without_complete_passing_xml_is_rejected(self):
        for mode in (
            "list_missing",
            "missing",
            "no_xml",
            "no_run",
            "duplicate",
            "skipped",
            "disabled",
            "failed",
        ):
            with self.subTest(mode=mode):
                self.evidence = self.root / f"evidence-{mode}"
                self.environment["CHROMIUM_GTEST_EVIDENCE"] = str(self.evidence)
                result = self.invoke(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("Compiled upstream test evidence:", result.stdout)

    def test_stale_evidence_is_rejected_before_running_and_preserved(self):
        self.evidence.mkdir()
        previous = xml(report())
        report_path = self.evidence / "selection-gtests.xml"
        report_path.write_text(previous)
        result = self.invoke("no_xml")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Evidence directory must be new", result.stderr)
        self.assertEqual(report_path.read_text(), previous)
        self.assertFalse(self.calls.exists())

    def test_nonzero_test_process_is_preserved_even_with_passing_xml(self):
        result = self.invoke("nonzero")
        self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
        self.assertFalse((self.evidence / "verified-results.log").exists())


if __name__ == "__main__":
    unittest.main()
