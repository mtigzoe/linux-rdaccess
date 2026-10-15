"""Pin the reviewed native experiment and reject unsafe or changed inputs."""

import argparse
import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.diagnostics import vscode_native_selection_experiment as native


class NativeByteTests(unittest.TestCase):
    def test_exact_five_reviewed_edits_and_binary_hashes_are_pinned(self):
        self.assertEqual(
            [
                (address, before.hex(), after.hex())
                for address, before, after in native.EDITS
            ],
            [
                (0xA325803, "4963c5488d4db0488901", "e9090300009090909090"),
                (0xA325931, "0f85ccfeffff", "0f858a080000"),
                (0xA325945, "e9b9feffff", "e977080000"),
                (0xA325B11, "cc" * 15, "4489e94189d4e943fdffff" + "cc" * 4),
                (0xA3261C1, "cc" * 15, "4963c5488d4db0488901e93df6ffff"),
            ],
        )
        self.assertEqual(native.TEXT_FILE_DELTA, 0x1000)
        self.assertEqual(
            native.NATIVE_SHA256,
            "f36c0ef83163bb3c7b99c5860ce98a5d4055dd6b69d3a4d393d7563e499d3456",
        )
        self.assertEqual(
            native.CANDIDATE_SHA256,
            "851b6cbe2a980344d09a1de58e451dc7a91116ea7bae5ef465abc1f5ee1799ad",
        )

    def test_ordinary_and_both_find_fallback_branches_remain_separate(self):
        edits = {address: after for address, _, after in native.EDITS}

        def destination(address, instruction):
            return address + len(instruction) + struct.unpack("<i", instruction[-4:])[0]

        self.assertEqual(destination(0xA325803, edits[0xA325803][:5]), 0xA325B11)
        self.assertEqual(destination(0xA325931, edits[0xA325931]), 0xA3261C1)
        self.assertEqual(destination(0xA325945, edits[0xA325945]), 0xA3261C1)
        self.assertEqual(destination(0xA325B17, edits[0xA325B11][6:11]), 0xA32585F)
        self.assertEqual(edits[0xA3261C1][:10], native.EDITS[0][1])
        self.assertEqual(destination(0xA3261CB, edits[0xA3261C1][10:]), 0xA32580D)

    def test_copy_changes_only_reviewed_bytes_and_leaves_baseline_untouched(self):
        baseline = bytearray(b"abcdefgh")
        with (
            mock.patch.object(
                native, "NATIVE_SHA256", hashlib.sha256(baseline).hexdigest()
            ),
            mock.patch.object(
                native, "EDITS", ((0x1001, b"bc", b"BC"), (0x1005, b"fg", b"FG"))
            ),
        ):
            self.assertEqual(native.patch_native_bytes(baseline), b"aBCdeFGh")
        self.assertEqual(baseline, b"abcdefgh")

    def test_different_or_already_modified_executable_is_rejected(self):
        for value in (b"different ELF", b"already corrected ELF"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.patch_native_bytes(value)

    def test_all_sites_validated_before_any_copy_edits(self):
        baseline = bytearray(b"abcdefgh")
        invalid = (
            ((0x1001, b"bc", b"BC"), (0x1005, b"XX", b"FG")),
            ((0x1001, b"bc", b"BC"), (0x1002, b"cd", b"CD")),
            ((0x1001, b"bc", b"B"),),
            ((0x0FFF, b"a", b"A"),),
        )
        for edits in invalid:
            with (
                self.subTest(edits=edits),
                mock.patch.object(
                    native, "NATIVE_SHA256", hashlib.sha256(baseline).hexdigest()
                ),
                mock.patch.object(native, "EDITS", edits),
                self.assertRaises(ValueError),
            ):
                native.patch_native_bytes(baseline)
            self.assertEqual(baseline, b"abcdefgh")


class NativePathTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name).resolve()
        self.output, self.original = root / "output", root / "original"
        self.original.mkdir()
        (self.output / "code").mkdir(parents=True)
        self.private = self.output / "code/code"
        (self.original / "code").write_bytes(b"original")
        self.private.write_bytes(b"candidate")
        self.metadata = {
            "original_root": str(self.original),
            "private_binary": str(self.private),
        }

    def test_independent_private_copy_is_required(self):
        self.assertEqual(
            native.native_paths(self.output, self.metadata),
            (self.original / "code", self.private),
        )
        self.metadata["private_binary"] = str(self.original / "code")
        with self.assertRaises(ValueError):
            native.native_paths(self.output, self.metadata)

    def test_hard_link_cannot_reach_original(self):
        self.private.unlink()
        os.link(self.original / "code", self.private)
        with self.assertRaises(ValueError):
            native.native_paths(self.output, self.metadata)
        self.assertEqual((self.original / "code").read_bytes(), b"original")

    def test_another_hard_link_to_private_copy_is_also_rejected(self):
        os.link(self.private, self.output / "alias")
        with self.assertRaises(ValueError):
            native.native_paths(self.output, self.metadata)

    def test_symlink_target_is_rejected_before_read_or_write(self):
        with (
            mock.patch.object(Path, "is_symlink", return_value=True),
            self.assertRaises(ValueError),
        ):
            native.native_paths(self.output, self.metadata)
        self.assertEqual(self.private.read_bytes(), b"candidate")

    def test_different_independent_executable_outside_output_is_rejected(self):
        outside = self.original / "other-code"
        outside.write_bytes(b"candidate")
        self.metadata["private_binary"] = str(outside)
        with self.assertRaises(ValueError):
            native.native_paths(self.output, self.metadata)

    def test_changed_original_after_run_prevents_success_and_records_evidence(self):
        args = argparse.Namespace(code_root=self.original)

        def run():
            native.experiment.prepare(args)
            return 0

        with (
            mock.patch.object(native.sys, "argv", ["native", "--execute"]),
            mock.patch.object(
                native, "prepare_native", return_value=(self.output, self.metadata)
            ),
            mock.patch.object(native.experiment, "main", side_effect=run),
            mock.patch.object(native.experiment, "digest", return_value="changed"),
        ):
            self.assertEqual(native.main(), 1)
        self.assertFalse(
            json.loads((self.output / "native-integrity.json").read_text())[
                "installed_native_unchanged"
            ]
        )

    def test_unowned_private_copy_is_rejected(self):
        with (
            mock.patch.object(
                native.os,
                "getuid",
                return_value=self.private.stat().st_uid + 1,
                create=True,
            ),
            self.assertRaises(ValueError),
        ):
            native.native_paths(self.output, self.metadata)

    def test_changed_private_or_original_hash_is_rejected(self):
        self.metadata["native_candidate_sha256"] = native.CANDIDATE_SHA256
        for digests in (
            (native.NATIVE_SHA256, "changed"),
            ("changed", native.CANDIDATE_SHA256),
        ):
            with (
                self.subTest(digests=digests),
                mock.patch.object(native.experiment, "digest", side_effect=digests),
                self.assertRaises(ValueError),
            ):
                native.verify_native(self.output, self.metadata)

    def test_unsupported_original_is_rejected_before_copying(self):
        prepare = mock.Mock()
        args = argparse.Namespace(code_root=self.original)
        with self.assertRaises(ValueError):
            native.prepare_native(args, prepare, False)
        prepare.assert_not_called()


class NativeRunnerTests(unittest.TestCase):
    def test_default_strict_runner_preserves_failure_exit_codes(self):
        for code in (1, 2):
            with (
                self.subTest(code=code),
                mock.patch.object(native.sys, "argv", ["native", "--execute"]),
                mock.patch.object(native.experiment, "main", return_value=code),
            ):
                self.assertEqual(native.main(), code)

    def test_diagnostic_flag_is_removed_and_children_use_this_runner(self):
        original_file = native.probe.__file__

        def run():
            self.assertNotIn("--selection-probe", native.sys.argv)
            self.assertEqual(native.probe.__file__, native.__file__)
            return 2

        with (
            mock.patch.object(
                native.sys, "argv", ["native", "--execute", "--selection-probe"]
            ),
            mock.patch.object(native.probe, "main", side_effect=run),
        ):
            self.assertEqual(native.main(), 2)
        self.assertEqual(native.probe.__file__, original_file)

    def test_inner_child_recovers_diagnostic_mode_and_verifies_native_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "metadata.json").write_text(
                json.dumps({"native_selection_probe": True})
            )
            args = argparse.Namespace(output=output)
            original = mock.Mock(return_value=1)
            with (
                mock.patch.object(
                    native.sys, "argv", ["native", "--inner", "--output", str(output)]
                ),
                mock.patch.object(native.probe, "run_inner", original),
                mock.patch.object(native, "verify_native") as verify,
                mock.patch.object(
                    native.probe,
                    "main",
                    side_effect=lambda: native.probe.run_inner(args),
                ),
            ):
                self.assertEqual(native.main(), 1)
            original.assert_called_once_with(args)
            self.assertEqual(verify.call_count, 2)


if __name__ == "__main__":
    unittest.main()
