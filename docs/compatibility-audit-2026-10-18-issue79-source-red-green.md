# Issue #79: Chromium source-built ATK red/green checkpoint

**Captured October 17, 2026 ET / October 18 UTC. Issue #79 is open.**

This checkpoint consolidates evidence from the *actual Chromium accessibility C++ sources* and a source-linked unit-test executable. It supersedes the smaller October 16 compiled-text inventory in [the earlier checkpoint](compatibility-audit-2026-10-17-sourcebuilt-checkpoint.md), **not** its separate Electron/Code build status.

The two independent upstream defects remain:

1. **Chromium ATK:** `GetSelectionExtents` produces Unicode code-point offsets; `GetSelectionWithText` incorrectly converts ordinary selections again as though they were UTF-16 offsets. The proposed change converts only the find-in-page fallback that actually stores UTF-16 positions.
2. **VS Code:** native screen-reader content accepts an external system caret without consistently synchronizing the editor model. [Upstream VS Code draft PR #342341](https://github.com/microsoft/vscode/pull/342341), head `08c2137f0a74c01bd1952f09a283e827512194f1`, tracks the last handled DOM selection independently, including a 13 → 1 → 13 event sequence without render.

## Full Chromium source-linked red/green result

Both executables were compiled against **Chromium 150** pinned source/toolchain `f916f1b7136907af19d96b95b891533d091d932a` and linked from GN/Siso's actual `accessibility_unittests` graph. The regression-test object and all 1,343 executed test cases were **identical** in both executables. Comparison of **8,585 linker inputs** confirmed that the **only changed link input** was the private ATK production archive.

| Full enabled `accessibility_unittests` | Original Chromium ATK source | Corrected Chromium ATK source |
| --- | ---: | ---: |
| Pass | **1,340 / 1,343** | **1,343 / 1,343** |
| Assertion failures | 3 | 0 |
| Test process errors | 0 | 0 |
| Existing disabled tests (not executed) | 6 | 6 |
| Executable SHA-256 | `ab58fb9b473fae0b5f4901c8ca9eeb2ed7a8417d9fa5a1bc615a2da5af977a88` | `5c24d3f97bd020d02ac8ee476827529e29014180e5bc7c81e6c1427eac525413` |

The three baseline failures, and **only** those failures, were `AXPlatformNodeAuraLinuxTest.TestAtkTextGetSelectionUnicodeOffsets`, `TestAtkTextGetSelectionTwoSupplementaryChars`, and `TestAtkTextGetSelectionMultilineUnicodeOffsets`. They respectively included an original end-offset shortfall of **13 → 12**, **14 → 12**, and **13 → 11**. These failures also truncated selected text. Every one passed with the corrected production object.

The **same formatted new test object**, SHA-256 `a5405a1a24b131c37b89d2b0e9ba1cbe26476cabe0e05a952602d40d7660a861`, was used for original and corrected builds. Exact local Chromium Gerrit **draft commit**: `12f03354b62379f78dc76ddca4b8771a80c71dc0`, branch `issue79/atk-unicode-selection-gerrit-draft`. This is a local commit, **not** a submitted Chromium CL.

### How the private source build was isolated

The compilation used the original Chromium 150 Clang flags and generated dependency graph, but sent the `.o`, `.d`, private 40-member thin archive, response file, and new executable to dedicated evidence directories. Neither the original source build outputs nor the installed VS Code/Chromium executable was replaced.

Both newly linked test executables needed **hash-verified private copies** of the pinned `icudtl.dat` and `snapshot_blob.bin` beside them. An initial full corrected test run produced ten V8 startup errors because the private snapshot was missing. After copying the matching snapshot, the **unmodified full test command** passed 1,343/1,343. The earlier startup-error log was preserved, not hidden.

Both source-linked full test processes used the existing resource limits (two CPUs, 3 GiB memory soft / 4 GiB hard, low priority). **Task swap peak: zero** for both. No active XFCE desktop, Orca, NVDA Remote Access, physical braille device, system swap setting, installed program, or Electron recovery controller was changed.

Private Cyber evidence:

- Original source and test executable: `/home/miriam/chromium/issue79-compiled-20261016-a/unpatched-vs-formatted-20261018/`
- Corrected source and test executable: `/home/miriam/chromium/issue79-compiled-20261016-a/formatted-source-compile-20261017/`
- Verified two-run comparison: `unpatched-vs-formatted-20261018/controlled-1343-red-green-evidence.json`
- Full control and corrected result files: `baseline-full-accessibility-unittests.xml` and `latest-draft-full-accessibility-unittests-with-v8-20261017.xml`, respectively.

The private paths document provenance but are **not** publicly downloadable artifacts. See the public [issue #79 evidence comment](https://github.com/mtigzoe/linux-rdaccess/issues/79#issuecomment-6244609262) for a concise review record.

## Separate VS Code and combined-application evidence

The VS Code upstream editor fix `08c2137f` passed **22/22** in each of five fresh Chromium browser-test sessions (**110/110 executions**), **135/135 surrounding editor tests**, scoped TypeScript and ESLint. A *same-test* replay with the original editor code passed 21/22, failing only the newly added 13 → 1 → 13 regression; with current editor code it passed 22/22.

For a **private copy of prebuilt VS Code 1.141.0**, ASCII and BMP native caret routing failed at `caret_readback` without the editor fix, while the corrected editor code passed **4/4 ASCII** and **4/4 BMP** sessions. With the corrected editor alone, supplementary/multiline Unicode caret movement worked, but the Chromium provider failed at semantic selection.

A **separate, experimental, hash-pinned native Chromium instruction-bypass** (in disposable prebuilt executable copies only) together with corrected VS Code editor methods passed **8/8 complete application-level tests** across five fixtures. Keeping the exact editor bundle identical, the uncorrected versus experimental-corrected Chromium provider passed **4/16 versus 16/16** semantic selections, with **6/6** routing sequences passing on each side.

**These are diagnostic native-binary experiments, not source-built production Electron/Code, and the experimental instruction patch must not be shipped.** Physical Windows NVDA/braille was not tested.

## Fresh Chromium main compatibility: source-only

The formatted local C++ patch applies with **zero fuzz and no rejected hunks** to public Chromium `main` Gitiles revision `f05e8113fd96ea8c88375389c280a9250bbcdbc7`, reported October 18 UTC, and its touched regions pass Chromium `clang-format` v21. The port is private at `/home/miriam/chromium/issue79-compiled-20261016-a/current-main-compat-20261017-f05e/`.

**This is not current-main compiled validation.** Attempts to compile newer `main` production sources with pinned Chromium 150 headers failed on newer base-class APIs, including `SetDocumentTextSelections` and `AtkTextSelectionCompat`. Overlaying the matching header exposed additional newer dependencies. A valid current-main build requires a self-consistent current Chromium checkout, generated headers, and toolchain; do not claim those mixed-version errors are defects in this patch.

## Remaining acceptance gates

- **Chromium upstream:** Contributor-owned Gerrit identity, appropriate CLA and authorized public `AUTHORS` entry; then rebase, build and run presubmit on complete current Chromium main, upload for review, and address maintainers. No contributor agreement was accepted or CL uploaded on the user's behalf.
- **Electron/Code:** The existing Electron 43.7.7 source-build recovery controller is alive but waiting for its **12 GiB `MemAvailable` startup gate**. Do not lower the reserve, change swap, interrupt unrelated processes, or modify the active accessibility desktop. Complete the full source-built baseline and a source-built corrected comparison.
- **Live NVDA/braille:** Follow [VS Code Unicode accessibility acceptance](accessibility-acceptance-vscode-unicode.md) in an explicitly authorized, disposable session, recording semantic versus raw mode and actual physical routing/tactile output. Do not infer device acceptance from simulated tests.
- **VS Code upstream:** [PR #342341](https://github.com/microsoft/vscode/pull/342341) remains draft pending contributor CLA, review thread resolution, workflow authorization, and maintainer approvals.

**Do not merge the upstream changes or close [issue #79](https://github.com/mtigzoe/linux-rdaccess/issues/79) based solely on this checkpoint.**
