# Reconnect and stale-input lifecycle audit (issue #61)

Base: `origin/main` at `d8557b28848edd27a848188f9ca045c5378f95aa`.
Branch: `issue_61`.

**Result: no new defect was reproduced.** This change adds lifecycle coverage
only; it changes no production code. Issue #61 is a live-validation task and
remains open. Nothing here is live Windows NVDA, Linux Mint, Orca 42, or
physical braille evidence.

## Method

Reviewed the injected remote-input shim (`linux_rdaccess_core/connection/
remote_access.py`), the DVC speech/braille/A11Y links, the AT-SPI bridge, and
the Windows companion's session/control-generation guards, then probed the
reconnect, handoff, queued-work, held-key and injection-failure scenarios with
the repository's fake upstream controller and fake GLib queue. Fixes already
merged to main (PRs #78, #90 and #98) were not duplicated. The companion was
reviewed by reading its guards; its tests were not run here because they need
an NVDA source checkout.

A randomised model checker then drove fixed-seed interleavings of remote key
events, control handoff, transport disconnect/reconnect (including role
change), master-client departure, queued Orca main-loop work and injected
key press/release failures. An independent oracle checked two invariants:

1. After a final teardown with a working backend, no Linux key is held. A
   release that failed earlier stays owned and is retried by the next reset.
2. No queued Orca operation runs after the session it was scheduled in ended.

Across 400 seeds for invariant 1 and 150 seeds for invariant 2 (during
exploration), and the 60 committed seeds, both invariants held.

An early exploration run flagged six stale-callback executions. They came
from the model flipping `connection_type` directly with no connect or
disconnect callback. As far as the shim's code shows, a role change only
arrives with a new transport, and connecting resets input. That was a modelling
error, not a defect, and the committed test uses role-changing reconnects
instead.

## Candidates examined and not confirmed

- **Key press delivered after `disconnect()` returns.** Forwarded and owned
  until the next state change in a synthetic test. Not reachable in the
  transport: messages and the `transport_disconnected` callback run on the
  receiver thread in order, and that callback resets and releases held keys.
- **Braille link flushes content offered while no session was active.** The
  newest content is deliberately kept and delivered when the next session is
  ready, and existing tests assert this. `on_ready` normally replaces it with
  the live focus first.
- **Semantic action with only an object id.** Late messages from a previous
  XON session are dropped by `drain_current_session()`, and the object
  registry is replaced on every focus snapshot. A stale action naming an
  object that is still present in a newer snapshot would still execute. This
  is a design question (no snapshot id on the wire), not a reproduced
  failure, and no test was written for it.
- **Elements-list chooser across a reconnect.** The stale selection is
  dropped by the generation and request guards. The chooser keeps the dialog
  flag set until dismissed, so NVDA+F7 is ignored until then. Unverified.

## Coverage added

`tests/unit/input/test_lifecycle_invariants.py`: five targeted regressions
(queued speech stop across reconnect, late deferred Insert and CapsLock
release after reconnect, master departure releasing every held key exactly
once, role-changing reconnect expiring queued Orca work) and the two
fixed-seed invariants above. The assertion messages carry the full event trace
of the first failing seed.

Mutation check (temporary, reverted): disabling the generation guard in the
queued-work scheduler failed three tests; making the reset skip key release
failed two tests. These prove the tests detect broken lifecycle handling; they
are not failures that existed before a fix.

## Test results

Linux sandbox, Python 3.12.3, Xvfb, AT-SPI, Liblouis installed:

- Main `d8557b2`: 1591 tests, OK, 10 skipped.
- This branch: 1598 tests, OK, 10 skipped (the 7 new tests).

CI runs Python 3.10 on Ubuntu 22.04; that environment was not reproduced
locally.

## Coverage gaps

- **Orca restart.** A restart replaces the shim's in-memory state in a new
  process. It was not simulated; only reconnect and handoff transitions were.
- **Windows companion.** Not exercised by this change.
- **Real key injection failure** was modelled with a fake backend only.

## Remaining live acceptance

Still required with real hardware: Insert+Alt+Tab handoff with held modifiers,
NVDA Remote disconnect and reconnect during typing, Orca restart in an active
session, actual key-injection failure, and physical braille routing and
panning after each transition, with the standalone companion active rather
than the legacy RDAccess integration. Issue #61 cannot be closed on automated
results.
