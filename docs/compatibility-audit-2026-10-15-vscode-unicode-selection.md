# VS Code CI classification and Unicode selection — 2026-10-15

Based on `origin/main` at `93c3818` (merged PR #91). Issue
[#79](https://github.com/mtigzoe/linux-rdaccess/issues/79) remains open.
This investigation used SSH to Linux Mint and private Xvfb/D-Bus sessions.
No installed application, active desktop, Orca, NVDA, Remote Access or physical
braille configuration was changed.

## CI failure: a newly installed version

The failed [Linux GUI run 38754047520](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38754047520)
at head `36fe846` installed Debian package **`1.142.0-1792035033`**.
The version command reported **Code 1.142.0**, revision
`6d62b1d5dace93a33b3a6d3eca1317bd5e15bcb1`, x64.
`LRD_EXPECT_VSCODE_79=1` was present. AT-SPI readback reached 1, but the
first Right key produced 13 instead of 2. The typed failure was:

```text
VS Code #79: accessibility caret readback 1; expected Right=2 but stale editor selection produced Right=13
```

The classifier only allowed versions **1.141.0 and 1.141.2**. It correctly
refused to suppress a failure on the previously unverified 1.142.0 release.
The fix permits **only the verified `right-13` signature on 1.142.0**.
Its other known signature, readback remaining at 12, has not been established
on 1.142.0 and stays fatal there. Opt-in is still required. Unknown versions,
unknown signatures, untyped assertion failures and unrelated failures stay
fatal. Existing 1.141.0/1.141.2 behavior is preserved. Caret assertions,
timeouts and setter counts are unchanged; no retries were added.

The already completed [main run 38754755864](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38754755864)
installed the same Code release and passed 53 actual checks, zero expected
failures and zero skips. A successful sample does not establish that this
intermittent upstream issue is corrected. Historical completed runs were
inspected for this task; no new CI run was polled or awaited.

## Unicode failure: Chromium converts selection offsets twice

Installed versions: Code 1.141.0 revision
`2a59476c9bfcb90b3ddc372c36762471b7dfad1c`, Electron 43.7.7,
Chromium 150.0.7871.250, AT-SPI 2.44.0, Orca package 42.0-1ubuntu2 and
Python 3.10.12. Orca was not loaded by these tests.

A selection-only diagnostic compared independent unmodified and experimentally
patched Code copies, each with a fresh profile, private display and private bus.
It pasted public fixtures through that display's clipboard, pressed Ctrl+A,
then read DOM selection through loopback CDP, raw AT-SPI selection and the
semantic payload. Ctrl+C verified that the editor selected the complete fixture.
No caret setter was used in this diagnostic.

Both copies produced the same results:

| Fixture | Code points / UTF-16 units | DOM selection end (UTF-16) | AT-SPI count / caret | AT-SPI / semantic selection end | Copied full fixture |
| --- | --- | --- | --- | --- | --- |
| `a café omega` | 12 / 12 | 12 | 12 / 12 | 12 / 12 | Yes |
| `a🙂 café omega` | 13 / 14 | 14 | 13 / 13 | 12 / 12 | Yes |
| `a🙂🙂 café omega` | 14 / 16 | 16 | 14 / 14 | 12 / 12 | Yes |

This rules out input loss and the experimental VS Code selection-sync patch as
the cause of the shortened selection. The semantic snapshot copies the valid
provider offsets unchanged; it does not perform a UTF-16 conversion. A bridge
workaround that stretches 12 to 13 would corrupt legitimate partial selections.

Electron's [v43.7.7 DEPS](https://github.com/electron/electron/blob/v43.7.7/DEPS)
pins the observed Chromium version. In that exact Chromium
[Linux accessibility provider source](https://github.com/chromium/chromium/blob/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc),
`GetSelectionExtents` converts UTF-16 offsets into Unicode character offsets.
`GetSelectionWithText` calls it and converts the returned offsets again.
That produces **14→13→12** with one emoji and **16→14→12** with two,
matching both native probes. The caret path converts once, explaining its
correct result. The source SHA256 is
`1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f`.
The Electron Chromium patch set was inspected and contained no patch to this
provider file. This is a Chromium ATK provider defect exposed through AT-SPI.

The [unsubmitted Chromium candidate](upstream/chromium-unicode-selection.diff)
removes the second ordinary-selection conversion while retaining conversion
for the find-in-page fallback, which still supplies UTF-16 offsets. It includes
upstream gtest cases for full, partial, emoji-only and reversed selections,
two supplementary characters and find-in-page. The candidate does not change
the VS Code synchronization patch or the bridge.

## Verification and limits

- Linux Python: 82 focused classifier, model, GI, experiment and probe tests passed
  across two focused invocations (77 + 5).
  New cases preserve raw provider selection ends 12 and 13 and reject an
  out-of-range 14; they do not manufacture a correction in the semantic layer.
- Actual pinned TypeScript source with isolated DOM/model dependencies:
  original **9 passed, 7 assertion failures**, zero errors/skips;
  selection-sync candidate **16 passed**, zero errors/skips. The added cases
  check Unicode UTF-16 rendering, conversion to model position and preservation
  of a pending external selection. This is not a full VS Code build.
- Fresh strict native BMP experiment: passed one route, readback 1,
  Right=2/Left=1, selection, clipboard paste/undo/cut/restore and focus return.
- Fresh strict native emoji experiment: entered all 13 code points / 14 UTF-16
  units; one route and Right=2/Left=1 passed; semantic selection timed out at
  `[0,12]` instead of `[0,13]` and exited **1**. No assertion was relaxed.
- Both selection-only probes completed and reproduced the mismatch. A zero
  diagnostic exit means observation completed, not Unicode acceptance.
- The reusable `vscode_unicode_selection_probe.py` was then run against fresh
  original and patched copies: both completed and reproduced all three fixture
  measurements, with `provider_full_selection=false` for both emoji fixtures.
- Pinned Chromium C++ method extraction contract, compiled with g++ 11.4.0
  and `-std=c++17 -Wall -Wextra -Werror`: original **4 passed, 5 failed**, exit 1;
  candidate **9 passed, 0 failed**, exit 0. Both actual method bodies are used;
  ATK, delegate and Unicode conversion dependencies are test doubles. Cases
  include partial/reversed/emoji-only selections, two emoji, find-in-page full
  and suffix selections and no selection. This is not a Chromium build or
  native ATK/AT-SPI validation of the correction.
- Chromium patch application was checked against the exact provider and test
  sources. Its upstream gtests were **not built or run**, and no native binary
  containing the Chromium candidate was tested. Full upstream builds,
  typechecking and suites remain outstanding.
- Scoped Ruff critical-error checks, Python compilation and whitespace checks
  passed. The new Python diagnostics and probe tests also pass full Ruff and
  formatting checks.

The [numeric evidence](vscode-unicode-selection-evidence-2026-10-15.json)
contains the CI version/signature, native stage measurements, strict exit
codes and hashes. Private raw logs are retained on `cyber.local` under
`/tmp/lrd-vscode-unicode-20261015-MXANAK`; they are temporary evidence, not
durable published artifacts. The installed Code bundle retained SHA256
`631c1d79c4f3af9177ca23a70cfe0cf2586a692678bd897af6c869324160d905`.
The experimental patched bundle retained SHA256
`02f7853f04a4fad8796e5710fc87044e046e68f1dc84e51e17a2cddba8883b83`.

No real Windows NVDA input, audible speech or physical braille was tested.
The upstream candidates are not deployed or submitted. Neither this diagnosis
nor the version-specific CI classification establishes correction and
acceptance of #79; it must remain open.
