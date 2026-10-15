# Isolated follow-up for issue #79 — 2026-10-15

Issue [#79](https://github.com/mtigzoe/linux-rdaccess/issues/79) remains open.
This follow-up used the Windows repository and a separate Ubuntu WSL
environment. It did not SSH to `cyber.local`, access the active Mint desktop,
change installed applications/accessibility configuration, or use a physical
braille display.

## Root-cause review

The pinned Chromium `150.0.7871.250` correction is consistent with its
[provider source](https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc):
`GetSelectionExtents` converts ordinary UTF-16 extents into code-point offsets,
then `GetSelectionWithText` converts them again. The candidate moves conversion
into the find-in-page fallback, whose stored extents still use UTF-16. This
does not require a second conversion in linux-rdaccess.

The two pinned files were fetched independently into
`tmp/issue79-validation/pinned-source/`; SHA-256 matched:

| File | SHA-256 |
| --- | --- |
| `ax_platform_node_auralinux.cc` | `1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f` |
| `ax_platform_node_auralinux_unittest.cc` | `f18932d4de877d2074b541b4b77bfb9321e4292c5bf62df5a3d32c96481af540` |

The patch passed `git apply --check` and applied to a separate two-file copy.
This verifies source identity and patch application only. No full dependency
checkout, compiler invocation or upstream gtest execution occurred.

The earlier VS Code DOM/editor-model race is separate: a routed DOM caret can
read back as 1 while the editor still resumes keyboard movement at 12. The
retained sample with correct DOM selection/clipboard but zero AT-SPI selections
also remains unexplained. It passes through selection availability, outside
the changed conversion method. Publication timing is still a hypothesis for
that sample. No retry, delay, guessed offset or bridge workaround was added.

## Confirmed bridge defect

[PR #98](https://github.com/mtigzoe/linux-rdaccess/pull/98) fixes a separate
semantic-braille reconnect bug. Resynchronization withheld focus when its caret
was beyond the 8192-character snapshot window, then discarded the registry
needed to recognize the caret's return. The existing test accidentally
reinserted the object before each event and concealed the failure.

The fix retains that registry for focused caret observation and clears the
obsolete cached link snapshot. It rejects remote actions for the unpublished
neighborhood until focus is published. Regressions cover resumption exactly
once, subsequent text updates, unfocused/replaced sources and action blocking.
The resumption regression fails against the original method; the action test
also failed before its guard in both initial-focus and reconnect paths.

Final focused long-text/model/bounds/resync/event-gate/replay checks passed
**74 tests** on Windows Python 3.13 and Ubuntu WSL Python 3.10.12, with no skips.
Separate WSL bridge and braille-bridge modules passed **10 + 10 tests**.
Python compilation and whitespace checks passed. Two earlier root invocations
used nonexistent module names; their import errors remain in local logs and
are excluded from the pass counts. No bridge Ruff run was performed; a cached
Ruff invocation was subsequently available for the runner changes.

WSL package metadata reports Orca `42.0-1ubuntu2`, GI `3.42.1-0ubuntu1`, and
AT-SPI `2.44.0-3`. These are package/library and test-double checks, not a running
Orca session or evidence about the active Mint installation. No native Orca
command mapping was changed.

## Chromium build blocker

The isolated Ubuntu `22.04.5` environment reports 7.6 GiB RAM and 2 GiB swap.
`gn`, `autoninja`, Clang and g++ were absent from PATH; no `.gn` checkout was
found in the inspected `/tmp`, `/opt` or `/home` locations. Docker's Linux
engine was unavailable. No complete version-matched source checkout or build
directory was supplied.

WSL's filesystem advertises 952 GiB free virtual capacity, but its Ubuntu VHD
is backed by C:, which had **17,679,319,040 bytes (16.46 GiB)** physically free.
The [official Linux build instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md)
require at least 100 GB free storage and 8 GB RAM, recommending more than
16 GB RAM and substantially more swap on small systems. The virtual capacity
does not supply the missing physical storage. A full checkout/build was not
started on this host. No other isolated build host or larger CI runner was
provisioned in this session.

The next build needs a suitably provisioned isolated Linux host, a complete
pinned checkout with synchronized dependencies/toolchain and generated GN
output. Run `scripts/linux/run_chromium_selection_gtests.sh` there and retain
its source hashes, commit, build log, filtered inventory, XML and test log.
The runner review found that its old prefix excluded the proposed
`TestAtkTextFindInPageUnicodeOffsets`, and a zero-execution successful process
could escape detection. Its follow-up requires complete execution evidence;
synthetic orchestration tests do not supply compiled Chromium evidence.

The runner now includes find-in-page and existing selection regressions,
requires all five proposed tests plus every listed selected test in fresh
passing XML, clears inherited test settings and disables launcher retries.
The validator handles both direct GoogleTest XML and the pinned Chromium
launcher's XML, which omits the testcase `result` attribute. A successful exit
without complete XML cannot pass.

Its synthetic shell negative control against the original runner recorded
**11 failing assertions, zero errors** across five methods, including partial,
empty, skipped and stale results. The corrected Linux suite passed **11/11**;
Windows passed six report tests and explicitly skipped five Linux-only shell
tests. Scoped Ruff lint/format, shell syntax and whitespace checks passed.
PR #97's three Linux preflight tests also passed against the corrected runner,
loaded from its remote branch without changing or copying the source test file.
These fixtures deliberately stub source checks, Git, build tools and the test
binary; their results are not upstream gtest execution.

## Outstanding acceptance

Chromium compilation/upstream gtests, a source-built Electron/VS Code
integration containing both corrections, repeated strict native Unicode
selection/routing/keyboard continuation, live Windows NVDA speech and physical
braille acceptance remain **not performed**. The production upstream defects
and unexplained first-observation failure remain open. The bridge fix and
runner checks do not satisfy #79's closure criteria.

Local development evidence is under `tmp/issue79-validation/`, including
environment, hash, patch-check and focused test logs. These local files are
not a substitute for the eventual compiled build/test artifacts.
