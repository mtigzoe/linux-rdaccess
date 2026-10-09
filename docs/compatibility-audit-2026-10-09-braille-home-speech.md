# Braille return-to-focus speech audit — 2026-10-09

## Confirmed defect

Orca 42's native braille dispatcher stops speech before processing a home key.
The key calls `goBrailleHome`, which returns the braille display to its focused
region or exits flat review. The bridge handled NVDA Remote's `braille_toFocus`
by calling that script method directly, bypassing the dispatcher and its speech
interruption. Both the normal adapter and legacy fallback left speech running.

This could also let an already queued Say All END start the next utterance.
The existing routing interruption path did not cover the home command.

The nine new unit methods were run against the original controller and adapter
from main commit `e65b8a9` (controller v110). Six assertions failed across
their subtests, with no errors or skips. Frozen, unmodified native methods
establish the dispatcher interruption order, speech-exempt braille commands,
home behavior and focus return. Their ASTs match the installed Orca 42 methods.

## Fix

Add an optional callback to the adapter's return-to-focus command. Invoke it
only after finding a callable native handler, and run it through the existing
main-loop, session, display and focus checks. The legacy fallback follows the
same order. Unsupported or stale home commands do not stop current speech.

Share the speech interruption helper with routing. Stop local speech and send
NVDA Remote's cancel, then run the native home command. The existing stop
wrapper blocks further Say All utterances and completion callbacks. Home keeps
native CANCEL's caret placement at the last spoken word; only explicit routing
invalidates that caret callback. This covers normal focus return and leaving
flat review. A handler returning False is not retried. Panning still keeps
speech running, and an old cancellation cannot stop a new Say All run.

The generated controller advances from v110 to v111, with v110 upgrade support.
The existing Say All interruption epoch and protocol are reused. Root-level
Python compatibility wrappers are unchanged.

## Focused validation

| Coverage | Result |
| --- | --- |
| Braille contract matrix, including nine new home regressions | 48 tests passed |
| TCP protocol contract matrix, including home cancellation and master departure | 28 tests passed |
| Speech/focus contract matrix | 10 tests passed |
| Orca adapter, upgrades, patch integrity and direct commands | 101 tests passed |
| Say All callbacks and isolated installed CLI | 27 tests passed |
| Selected legacy home, pan and routing tests | 3 tests passed |

These are 217 distinct focused tests with no final failures or skips. The new
regressions use existing test modules already selected by the Actions matrix;
no matrix inventory changes are needed. The two added protocol tests exercise
actual loopback TCP framing with a simulated Orca runtime.

A disposable upgrade generated genuine v110 output with the pinned base, then
upgraded it to v111. Current patch validation, original backup contents, mode
0600, idempotence, generated/changed Python compilation, Python 3.10 grammar,
native fixture AST comparisons and whitespace checks passed. During review,
the cancellation guard was narrowed to preserve native home caret placement.
The new loopback test initially failed that check because its controller
session stamp and native last-input state needed initialization; the corrected
fixture and complete protocol contract pass.

## Limits

Live Windows NVDA, audible speech, physical braille, Linux application acceptance,
Xvfb and full repository discovery were not run. Native method bodies execute
with simulated module globals and accessible objects; these tests do not prove
physical display behavior or speech timing on a real desktop.

Existing installations need the normal connect/update flow and an Orca restart
to load the updated controller and adapter. No real user configuration was
changed. GitHub Actions were not monitored or awaited, and the PR was not merged.
