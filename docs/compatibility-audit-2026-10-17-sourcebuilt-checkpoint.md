# Issue #79: verified source-build checkpoint, October 17, 2026

**Issue #79 remains unresolved.** An authorized SSH inspection of Cyber at
21:39 UTC verified the preserved compiled Chromium results and found the
Electron baseline recovery waiting for memory. No compilation or native
application test was started during this inspection.

The [numeric checkpoint](sourcebuilt-checkpoint-evidence-2026-10-17.json)
records artifact hashes, exact test inventories, source revisions, dependency
checkpoints, configuration, controller state and harness staging. It is a
verification of preserved artifacts, not a new application run.

## Actual Electron state

The existing controller, PID 629572, was alive and waiting before
`electron-baseline-resume1-gn`. Its 21:39:16 UTC sample reported
**12,117,172 KiB available RAM (11.56 GiB)**, below the unchanged
**12,582,912 KiB (12 GiB)** startup requirement. Free swap was 760,572 KiB,
full memory-pressure avg10 was zero, and free disk was 1,247,870,476,288 bytes.
No readiness wait or additional controller was started in this pass.

The previous build stopped through its resource guard after **23,371 of
45,402 actions**, with exit -15 and a recorded memory/swap-pressure reason.
The preserved Ninja log and dependency database still match the recovery
preparation hashes. The preparation recorded **19,024 completed objects**.
Neither `electron` nor `dist.zip` exists in the output directory. Recovery
GN, its revised dry-run plan, baseline preservation and native cases have
not run. The earlier 22,031-action plan predates the approved generator
change; it is not a newly verified recovery plan.

Verified identities and configuration:

- Electron **v43.7.7**, commit `ddb762f50fbd70384d0385302697e60ada549024`.
- Chromium **150.0.7871.250**, base `f916f1b7136907af19d96b95b891533d091d932a`;
  Electron's official patch checkpoint is
  `289a05f36b7fdc2d529fc3258211336de2ab9849`. All 18 recorded official-patch
  dependency HEADs and checkpoint refs still match.
- Original ATK provider SHA-256:
  `1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f`.
  The neighboring original test source also matches its pin. The Chromium
  Unicode correction has **not** been applied to this Electron tree.
- GN imports `//electron/build/args/testing.gn`, disables symbols, ThinLTO
  and remote execution, sets one concurrent link and enables GLib. Its
  arguments hash remains
  `59b13a26616f6093f31c749197e5d6feaa7cca4c9753e4423c4d02449ebc9022`.
- Ninja **1.12.1** remains the backend. The approved Blink configuration
  uses the existing `--single_process` generator option. No backend switch,
  clean, dependency resync or rebuild was attempted.

The existing controller retains Ninja `-j1`, CPUs 14–15, low CPU/I/O priority,
6 GiB soft / 8 GiB hard build memory limits, the physical startup reserve,
swap/pressure/disk stop conditions and eight-hour build bound. It will
independently check startup resources for GN, plan, generator-command
inspection and build. Its eventual plan must reject recompilation of
completed C/C++ outputs. No policy was weakened, no unrelated process was
stopped, and system swap/settings and the active desktop were unchanged.

## Preserved compiled Chromium regression results

The original **October 16** runs built the real upstream
`accessibility_unittests` target at the Chromium base above. This inspection
verified **all 73 files** in the preserved compiled-evidence manifest,
recomputed both binary hashes, parsed all three XML reports, and matched
their complete executed/failing inventories to the original summaries.
No gtest was rerun here.

| Provider and scope | Passed | Failed | Test exit | Original XML |
| --- | ---: | ---: | ---: | --- |
| Original provider, tests added | 7 | 3 | 1 | [Baseline](upstream/evidence/2026-10-16-chromium-selection/baseline-selection-gtests.xml) |
| Corrected provider, same focused inventory | 10 | 0 | 0 | [Corrected](upstream/evidence/2026-10-16-chromium-selection/candidate-selection-gtests.xml) |
| Corrected provider, broader ATK text inventory | 16 | 0 | 0 | [Broader](upstream/evidence/2026-10-16-chromium-selection/candidate-atk-text-gtests.xml) |

No tests in these inventories were skipped. Original failures are
`TestAtkTextGetSelectionUnicodeOffsets`,
`TestAtkTextGetSelectionTwoSupplementaryChars`, and
`TestAtkTextGetSelectionMultilineUnicodeOffsets`, all in
`AXPlatformNodeAuraLinuxTest`. The preserved review attributes them to
offset/selected-text mismatches, not failed fixture setup or setters.

The preserved original binary hashes to
`66eee26314273bb3ad1ab9459f5df6e0be6001cdf53a0617931562e84f7f5482`;
the corrected binary hashes to
`d199bab39dd28ceec03b67ce551ae0534f1d3ba20b680113b34cefb2cc0c29d5`.
The patch hash is
`8b58fde3c6d6642caeea780f3f087832027172841cb9db49cee25ae2d27c531d`.
These are compiled upstream unit tests in private Xvfb/D-Bus, not a full
Chromium application build or source-built Electron/VS Code acceptance.

## Correcting the queued harness snapshot

The controller's existing wrapper points at
`/home/miriam/chromium/issue79-native-20261016-b`. Its experiment script
predated merged [PR #133](https://github.com/mtigzoe/linux-rdaccess/pull/133),
so future native failures would lack the requested stage diagnostics.

The original script was preserved under
`evidence/resume-review-20261017-b/vscode_selection_experiment.original.py`.
Only that private harness script was atomically replaced with the exact
merged Git blob `189541403a3bd1075195113f3f3665055926b022` from main
`c975491a0428207e43ea87b17e431d56f231fc1e` (LF SHA-256
`80b06a264701b7f47eb43e6d74f5c924137e4ed0f331375320f2e6f5d68a7456`).
The smoke helper, activation helper and TypeScript contract compiler match
current main, and the renderer candidate retains its existing source pin.
The controller, wrapper, monitor, source tree and fixture requirements
were unchanged.

The six current experiment unit tests ran against the old private snapshot
once: four test methods passed and two reported missing diagnostics,
including 13 failing subtests (14 unittest errors total), exit 1. The
staging precheck initially miscounted those reports as one failure and one
error and stopped before replacement; its script and log remain preserved.
After correcting that accounting without rerunning the control, staging
completed and **6/6 passed**, exit 0, against the updated private script.
These are unit tests with simulated fixture failures, not accessibility
acceptance runs. Local focused checks separately ran 23 tests: **18 passed,
5 Linux-only runner tests skipped** on Windows.

## Remaining application and upstream gates

The two confirmed mechanisms remain separate:

1. Chromium's ordinary selection extents are already code-point offsets,
   but `GetSelectionWithText` converts them from UTF-16 a second time. The
   existing small patch retains conversion only for find-in-page's UTF-16
   fallback; the compiled regressions above support that correction.
2. VS Code can expose caret 1 while its editor model remains at 12; an
   unchanged model render or subsequent Right key can undo routing. The
   renderer synchronization candidate requires independent application
   validation. The Chromium correction does not establish a fix for it.

When the existing resource requirements are satisfied, complete the same
incremental baseline and preserve its complete distribution, dependency
list, GN arguments and per-member hashes before applying any correction.
The queued baseline cases are original-renderer BMP control and candidate
renderer BMP, emoji, distinct supplementary-character and multiline
supplementary-character fixtures. Each runs once and preserves nonzero
results; prerequisite or renderer BMP control failures stop for inspection.
Only afterward should a corrected Electron distribution be built
incrementally and compared with the same strict cases.

Every routing case still requires correct fixture entry, AT-SPI caret 1,
Right 2 / Left 1, semantic Unicode selection, clipboard integrity and
focus return. PR #133 distinguishes those failure stages; no retry,
timeout extension or weaker assertion was introduced.

The private fixture combines source-built public Electron with the pinned
Code application bundle. A complete VS Code source dependency install,
build/typecheck/lint/upstream-suite run, real composition/IME and broader
mapping coverage remain outstanding. Both upstream candidates remain
unsubmitted. No production bridge/application behavior was changed.
Windows NVDA-origin input/speech and physical braille acceptance remain
explicitly outstanding under #59/#60. Keep #79 open.
