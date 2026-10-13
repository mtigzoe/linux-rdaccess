# Linux braille restoration after temporary messages — 2026-10-13

Related: temporary-message acceptance #72 and physical braille #59.
Base: `main` **846b0f4528d523381faa24cbef5bcaf777197294**.
Prepared companion: **20261013.0.4**.

## Confirmed automated defects

A Linux temporary message uses NVDA's native message buffer. Native dismissal
returns to the main buffer; it does not reconstruct Linux focus. If a Windows
focus update replaced that main buffer before the Linux message arrived, or
while it was visible, dismissal restored Windows content. Source-backed
regressions reproduce both cases on the unmodified .3 bridge.

A retained Linux region can also share the current focus ID and session while
its object belongs to an older snapshot. The existing focus-region detector
accepted it, so recovery skipped rebuilding stale content and left its invalid
input sender in place. A separate focused regression failed before adding
current-object identity validation.

These are **automated-reproduced defects**, not new physical observations.
The test buffers/timers are isolated; no running NVDA or Linux desktop is
modified and no private document content is captured.

## Implementation

After NVDA actually displays a new Linux message, repair cached Linux focus
underneath it. Determine actual presentation from changed region identities,
so disabled messages, speech-only mode and a pre-existing Windows message
cannot be incorrectly claimed as a new Linux message.

Use NVDA's native pre-show and post-dismiss extension points to track message
ownership. A later Windows message clears Linux ownership. On dismissal,
recover the latest Linux snapshot only for the same handler, connected session
and control generation with active remote control. Disconnect, fallback,
new sessions, local control and termination invalidate that ownership. Hooks
are removed on termination. No message contents are retained in the ownership
metadata or logged.

Focus-region validity now requires the object from the bridge's current map,
as well as its ID and session. Old retained senders remain invalid. Existing
intact Linux regions and their panning window are preserved.

NVDA's native timeout, panning timer reset, routing dismissal, Show messages
policy and speech-only mode remain authoritative. If the lifecycle extension
points are absent, the pre-message repair remains available but repair of a
replacement made while a message is already visible is unavailable.

## Source and validation

Pinned NVDA source: **1406f9f8a04eb50f7317af87aba3a9d439c2a772**,
`source/braille/brailleHandler.py`. Tests compile its actual `message`,
`_resetMessageTimer`, `_dismissMessage`, routing and panning methods with
presentation dependencies stubbed.

A separate disposable harness runs the installed NVDA 2026.2 `braille.pyc`
methods against those same isolated buffers/timers. Bytecode SHA-256:
`988b977c3e3286727070136c6b8f9b11a4046fed0e1eb10a64ca59f1712a2d12`.
It does not import or inject code into the running NVDA process.

The installed BrailleExtender `speechhistorymode.py` wrapper was also read.
It delegates to native messages outside speech-history tether mode and skips
them in that mode; this is source inspection, not live mode acceptance.
Its file SHA-256:
`8afca62e079c4c828ae7980c4aed0a973f570e87e3215ae5b4cd8df2a9b2a1e7`.

- Unmodified .3 bridge with installed NVDA message bytecode: **two expected
  restoration failures**.
- Retained same-ID region: **one expected failure** before identity validation.
- Fixed focused module: **20 tests pass**, also **20 pass** using installed
  bytecode in the independent isolated harness.
- Full Windows companion suite, Python 3.13 and documented
  `configobj==5.0.9`: **230 tests pass**, including kernel/IPC and packaging.
- Ruff 0.16.4 checks and format validation, package source compilation and
  `git diff --check` pass. Only the new test file needed formatting.
- Test-fixture callback lifetime and misplaced assertions were corrected before
  the final counts; those harness errors were not product regressions.

The deterministic package contains **17 entries**, **13 compilable Python
files** and **48,031 bytes**. SHA-256:
`65c441d2398fee0708ff4b1a5e481bb059b2e73e6ddb6a765bbc708736771c77`.
A second temporary build matches. Compared with .3, only the manifest, help
document and semantic bridge module differ. Linux code, root wrappers and
IPC permissions/protocol are unchanged.

## Live limits and next acceptance

At task start, installed .3 files matched all 13 package Python files; disk
verification alone does not prove the running build. The authorized status
launcher returned `required_or_expired`; fresh consent was requested. No live
desktop input, automatic consent renewal, Desktop Commander, NVDA/Orca restart,
driver change or BRLTTY/BrlAPI operation was used.

Build .4 is **not installed or physically accepted**. Native post-dismiss
notification occurs after NVDA's initial update; the recovery fixes final
restoration, but a brief intermediate Windows frame on physical hardware was
not measured. Physical tests must verify readable Linux text/caret after
timeout and routing dismissal, panning/timer behavior, disabled messages,
Windows-message replacement, handoff and reconnect. Keep #72 and #59 open;
do not convert source-backed tests into live acceptance. No CI polling or
merge is performed.
