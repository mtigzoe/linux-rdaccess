# Chromium and VS Code production-readiness follow-up — 2026-10-15

This branch starts at `origin/main` commit `7b0f959`, which merged PR #92.
The source coordinate review supports the Chromium selection correction, and
the expanded automated evidence advances its validation. It does **not**
establish a source-built Chromium/Electron application or production readiness.
The candidate remains unsubmitted; installed VS Code still contains the
upstream defects.

Read the separate results:

- [Chromium source validation and build feasibility](compatibility-audit-2026-10-15-chromium-source-validation.md).
- [Fresh native Unicode integration](compatibility-audit-2026-10-15-native-unicode-production.md).
- [Windows NVDA and Eurobraille b.note 80 acceptance procedure](accessibility-acceptance-vscode-unicode.md).

Fresh native strict fixtures with three distinct supplementary characters and
multiline Unicode passed routing, readback, Left/Right, semantic selection,
clipboard editing and focus restoration. The extended keyboard matrix exposed
both improvement and a remaining limit: the unchanged-native baseline passed
4/16 selection samples, while the candidate passed 16/16 in one run, failed
15/16 in another because AT-SPI reported no selection, and passed 16/16 in a
later instrumented run. All six synchronized routing sequences passed in the
last two runs; an earlier run without the existing readback synchronization
timed out at later multiline routing. These failures are retained, not
declared fixed. Actual Electron find-in-page passed 14/14 on each runtime for
the new distinct/multiline fixtures. The native report records each run and
the distinction between first-snapshot assertions and later diagnostic reads.

## Source validation and CI

The provider's ordinary selection path already returns Unicode code-point
offsets. Find-in-page retains UTF-16 offsets. Converting only that fallback
preserves the correct boundary: UTF-16 inside Chromium, code points at ATK and
the semantic bridge. Combining marks count separately; braille cells and
grapheme clusters are different coordinates.

The pinned original and candidate method bodies now run through 25 source
cases. Original: **13 pass / 12 fail, exit 1**. Candidate: **25 pass / 0 fail,
exit 0**. The verifier checks each case identity, expected/observed extent,
selected-text comparison and child exit. Aggregate counts alone cannot hide a
different failure. Six focused regression tests verify the evidence gate.

The complete diff applies to both pinned upstream files. Five proposed gtests
cover ASCII/BMP/combining text, emoji, multiple supplementary characters,
multiline, partial/reverse selection and find-in-page. **These gtests were not
compiled or run.** The real `//ui/accessibility:accessibility_unittests` target
depends on substantial generated/base/Mojo/Skia/gfx infrastructure. The Mint
host has ample disk but no checkout, supported compiler/build tools or required
development packages; 14 GiB RAM and 2 GiB swap constrain provisioning. A source
build is technically possible after provisioning, and remains outstanding.

The new [source-contract workflow](../.github/workflows/chromium-selection-contract.yml)
verifies the two source hashes, applies the entire patch, executes focused
regressions and retains both variants' evidence. Its job name explicitly says
it is **not upstream gtests**. The exact shell steps passed on Mint in
`/tmp/lrd-chromium-ci-shell-20261015-qpdmv7n3`. This is a local workflow-command
check, not an Actions result. The first local fixture was incomplete and
failed importing the root `remote_access` module; its logs remain under
`/tmp/lrd-chromium-ci-shell-20261015-7ipxz3yo`. Completing that fixture required
no workflow assertion or product change.

One initial GitHub inspection found the completed
[main GUI run](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38787265199)
at `7b0f959` successful, with **48 checks and one known #79 expected failure**:
Code readback 1 followed by Right=13. It did not prove Code's remaining checks.
The Windows companion and NVDA–Orca contract workflows were successful; Linux
diagnostics and the full unittest workflow were still running at inspection.
Their later results were not polled. Historical GTK failure/success evidence
from PR #92 remains in the [GTK investigation](compatibility-audit-2026-10-15-gtk-activation.md).
No new Actions result is claimed for this branch.

## Windows and protocol boundaries

Five new [cross-layer Unicode tests](../nvda-addon/tests/test_unicodeOffsets.py)
execute the actual Linux snapshot model, fragmented JSON decoder and Windows
companion TextInfo/routing hooks. BMP, distinct supplementary characters,
multiline and combining text retain code-point offsets; an out-of-range UTF-16
endpoint cannot be routed. An in-range defective provider endpoint remains
visible rather than being silently corrected. Provider and NVDA base/handler
are doubles; these tests do not run the complete NVDA presentation stack.

The complete companion suite passed **359 tests** on Windows with Python 3.13,
declared `configobj==5.0.9` and CI-pinned NVDA source
`1406f9f8a04eb50f7317af87aba3a9d439c2a772`. It does not operate installed NVDA.
The initial new-test fixture used an unsupported `a11y_caret` message type;
correcting it to the existing protocol's `a11y_text` made all five tests pass.
An initial full-suite attempt in the Python 3.14 environment lacked the
declared `configobj` dependency and failed importing it; its log is retained. Those
setup/fixture failures are not product defects or passing test results.

Six existing Linux braille/loopback modules passed **170 tests**, no errors,
failures or skips, under private Xvfb/D-Bus. The initial combined invocation
had a GI enum-registration setup error and a downstream empty-snapshot failure.
Preloading the real GI modules before the tests' module mocks corrected the
test invocation; no product assertion changed. Both logs are retained as
described in the acceptance procedure.

The [numeric evidence](production-validation-evidence-2026-10-15.json) records
these results, the retained failures and raw evidence paths. Public fixture
text is the only document content used. Read-only Orca inspection verified
installed `42.0-1ubuntu2`; no bridge behavior was changed.

## Remaining production and acceptance gates

The upstream source correction must be compiled/tested in the real dependency
chain and integrated into a shipped Chromium/Electron/VS Code application.
The separate VS Code editor-model synchronization correction also needs
upstream integration and complete regression coverage. Private binary edits
are experimental evidence only and must not become an installation mechanism.

Then verify live NVDA-origin input/control ownership, Windows speech, semantic
and raw braille paths, translation-aware routing/panning, focus/session
transitions and physical b.note 80 output/keys using the prepared procedure.
Software checks were performed independently; no operator was asked to repeat
an automated check and no physical-device acceptance is claimed.

GitHub initially showed issue #79 **closed**. It was reopened to follow the
explicit instruction to keep it open until production integration and
accessibility acceptance establish the correction. This work does not close
it. No active desktop, installed Code/Orca/NVDA/Remote Access configuration,
physical braille settings or user documents changed. No PR was merged.
