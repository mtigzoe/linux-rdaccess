# Routing acceptance preparation without Desktop Commander — 2026-10-13

Base: merged `main` **7c21b45** (companion PR #78 and diagnostics PR #80).
Relevant issues: #59, #72, with speech #58, reconnect #61 and VS Code #79
remaining separate open acceptance/compatibility work.

## Findings and scope

Read-only source review confirmed that the companion keeps standard NVDA
braille routing local, maps TextInfo caret offsets to `lrd_a11y_caret`, and
guards retained callbacks by snapshot, session, control generation and current
transport. Linux validates the current semantic focus/script/window before
applying the AT-SPI offset and interrupts applicable Say All. No additional
production routing defect was established in this investigation.

Installed BrailleExtender source was inspected read-only. Its patched standard
routing script uses `braille.handler.routeTo` in normal routing mode; the saved
`routingCursorsEditFields` setting is `normal`. The installed `patches.py`
SHA-256 is `a9a394c2a0cb0564480558617826eba15f60aec4370e08fc7604dcf0e2266da9`.
This identifies the inspected source/settings, not a live loaded routing path.
No add-on files or user settings were changed.

The existing offline acceptance tracker lacks per-layer evidence for one
interaction. New `session-template` / `session-summary` commands preserve its
original matrix and separate keyboard delivery, Linux focus/caret, Windows
NVDA speech, semantic braille and human-confirmed physical braille. The summary
keeps the scope to that interaction. Speech events do not imply audible output,
semantic events do not imply a physical display, and isolated results do not
close an issue. Physical results require the declared user-confirmation source
and display model; this validates evidence labels, not an author's identity.

A read-only Linux caret observer reuses graphical-session discovery and the
existing focused-object probe. It requires the requested application and a
readable text caret, observes for 1–60 seconds, caps retained events at 64,
redacts content/provider errors, skips password caret providers, and invalidates
the comparison on a focus change. Listener registration/timer failures prevent
starting; listeners/timer are cleaned up on completion/interruption. It sends
no input and grants no new desktop permission.

## Validation

- Windows Python 3.10: **31 focused tests passed**, **1 native test skipped**
  because the private Linux GUI environment was absent.
- Linux Mint Python **3.10.12**: the same **31 focused tests passed**.
- Native isolated Linux Mousepad **0.5.8-1**: **1 integration test passed**.
  Private Xvfb and the runner-owned D-Bus daemon were verified before the
  fixture's direct AT-SPI stimulus. The observer recorded initial caret **2**,
  a caret **7** event at **+101.0 ms**, final caret **7**, the same focus object,
  no intervening focus change and no dropped events. This is observer
  validation, not NVDA-origin input or physical braille acceptance.
- Installed Orca package **42.0-1ubuntu2** was identified read-only; Orca was
  not loaded or restarted by this fixture.
- Scoped Ruff **0.16.4** check, new-file format check, Python compilation and
  `git diff --check` passed. An initial import-order/top-level bootstrap lint
  failure was corrected; only the final passing checks count.
- The native GUI workflow now runs this observer test in a separate private
  session and preserves its metadata log, including after another GUI check
  fails. The existing VS Code assertion is still required; there is no retry,
  timeout increase or skipped VS Code failure.

Sanitized machine evidence:

- [Layered interaction report](routing-observer-layered-evidence-2026-10-13.json)
  (`session-summary --file` compatible; only the isolated Linux layer passes).
- [Native AT-SPI metadata](routing-observer-atspi-evidence-2026-10-13.json).
- [Manual routing procedure](routing-tests-without-desktop-commander.md).

## Live acceptance

The Windows readiness probe reported NVDA **not running** at initial discovery.
No live keyboard gesture, routing key, message trigger or reconnect was sent by
the agent. The user was asked to prepare a new unsaved Mousepad fixture with
`alpha bravo charlie`, start/reconnect NVDA normally if necessary, and authorize
five minutes before the next authenticated-status/live observation check.
That preparation has not yet been confirmed. No new physical-routing PASS is
recorded. Earlier user-confirmed b.note left panning in Firefox and the Linux
terminal remains limited evidence from build `20261013.0.2`.

Desktop Commander and other desktop-control tools were not used. SSH was used
for source/test transfer into a temporary isolated checkout, read-only package
metadata and isolated tests. The active desktop, running Orca, NVDA settings
and saved relay credentials were preserved.

| Issue | Classification after this work |
| --- | --- |
| #59 | Needs live testing: physical routing/caret and repeated/boundary panning |
| #72 | Needs live testing: temporary-message restoration and remaining checklist |
| #58 | Still open: forwarded Orca speech wording, key echo and audible cancellation |
| #61 | Needs live testing: reconnect/handoff and stale-input acceptance |
| #79 | Still open: intermittent VS Code caret overwrite; PR #80 diagnostics merged |

New GitHub Actions are left to run without polling or waiting. No issue is
closed and no pull request is merged by the agent.
