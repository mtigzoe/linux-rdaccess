"""Fail-closed tests for the opt-in compiled Chromium gtest runner.

These tests intentionally do not compile Chromium or claim native accessibility validation.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/linux/run_chromium_selection_gtests.sh"


class ChromiumGtestRunnerPreflightTests(unittest.TestCase):
    def invoke(self, source, env=None):
        return subprocess.run(
            ["bash", str(RUNNER), str(source)],
            cwd=ROOT,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_help_succeeds_without_checkout(self):
        result = subprocess.run(
            ["bash", str(RUNNER), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CHROMIUM_SRC", result.stderr)

    def test_missing_checkout_fails_without_creating_source(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "missing"
            result = self.invoke(source, {
                "CHROMIUM_GTEST_EVIDENCE": str(Path(root) / "evidence")
            })
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(source.exists())

    def test_mismatched_source_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "chromium"
            platform = source / "ui/accessibility/platform"
            platform.mkdir(parents=True)
            (source / ".gn").write_text("")
            original = platform / "ax_platform_node_auralinux.cc"
            original.write_text("invalid pinned Chromium source")
            tests = platform / "ax_platform_node_auralinux_unittest.cc"
            tests.write_text("invalid upstream tests")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            for command in ("autoninja", "gn"):
                executable = fake_bin / command
                executable.write_text("#!/bin/sh\nexit 99\n")
                executable.chmod(0o755)
            result = self.invoke(source, {
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "CHROMIUM_GTEST_EVIDENCE": str(root / "evidence")
            })
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FAILED", result.stdout + result.stderr)
            self.assertEqual(original.read_text(), "invalid pinned Chromium source")
            self.assertEqual(tests.read_text(), "invalid upstream tests")
            self.assertFalse((root / "evidence" / "patch-state.txt").exists())


if __name__ == "__main__":
    unittest.main()
