# VS Code selection synchronization candidate — 2026-10-14

Issue [#79](https://github.com/mtigzoe/linux-rdaccess/issues/79) remains open.
There is now a reproducible upstream correction candidate, with **12 fresh
ASCII sessions, one multiline session and one final harness ASCII check passing**.
It has not been submitted upstream, installed in production, or accepted through
real NVDA/physical braille testing. Unicode checks failed and are preserved.

## Established defect and correction

The [previous native trace](vscode-caret-render-trace-2026-10-13.json) captured
the DOM caret moving to 1 while the editor model remained at 12, followed by an
unchanged render writing 12 back before `selectionchange` reached the model.
The relevant installed-revision
[SimpleScreenReaderContent source](https://raw.githubusercontent.com/microsoft/vscode/2a59476c9bfcb90b3ddc372c36762471b7dfad1c/src/vs/editor/browser/controller/editContext/native/screenReaderContentSimple.ts)
also drops selection events within 100ms of its own writes and events arriving
within 5ms of the previous event. These time windows cannot distinguish an
external system-caret request from a renderer-owned write.

The [candidate patch](upstream/vscode-selection-sync.diff) leaves the DOM
selection alone when the rendered value, model selection and page mapping have
not changed. Its listener ignores selections equal to the rendered model state
instead of filtering by time. Focus return clears the cache so the next render
restores the model selection. The cut/paste interface hooks remain without the
old suppression windows. Source attribution and [reproduction instructions](upstream/README.md)
accompany the patch.

This corrects the captured native EditContext path in the tested private copies.
It does not establish that every VS Code/Chromium/AT-SPI caret failure has the
same cause. The legacy textarea path is unchanged. The bridge's provider setter,
Orca controller, Windows companion and application settings are unchanged.

## Stronger assertion

AT-SPI readback 1 can be a false positive. In the final **unmodified** private
Code copy, the setter was accepted and readback reached 1, but the next Right
key produced **13**, proving that the editor model had remained at 12.
The test failed after the existing 18-second wait.

The normal GUI runner now requires Right to produce 2 and Left to return to 1
after the VS Code route. It stops on failure without another route or extra
navigation. Other application checks keep their existing behavior. Two focused
unit regressions distinguish synchronized model/visible caret 1→2→1 from a
visible-only caret 1 whose stale model produces 13.

## Tests and native evidence

Environment: Linux Mint 21.3, system Python 3.10.12, AT-SPI 2.44, installed Orca
42.0, Code 1.141.0 revision `2a59476c9bfcb90b3ddc372c36762471b7dfad1c`.
The experiment does not load Orca or Windows NVDA. It uses the existing verified
private Xvfb/D-Bus runner, independent Code copies and fresh profiles/extensions.
Code's bundled Node 24.21.0 and TypeScript 6.0.3 transpile the actual source.

| Experiment | Result |
| --- | --- |
| Original TypeScript, isolated dependencies | 13 cases: 7 passed, 6 assertion failures, 0 errors/skips. |
| Patched TypeScript, same contract | 13 passed, 0 failures/errors/skips. |
| Unmodified native copy, initial probe | Accepted route 1; stayed 12 for the full 18-second readback wait. |
| Render-only correction, native probe | Readback 1, then Right 13; failed. |
| Listener-only correction, native probe | Stayed 12 for the full readback wait; failed. |
| Both diagnostic corrections | Three fresh sessions passed 1→2→1. Exploratory, counted separately. |
| Actual transpiled candidate methods, initial probe | Three fresh sessions passed 1→2→1. Exploratory, counted separately. |
| Final portable harness, unmodified copy | Readback 1, then Right 13; nonzero failure. |
| Candidate, 12 fresh ASCII sessions | All passed one route, 1→2→1, selection, clipboard paste/undo/cut/restore and focus-return navigation. |
| Candidate, one multiline session | Same checks passed; before-route caret 18. |
| Candidate, final formatted harness with numeric cleanup diagnostics | One fresh ASCII session passed the same checks. |
| Candidate, Unicode fixture `a🙂 café omega` | First run passed route/Right/Left, then failed semantic-selection validation. Two later sessions failed fixture text entry before any route; the final provider exposed 12 characters instead of the expected 13. All three exited nonzero. Unicode input/selection remains unresolved; no Unicode acceptance claim. |

The [sanitized numeric reports](vscode-selection-sync-evidence-2026-10-14.json)
preserve final native pass/fail states, request counts, timestamps and hashes.
Raw private logs remain under
`$HOME/.local/state/linux-rdaccess/vscode-79-20261014-qfs9wmnl`, using the
report's experiment and per-run evidence directory names. Times are UTC; some
fall on October 15 UTC, still October 14 in America/New_York.

Each native session sends **one** AT-SPI setter request. Polling the provider is
read-only; there are no repeated setters or quiet-period workarounds. Later
clipboard/selection tests deliberately move the caret, so a final cleanup caret
of 13 (ASCII) or 19 (multiline) is not a routing reversion. The separate
`readback`, `after_right` and `after_left` fields are the routing assertions.

The exact patched TypeScript SHA256 is
`44c80a27526793cd43cb518e33c9fa14d7f061479100b7ce713c063f37f72ad9`.
`git apply --check`, clean application to the pinned source and byte comparison
with that tested source passed. The reviewed installed bundle SHA256 is
`631c1d79c4f3af9177ca23a70cfe0cf2586a692678bd897af6c869324160d905`;
all final reports verify it remained unchanged. The private patched bundle SHA256
is `02f7853f04a4fad8796e5710fc87044e046e68f1dc84e51e17a2cddba8883b83`.

The portable harness transpiles five changed methods from the supplied source,
maps their three reviewed bundled import aliases and replaces only those methods
in its independent copy. The old, now-unused bundled timestamp field/helper
remain in that experimental binary. This is not a complete upstream build.
It rejects a different installed bundle hash, a reused output directory, an
unknown import alias or an invalid generated bundle before GUI input.

Local harness development failures are also retained: two early extraction
attempts failed the syntax gate before Code launched (no route); the extractor
was corrected and gained a regression for method calls versus declarations.
An early clipboard-cut assertion expected a literal empty string, while Code
exposes an empty document as a newline with caret 0; the fixture expectation was
corrected before the 12-run series. These failures are not counted as passes or
as evidence that the source candidate fixed an unrelated defect.

Validation of repository changes:

- Linux/WSL: 14 focused diagnostic unit tests passed.
- Windows Python 3.13: the three new regression tests passed. The whole GUI
  diagnostic module retains Linux-only filesystem assumptions.
- Scoped Ruff critical-error check and Python compilation passed; the two new
  Python files also pass full Ruff and formatting checks.
- Candidate and original source contracts executed through the actual bundled
  compiler/runtime as described above; native generated bundles passed Node's
  syntax gate before launch.
- `git diff --check` passed. The patch artifact's attribute preserves literal
  unified-diff context whitespace; source-code whitespace checks remain enabled.
  No GitHub Actions run was polled or awaited.

## Remaining acceptance

The source contract stubs DOM, services and view dependencies. Its IME-disabled
case checks a guard, not real composition input. Full VS Code compilation,
typechecking, lint and upstream test suites were **not run**. CRLF, large paged
documents, real IME/composition, Unicode selection/input and the legacy textarea
path need further investigation. The 12 ASCII samples reduce uncertainty about
the captured race but cannot prove every timing sequence safe.

The installed application still contains the original defect. Upstream review
and adoption (or a separately reviewed deployment) and real NVDA-origin/physical
braille routing acceptance are required before closing #79. Issues #57, #59,
#60 and #72 receive no new live acceptance from these tests. The active desktop,
Orca, NVDA connection, installed add-ons, relay settings and user documents were
not changed. No installation, restart or live-test consent was requested.
