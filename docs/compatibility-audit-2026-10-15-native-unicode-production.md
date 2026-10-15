# Native Unicode production follow-up — 2026-10-15

The experimental native counterpart still improves Unicode selection offsets,
but these results do **not** establish production readiness. A new strict run
also recorded one missing AT-SPI selection despite correct DOM selection and
clipboard contents. Both passing and failing evidence are retained. Issue
[#79](https://github.com/mtigzoe/linux-rdaccess/issues/79) must remain open.

This follows the [native investigation](compatibility-audit-2026-10-15-native-chromium-selection.md).
The [numeric evidence](native-unicode-production-evidence-2026-10-15.json)
records the individual observations, hashes, exit codes and final evidence-gate
results. Raw logs and independent private copies remain on `cyber.local` under
`/tmp/lrd-unicode-production-20261015-4wbkdpg4`.

## Environment and provenance

All GUI work ran through SSH to `miriam@cyber.local`, in fresh private Xvfb and
D-Bus sessions. Each profile, clipboard and application copy was disposable.
The active desktop, installed applications, accessibility connections and
physical devices were not changed or used. The private bus's screen-reader
status enables Chromium accessibility; these sessions do not run or validate
Orca, Windows NVDA or Remote Access.

The installed application remains Code **1.141.0**, Microsoft Electron 43.7.7
build 15553055, Chromium **150.0.7871.250**. Installed hashes still match:

| Artifact | SHA-256 |
| --- | --- |
| Installed native executable | `f36c0ef83163bb3c7b99c5860ce98a5d4055dd6b69d3a4d393d7563e499d3456` |
| Installed renderer bundle | `631c1d79c4f3af9177ca23a70cfe0cf2586a692678bd897af6c869324160d905` |
| Private native candidate | `851b6cbe2a980344d09a1de58e451dc7a91116ea7bae5ef465abc1f5ee1799ad` |
| Private renderer candidate | `02f7853f04a4fad8796e5710fc87044e046e68f1dc84e51e17a2cddba8883b83` |

The exact pinned VS Code TypeScript source was downloaded again at revision
`2a59476c9bfcb90b3ddc372c36762471b7dfad1c`, and the reviewed
`vscode-selection-sync.diff` applied to a new temporary tree. Its LF SHA-256 is
`b9f82337d145b955028e393bbe9f2829b0ede7432212213cc85b2d72500d3d09`;
converting those bytes to CRLF gives the earlier recorded
`44c80a27526793cd43cb518e33c9fa14d7f061479100b7ce713c063f37f72ad9`.
Both transpile to the same private renderer bundle hash above.

The guarded native experiment prepares independent owned copies and checks
the existing five reviewed binary edit sites and original/candidate hashes.
Its call-free trampolines remain an experimental counterpart to the Chromium
source change, not a source build or distributable fix. The renderer candidate
is also present in both matrix copies, isolating native selection conversion
from the separate editor caret synchronization defect. The unchanged native
baseline and experimental native candidate differ only in that reviewed native
correction.

## Additional native coverage

Two fixtures extend the earlier BMP, emoji, repeated-emoji and ASCII multiline
coverage:

- `distinct_astral`: `a🙂𝄞𐐷 café omega`, **15 code points / 18 UTF-16 units**.
  The supplementary characters are U+1F642, U+1D11E and U+10437.
- `multiline_astral`: `a🙂 café`, `b𝄞 omega`, `c𐐷 fin`, separated by newlines,
  **23 code points / 26 UTF-16 units**.

The keyboard matrix compares UTF-16 DOM offsets with independently expected
code-point AT-SPI and semantic offsets. Ctrl+Home/End span the entire multiline
fixture. It covers full and suffix selections in both directions, one
supplementary character, collapse at either end, all three supplementary
characters and the third alone. Selected-text clipboard checks use the private
display. DOM inspection through loopback CDP is read-only.

| Run | Exact selection observations | Routes | Exit |
| --- | --- | --- | --- |
| Fresh unchanged-native baseline | 4/16 | Not requested | 1 |
| Initial native candidate | 16/16 | Not requested | 0 |
| Early routing fixture, without provider readback synchronization | 16/16 | Incomplete; third-line Right timed out | 1 |
| Candidate using existing strict readback synchronization | 15/16 | 6/6 | 1 |
| Candidate with additional observation-only timing fields | 16/16 | 6/6 | 0 |

The 6-route checks request code-point offsets **1/2/3** in the first fixture
and **1/9/18** in the multiline fixture. Each sends one semantic provider caret
setter, uses the normal strict runner's existing readback wait, and verifies
immediate Right and Left continuation. DOM, provider and semantic caret values
must agree in their respective coordinate systems. No route is resent.
These exercise the Linux semantic routing operation used by the bridge;
they are not actual braille-cell or Windows Remote Access gestures.

Each new fixture also passed a separate fresh strict experiment: one route,
readback 1, Right=2/Left=1, full semantic selection, clipboard paste/undo/cut/
restore and command-palette focus return followed by keyboard continuation.
The cleanup report's null selection reflects a later collapsed selection;
the strict selection assertion has its own PASS log.

## Failures remain significant

The early routing fixture observed a changed DOM caret immediately after its
setter while the first provider read still reported the previous position.
It then sent keyboard input without the provider readback synchronization
already required by the normal strict test. Five completed routes had correct
Right/Left endpoints but stale immediate readbacks; the sixth timed out after
request 18 and Right. That historical run lacks the final DOM/text snapshot,
so its exact third-line failure mechanism is not established. The final runner
reuses the existing strict readback wait, retaining the immediate read as a
diagnostic. It does not extend the wait or repeat setters.

The later **15/16** run is a separate unresolved observation. For
`distinct_astral/one_character`, DOM selection was UTF-16 `[1,3]`, clipboard
contained the expected emoji and caret was code point 2. AT-SPI returned zero
selections and the semantic snapshot consequently had `[null,null]`, where
`[1,2]` was required. The strict result remains failed. This is not the earlier
stable double-conversion signature: no wrong nonempty endpoint was returned.
In the [pinned Chromium provider](https://github.com/chromium/chromium/blob/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc),
`GetNSelections` uses `HasSelection` and raw `GetSelectionOffsetsForAtk`;
that path does not execute the changed `GetSelectionWithText` conversion.
Count zero indicates absent, collapsed or invalid raw provider selection at
that read. Asynchronous provider availability is a possibility, not a proven
cause. Caret 2 was sampled after the clipboard action, so it does not establish
that selection was ready when its earlier count was read.

The last run adds one diagnostic provider read after the existing clipboard
action. The **first** selection observation still decides the strict result;
later data never repairs a failed sample. That run passed 16/16 and all 6
routes, but does not establish a correction for the preceding missing-selection
observation. There are no retry-until-pass loops, exception suppressions or
relaxed caret/selection assertions. No application correction was added for
this unresolved observation.

## Native find-in-page fallback

Fresh independent minimal Electron runtimes exercise actual
`webContents.findInPage`, including no-selection and clearing after each
query. The fixture uses `white-space:pre-wrap` so its multiline accessible
text preserves the public fixture's newlines. Multiline queries select the
first line, the second line, and its supplementary character; expected
selection endpoints include all preceding code points and newlines.

Both baseline and candidate passed **14/14** observations: 7 per fixture.
DOM selection stays empty, while actual fixture accessibility nodes expose
the find result. This establishes exercise of the native fallback rather
than ordinary renderer DOM selection. Native match counts and active result
ordinals are checked before observation. These new results support preservation
of the fallback path; they do not cover every browser search behavior.

## Regression checks and reproduction

The matrix and find probes now support opt-in
`--require-correct-selection`. Diagnostic completion by itself remains distinct
from acceptance. The strict gates require the exact fixture/case inventory,
reject missing/duplicated/mislabelled samples, require all selection/caret/
semantic checks and require successful copying for every nonempty selection.
With `--route-continuation`, all expected routes and all three observations
are required. Failed records keep nonzero exit codes.

Fifteen focused unit tests passed on Linux and Windows. They cover code-point
versus UTF-16 metrics, distinct supplementary fixtures, multiline offsets,
complete evidence inventories, clipboard evidence and native find fallback
observation requirements. Scoped Ruff, formatting, Python compilation and
whitespace checks passed. The final strict gates were also evaluated against
the saved native JSON reports: they accept the two fully correct candidate
reports and all four find reports, and reject the baseline and both failed
candidate reports.

After preparing the reviewed source and new private copies as described in
the [upstream README](upstream/README.md), use new output paths:

```sh
python3 tools/diagnostics/vscode_native_selection_experiment.py --execute --output /tmp/code-native-distinct --source "$TREE/$SOURCE" --case distinct_astral
python3 tools/diagnostics/vscode_native_selection_experiment.py --execute --output /tmp/code-native-multiline --source "$TREE/$SOURCE" --case multiline_astral
python3 tools/diagnostics/vscode_native_selection_matrix.py --binary /tmp/code-native-distinct/code/code --output /tmp/code-matrix-extended --extended --route-continuation --require-correct-selection
python3 tools/diagnostics/electron_native_find_probe.py --runtime /tmp/electron-find-candidate --output /tmp/find-distinct --fixture distinct_astral --require-correct-selection
python3 tools/diagnostics/electron_native_find_probe.py --runtime /tmp/electron-find-candidate --output /tmp/find-multiline --fixture multiline_astral --require-correct-selection
```

This native evidence does not replace compiling the complete Chromium/Electron
source candidate, running its upstream accessibility gtests, production
integration or live NVDA/Orca and physical braille acceptance. Installed Code
still contains both upstream defects. The unresolved missing-selection sample
and immediate-route timing evidence must be included in any upstream review.
