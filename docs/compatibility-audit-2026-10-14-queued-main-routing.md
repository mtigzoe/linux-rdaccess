# Queued native document routing after focus or control changes

**Confirmed defect; fixed in review candidate 20261014.0.3, automated-tested
only.** A routing press accepted on Linux focus A could execute against focus B
or a replacement Windows braille handler. This is related to #59/#61 and queued
message behavior in #72. It does not establish the cause of the historical 6→9
movement or complete any physical acceptance issue.

## Reproduction and cause

Baseline: merged main `f247d77`. Source-backed regressions execute selected NVDA
methods from references `1406f9f8a04eb50f7317af87aba3a9d439c2a772` and NVDA
2026.2 `f62c980589d1ac30babf68ad48177e9ad29a2e84` with fake display/transport
providers. No installed NVDA session or physical key is needed.

The bridge's main-buffer routing path returned true to `decide_executeGesture`
and queued focus recovery. NVDA then queued its ordinary global routing script,
which reads the active braille handler/buffer at execution time. Recovery's
session/control checks did not cancel that separately queued native script.
Snapshot-bound TextInfo senders could not protect this path: the native script
could obtain a new sender from the replacement region.

Five initial regressions ran before the fix: **one valid-route control passed,
four regressions failed**, zero errors/skips. An old cell-9 press reached the
replacement focus, same-ID updated text, a new control generation, or a new
braille handler. The tests assert no native buffer routing and no outgoing
semantic input for stale presses. A fresh press on the replacement focus must
still send its requested caret offset.

## Correction

Bind a native document-routing gesture's `executeScript` hook to its original
handler, main buffer, semantic focus snapshot, session and control generation.
Validate those at execution before focus recovery and again before invoking the
original executor. A newer snapshot, control handoff, disconnect, new session,
termination, handler replacement or newly visible message invalidates the old
press. Every newer snapshot invalidates the pending press, including same-ID
text updates; a fresh press uses the current snapshot.

Keep `gesture.script` unchanged and let `InputManager.executeGesture` retain
speech effects, system-idle handling, input help, gesture capture and normal
script queuing. Tests execute native `InputManager.executeGesture`,
`InputGesture.executeScript`, `_queueScriptCallback`, global routing and braille
message/update methods with isolated dependencies. Both blocked and permitted
capture paths are checked. Existing guarded message routing is unchanged.

The pending-update fixture now enters the native gesture execution hook, as
real queued NVDA scripts do. A pre-existing empty-cell fixture assumed the newer
`cellIndexes` API and also failed against NVDA 2026.2's `routingIndex` script.
Its expectations now follow the selected native API, without skipping either
version or changing production legacy routing behavior.

## Validation

Groups overlap; do not add the full companion and release-reference counts.

| Check | Result | Scope |
| --- | --- | --- |
| Full companion, Windows/Python 3.13.13, NVDA reference `1406f9f` | 354 passed; 0 failures/errors/skips | Native-method harness plus real isolated Windows kernel IPC/DPAPI/DACL/cancellation |
| Message restoration and pending routing, NVDA 2026.2 reference `f62c980` | 61 passed; 0 failures/errors/skips | Selected native source methods; fake display/transport |
| Linux input, speech and braille lifecycle units, Mint/Python 3.10.12 | 299 passed; 0 failures/errors/skips | Private source checkout; automated dependencies |
| Six real Linux application fixtures | 48 checks passed | Private Xvfb/D-Bus; VS Code explicitly excluded and tested separately |
| VS Code 1.141.0 routing reproduction | FAIL | Accepted caret 1; stayed at 12 for 18.01064 seconds, focused, no target caret event |
| Ruff lint/format, package syntax/integrity/reproducibility, diff checks | PASS | No installation or runtime restart |

Companion commands from `nvda-addon` (env files contain only `NVDA_SOURCE_DIR`
pointing to the pinned references):

```text
rtk proxy uv run --no-project --python 3.13 --with configobj --env-file ../tmp/braille-routing-outcomes/ci.env python -B -m unittest discover -s tests -t .
rtk proxy uv run --no-project --python 3.13 --with configobj --env-file ../tmp/braille-routing-outcomes/test.env python -B -m unittest -q tests.test_semanticBrailleMessageRestoration tests.test_semanticBraillePendingRouting
```

From the repository root:

```text
rtk proxy uv run --no-project --with ruff ruff check nvda-addon
rtk proxy uv run --no-project --with ruff ruff format --check nvda-addon
rtk proxy python nvda-addon/build.py
rtk git diff --check
```

Linux tests used the existing private source at revision
`470a222989121a19041388a4417116ddc759eafe`. The GUI runner and canonical AT-SPI
model exactly match current main after newline normalization. The unit suite
combines `unittest.TestLoader().discover('tests/unit/input', top_level_dir='.')`
with the seven additional module names recorded in the evidence JSON. It ran
through the fixed local `tmp/braille-routing-outcomes/run_independent_linux_checks.py`
SSH helper, without active-desktop input.

Native GUI invocations used `python3 -B` with the existing absolute
`tools/diagnostics/real_gui_atspi_smoke.py` path and these two separate selections:

```text
--skip vscode
--skip settings --skip thunar --skip mousepad --skip terminal --skip calendar --skip firefox
```

The first selection passed Settings, Thunar, Mousepad, Terminal, Calendar and
Firefox checks. Calendar keyboard activation and selected-date semantics remain
provider limitations. The second selection reproduced #79; its failure remains
nonzero and is not turned into a pass by the other selection. No retry, increased
timeout or production workaround was introduced.

Installed Linux Orca reports **42.0**, Code **1.141.0** at
`2a59476c9bfcb90b3ddc372c36762471b7dfad1c`. The active Orca process is still
**254068**. The application runner verified its private Xvfb and private D-Bus
before actions; it did not use the active desktop or alter its settings. The
Windows fix does not change Orca's handlers or Linux runtime.

## Review artifact and remaining issue status

Candidate: `nvda-addon/dist/linuxRdAccess-20261014.0.3.nvda-addon`, SHA-256
`b07bd08dfe26bb888ee9339849f7c5cbb7b7e0a6b08e708f37b196eac4947ba6`.
Two builds produced that same hash; all 15 packaged Python files parse and the
archive integrity check passes. This branch is based on merged main and does
not include the separate unmerged PR #89 one-shot routing automation. The
candidate has not been installed; user installation/restart and test consent
remain separate decisions. No active Windows input was sent for this work.

| Issue | Evidence added independently | Remaining acceptance |
| --- | --- | --- |
| #57 keyboard/modifier ownership | Input regressions and native input/capture pipeline checks | Actual Windows NVDA gestures/layouts/modifiers across the live connection |
| #58 speech/interruption | Speech, Say All and braille-cancellation lifecycle units | Audible Windows output, ordering, cancellation and presentation-path comparison |
| #59 physical routing | Reproduced and corrected stale queued native routes | Physical b.note text/cursor/routing/panning and connection transitions |
| #60 application matrix | 48 private native GUI checks across six applications; VS Code failure reproduced | Live Windows presentation; calendar provider gaps; #79 |
| #61 stale input lifecycle | Deterministic queued-route regressions and automated lifecycle suite | Reviewed fix installation and live held-input/control/reconnect transitions |
| #72 temporary messages | Existing lifecycle tests remain passing; an old document route cannot dismiss a newer message | Clean full-window scripted rerun and remaining physical checklist; historical 6→9 cause unknown |
| #79 VS Code routing | Fresh isolated failure at the same installed revision | Reliable resolution of VS Code/Chromium selection/model behavior |

All acceptance issues remain open. Automated source methods, IPC tests and
private GUI actions do not establish physical display output or live Windows
NVDA acceptance. Sanitized evidence is in
[`queued-main-routing-evidence-2026-10-14.json`](queued-main-routing-evidence-2026-10-14.json).
No CI workflow was polled or awaited, and no PR was merged.
