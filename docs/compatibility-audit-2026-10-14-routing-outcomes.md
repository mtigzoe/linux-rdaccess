# Routing outcome diagnostics — 2026-10-14

Related: #59 and #72. Both remain open. This change adds evidence collection,
not a routing, speech-cancellation or caret-placement fix. The historical 6→9,
20→7, physical-cursor/unchanged-21 and mixed .6 observations remain separate,
unattributed reports.

## Baseline and independently verified findings

Fetched `origin/main`: `322b6d66f64fa45e4f668ebb8b4f7c5644d2060f`, the merge of
PR #85. Reviewed issues/comments and merged PRs #83, #84 and #85, the BRLTTY and
BrailleExtender research notes, and the previous routing/message audits.
The working tree was clean. Other contributors' worktrees were not modified.

Native routing references:

- NVDA **2026.2**, tag commit
  [`f62c980589d1ac30babf68ad48177e9ad29a2e84`](https://github.com/nvaccess/nvda/blob/f62c980589d1ac30babf68ad48177e9ad29a2e84/source/braille.py).
- Existing project CI reference
  [`1406f9f8a04eb50f7317af87aba3a9d439c2a772`](https://github.com/nvaccess/nvda/tree/1406f9f8a04eb50f7317af87aba3a9d439c2a772/source/braille).

Both references establish the relevant branches: a mapped buffer position at or
beyond `windowEndPos` returns without routing a region; the current text cursor
can cause `TextInfo.activate()` instead of a caret write; routing on a native
message dismisses it. A window conversion exception is preserved and classified
as unknown, rather than inventing a successful no-op.
Both references also clamp valid-row padding positions to the row's last content
cell. A blank physical cell is therefore not automatically an ignored route.
Tests cover this clamping separately from the empty-buffer no-op using
internally consistent native window geometry.

Linux's setter validates the target and character bounds before invoking the
speech-stop callback, then invokes the provider setter once. Explicit routing
increments `_lrd_braille_route_epoch`; the current Say All session guard includes
that epoch, preventing an old cancellation callback from overwriting the chosen
caret. Input-help descriptions deliberately do not select a new caret and retain
native cancellation placement. Existing source-backed regressions demonstrate
both policies. Native cancellation can therefore be relevant without proving
the cause of any historical live movement. No cancellation policy was changed.
In the source-backed input-help case, a request for offset 9 is consumed without
a direct write, and native cancellation later places the fake caret at 3.
Explicit routing instead retains 9 despite late cancellation/index callbacks.
These isolated results do not diagnose the historical physical reports.

## Read-only installed-source comparison

SSH to `cyber` was available. The old `/home/miriam/linux-rdaccess` checkout was
absent. Installed packages reported Orca **42.0-1ubuntu2**, pyatspi **2.38.2-1**
and libatspi **2.44.0-3**. Read installed integration source without importing it
into, restarting, or instrumenting the running Orca process.

- Installed controller ASTs for `_linux_rdaccess_semantic_caret`,
  `_linux_rdaccess_stop_braille_speech` and `_linux_rdaccess_run_main` match the
  main-baseline methods.
- Installed adapter `_semantic_target` and `set_semantic_caret` method ASTs
  match main. The whole adapter file is not byte-identical; this is not a claim
  that every installed component matches the checkout.
- Installed Orca's `__sayAllProgressCallback` AST matches the Orca 42.0 fixture
  used by the isolated tests.
- Installed customization guard bodies are not AST-identical to the current
  generated bodies. Their source contains both Say All and routing epoch
  references. This comparison alone does not establish equivalent behavior or
  identify a defective guard.

These are **on-disk** comparisons, not attestation of code loaded by the running
process. No claim assigns the original failure to Orca, NVDA, BrailleExtender,
BRLTTY or a particular display driver.

## Windows outcome evidence

Companion candidate **20261014.0.1** uses the existing separate, unchecked
numeric-routing checkbox and five-minute authorization. Version 1
status/connect/cancel and version 2 `braille_trace` retain their schemas and
semantics. The new argument-free **version 3 `braille_outcomes`** read is exposed
by `python linux_rdaccess_test_session.py nvda-braille-outcomes`.

The legacy event ledger and new outcome ledger each retain the first **12**
records and have independent saturated `dropped` counts. Both use the same
capture clock and consent lifetime. Expiry, revocation, secure desktop, lock,
profile change, shutdown and new consent clear both. Neither read enables,
resets or extends collection. Same-user authentication and GUI-thread dispatch
are unchanged; the operation cannot connect, send input or execute code.

Outcomes use the same fixed numeric/boolean metadata fields as the legacy
trace. No text, filenames, object/gesture identifiers, passwords, credentials,
exception messages or ordinary keystrokes are retained.

| Outcome enum | What is actually observed |
| --- | --- |
| `native_delegated` | The decider permits NVDA's native coordinate script; it has not necessarily executed. |
| `outside_buffer` | The actual stock conversion returns a position at/beyond the native buffer end, establishing its no-region-routing branch. |
| `activation_attempted` | Remote TextInfo activation or a normalized remote-object action was entered. Activation may remain unsupported or be rejected later. |
| `caret_attempted` | The remote TextInfo calls its caret sender after local argument checks. |
| `caret_rejected` | Local setter validation or the current-snapshot sender guard rejects the attempt. |
| `caret_send_returned` | The semantic transport send call returned. No Linux receipt or application is implied. |
| `caret_send_failed` | That send call raised; it is not retried and exception text is excluded. |
| `message_dismissed` | Native post-dismiss notification occurred during an observed handler route. This is logical-buffer evidence, not measured physical output. |
| `route_discarded` | A queued message route fails its original ownership/regions/session/control checks. |
| `outcome_unknown` | No supported effect was observed, capture intervened, a route was delegated elsewhere, or optional observation was unavailable. |

These are ordered stages, not mutually exclusive final results. A null routing
index does not establish association with a physical key. The version 2 ledger
still supplies gesture-received and message/control lifecycle evidence.
Incomplete traces cannot prove absence of a request.

The observer calls original methods once, preserving arguments, return values
and exceptions. It observes the actual native conversion instead of evaluating
it again. Unsupported/custom buffers remain unknown unless another effect is
observed. Temporary conversion wrappers are restored; handler wrappers are
removed on bridge termination only if no later add-on replaced them. Disabled,
missing and failing diagnostics must not change routing. No upstream production
implementation was copied; tests execute selected methods from pinned sources.

## Linux reason codes

`CaretReason` is defined in `linux_rdaccess_core/caret_diagnostics.py`. Optional
callbacks are isolated from production return values and exceptions. Codes
distinguish:

- Invalid object/offset, no semantic context, stale context, stale focus/script/
  window, unknown object, and unavailable target validation.
- Unavailable text interface, unavailable character count, character-range
  failure and unavailable setter.
- Provider refusal, provider exception and pre-route callback exception.
- Input-help consumption, stale queued session, scheduling failure, invalid
  protocol version, unavailable semantic mode and unclassified adapter failure.

`setter_returned` preserves the existing provider-return interpretation; it
does **not** assert a readback or final caret. Interface-unavailable does not
pretend to distinguish absence from every provider query failure. There are no
new text reads, retries, selection changes or alternate setter attempts.

Existing rejection/failure error logs now include fixed reason codes. Early
drops, input-help consumption and stale-session diagnostics use DEBUG; default
logging need not show them. No debug logging was enabled on the live machine.
Older adapters without the diagnostic capability still receive one call using
their old keyword signature; their unclassified result remains unknown.
An absent or malformed optional reason module also leaves caret behavior intact:
reporting is lazy and exception-contained, and the controller retains its old
generic rejection/failure log if classification is unavailable. A missing-module
regression first exposed an unintended dependency in the WIP implementation;
it passes after removing that dependency. This corrects the new diagnostics,
not a newly claimed defect in merged main.

## Deployment and future single-gesture check

The package is a review artifact, **not installed**. Future live collection needs
the new companion plus an independently approved Linux v121 installation with
the updated adapter, model and standalone `linux_rdaccess_caret_diagnostics.py`.
The installer includes the helper and doctor reports missing/stale/current
copies. Do not invoke connect/install/reload automatically to obtain diagnostics.
No NVDA or Orca restart occurred during this task.

After the user separately authorizes installation/reload and a test session:

1. Prepare Mousepad's public `Alpha Barlio Charlie` fixture. Disable input help
   and wait for all temporary messages to disappear. Prepare display panning
   before recording. Place the Linux caret somewhere other than **13**, the C
   in Charlie. Confirm exact fixture and initial numeric caret read-only.
2. Prepare both Windows reads and the existing read-only Linux observer first.
   Start a fresh, opted-in five-minute session after preparation; revoke a still
   active older session before granting a new one. Recheck transport, semantic
   negotiation and user-operated Linux control. Do not renew consent remotely.
3. With the Linux observer already running, ask for **one routing-key press
   under C in Charlie**, then stop Linux input. No arrows, panning, extra routes
   or message toggles in that observation window.
4. Save initial caret, target, both Windows ledgers and their drop counts,
   semantic request if observed, Linux caret events/final offset, and the user's
   physical result. Match the same target/focus and approximate clocks; a send
   return alone is insufficient. Do not repeat a press to repair missing data.

For #72, use a separate recording after ordinary routing is understood. First
verify message entry/timeout and Linux ownership. Only then test one route while
that message is visible, with caret preservation and no remote action/caret
request as separate acceptance conditions. No physical acceptance is claimed here.

## Validation and environment limitations

- Full Windows companion suite: **334 passed**, **0 failures/errors/skips**,
  Python 3.13/configobj 5.0.9 and CI-pinned NVDA source. This includes existing
  message lifecycle contracts repeated with diagnostics enabled, plus real
  isolated authenticated kernel/IPC tests.
- New outcome-specific tests against NVDA 2026.2 release source: **15 passed**.
- Local Ubuntu WSL, Python 3.10.12, native AT-SPI preloaded: **415 passed** across
  routing/semantic protocol, all four Orca contract areas, logging, standalone
  installation, patch integrity, stable imports and launcher checks;
  **0 failures/errors/skips**. A final added malformed-helper/logger regression
  passed separately (**1 passed**), without repeating provider input.
- Private Xvfb/D-Bus GTK test: **1 passed**, with a real provider setter, fixed
  reason, 2→7 readback and matching caret event. No keyboard/mouse injection.
  This is isolated provider evidence, not NVDA-origin or physical acceptance.
- The same native test on Windows explicitly reports **1 skip**, without
  starting an application or attempting GUI input.

Initial cross-environment runs are not hidden: the full source-backed message
subset on NVDA 2026.2 release source had **one failure** for an existing
empty-cell-list assertion. That same assertion fails on pristine main with
that reference; the CI-pinned reference passes. Two Linux configuration tests
fail on Windows (POSIX file mode and default text encoding), also reproduced
on pristine main. A broader Windows Linux-fixture run had four subtest failures
for one POSIX-mode test. The corresponding native Linux runs pass. These are
reference/platform limits, not newly attributed production regressions.

Automatic approval review rejected both a whole-source archive transfer and a
smaller unpublished patch transfer to the remote Mint test directory. Permission
was requested; neither transfer occurred. Linux validation instead used the
existing local WSL environment, with no source export. Updated diagnostics were
not tested in the active Mint session. Its source comparisons were read-only.
Mousepad is absent in WSL; the new native regression uses the owned GTK fixture
instead. No active application document, driver or connection was changed.

Final companion artifact: **19 entries**, **15 compiled Python modules**,
**55,343 bytes**, reproducible byte-for-byte, with archive CRC/unique-path and
exact source-entry checks passed. SHA-256:
`1c6368e0757b86ffc6da14f6fcda146c1307445d58b579dc3d369455d232ccf2`.
Scoped Ruff 0.16.4, new/companion formatting and `git diff --check` passed.
The companion package and Linux diagnostics are not deployed.
