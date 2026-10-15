#!/usr/bin/env python3
"""Test a pinned private compiled-method correction, without installing it.

This is an unsubmitted native binary experiment, not a Chromium source build.
The default runner retains strict routing/selection assertions. Pass
--selection-probe for separate diagnostic observations, not acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.diagnostics import vscode_selection_experiment as experiment
from tools.diagnostics import vscode_unicode_selection_probe as probe

NATIVE_SHA256 = "f36c0ef83163bb3c7b99c5860ce98a5d4055dd6b69d3a4d393d7563e499d3456"
CANDIDATE_SHA256 = "851b6cbe2a980344d09a1de58e451dc7a91116ea7bae5ef465abc1f5ee1799ad"
# Reviewed x86-64 Code 1.141.0 / Microsoft Electron 43.7.7 build 15553055.
# ELF Build ID: bbcca70c7e74fa871cca024670960f3720ccd016.
# ATK callback 0xa3290d0 tail-jumps to GetSelectionWithText at 0xa325790;
# its call at 0xa3257bb reaches GetSelectionExtents at 0xa3256b0.
# Ordinary extents are already code points: move r13d -> ecx, edx -> r12d,
# then join validation at 0xa32585f. Both find-in-page branches retain the
# original ten non-PC-relative bytes and conversions at 0xa32580d.
# The two caves are terminal INT3 alignment padding. Unwind metadata is not
# rebuilt, so asynchronous backtraces inside these call-free caves may differ.
TEXT_FILE_DELTA = 0x1000
EDITS = tuple(
    (address, bytes.fromhex(before), bytes.fromhex(after))
    for address, before, after in (
        (0xA325803, "4963c5488d4db0488901", "e9090300009090909090"),
        (0xA325931, "0f85ccfeffff", "0f858a080000"),
        (0xA325945, "e9b9feffff", "e977080000"),
        (0xA325B11, "cc" * 15, "4489e94189d4e943fdffff" + "cc" * 4),
        (0xA3261C1, "cc" * 15, "4963c5488d4db0488901e93df6ffff"),
    )
)


def patch_native_bytes(before):
    """Validate the entire original and every site before constructing a copy."""
    if hashlib.sha256(before).hexdigest() != NATIVE_SHA256:
        raise ValueError("Exact reviewed original native executable required")
    end = 0
    for address, expected, replacement in sorted(EDITS):
        offset = address - TEXT_FILE_DELTA
        if (
            offset < end
            or len(expected) != len(replacement)
            or before[offset : offset + len(expected)] != expected
        ):
            raise ValueError("Native sites differ, overlap or change instruction size")
        end = offset + len(expected)
    result = bytearray(before)
    for address, expected, replacement in EDITS:
        offset = address - TEXT_FILE_DELTA
        result[offset : offset + len(expected)] = replacement
    return bytes(result)


def native_paths(output, metadata):
    """Require the newly copied, owned, unlinked executable inside this output."""
    output = output.resolve()
    original = Path(metadata["original_root"]).resolve() / "code"
    private = Path(metadata["private_binary"])
    status = private.lstat()
    uid = os.getuid() if hasattr(os, "getuid") else status.st_uid
    if (
        private.is_symlink()
        or private.resolve() != output / "code/code"
        or original.is_relative_to(output)
        or output.is_relative_to(original.parent)
        or private.samefile(original)
        or status.st_nlink != 1
        or status.st_uid != uid
        or output.stat().st_uid != uid
    ):
        raise ValueError("Independent owned private native executable required")
    return original, private


def verify_native(output, metadata):
    original, private = native_paths(output, metadata)
    if (
        metadata["native_candidate_sha256"] != CANDIDATE_SHA256
        or experiment.digest(original) != NATIVE_SHA256
        or experiment.digest(private) != CANDIDATE_SHA256
    ):
        raise ValueError("Prepared native candidate or original executable changed")


def prepare_native(args, prepare, selection_probe):
    if experiment.digest(args.code_root.resolve() / "code") != NATIVE_SHA256:
        raise ValueError("Exact reviewed original native executable required")
    output, metadata = prepare(args)
    _original, private = native_paths(output, metadata)
    candidate = patch_native_bytes(private.read_bytes())
    if hashlib.sha256(candidate).hexdigest() != CANDIDATE_SHA256:
        raise ValueError("Native candidate differs from the verified experiment")
    private.write_bytes(candidate)
    metadata.update(
        native_original_sha256=NATIVE_SHA256,
        native_candidate_sha256=CANDIDATE_SHA256,
        native_experiment="compiled_method_bypass_not_source_build",
        native_selection_probe=selection_probe,
        native_edits=[
            {
                "virtual_address": hex(address),
                "file_offset": hex(address - TEXT_FILE_DELTA),
                "before": before.hex(),
                "after": after.hex(),
            }
            for address, before, after in EDITS
        ],
    )
    verify_native(output, metadata)
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return output, metadata


def main():
    # Only this wrapper consumes --selection-probe. Inner children recover the
    # selected runner from the prepared metadata, retaining their own __file__.
    options = argparse.ArgumentParser(add_help=False)
    options.add_argument("--selection-probe", action="store_true")
    options.add_argument("--inner", action="store_true")
    options.add_argument("--output", type=Path)
    known, _ = options.parse_known_args()
    selection_probe = known.selection_probe
    if known.inner:
        selection_probe = json.loads((known.output / "metadata.json").read_text())[
            "native_selection_probe"
        ]
    runner = probe if selection_probe else experiment
    original_prepare, original_inner = experiment.prepare, runner.run_inner
    original_file, original_argv = runner.__file__, sys.argv
    prepared = []

    def prepare(args):
        output, metadata = prepare_native(args, original_prepare, selection_probe)
        prepared.append((output, metadata))
        return output, metadata

    def inner(args):
        metadata = json.loads((args.output / "metadata.json").read_text())
        verify_native(args.output, metadata)
        try:
            return original_inner(args)
        finally:
            verify_native(args.output, metadata)

    experiment.prepare, runner.run_inner, runner.__file__ = prepare, inner, __file__
    sys.argv = [item for item in sys.argv if item != "--selection-probe"]
    unchanged = True
    try:
        code = runner.main()
    finally:
        experiment.prepare, runner.run_inner = original_prepare, original_inner
        runner.__file__, sys.argv = original_file, original_argv
        for output, metadata in prepared:
            unchanged = (
                experiment.digest(Path(metadata["original_root"]) / "code")
                == NATIVE_SHA256
            )
            integrity = {"installed_native_unchanged": unchanged}
            (output / "native-integrity.json").write_text(
                json.dumps(integrity, indent=2)
            )
    return code if code or unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
