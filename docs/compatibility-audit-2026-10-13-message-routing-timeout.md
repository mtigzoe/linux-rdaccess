# Routing a visible temporary message — 2026-10-13

Related: #59 (physical routing) and #72 (temporary-message acceptance).
Baseline: `01e79f1`, companion **20261013.0.4**.
Prepared fix: companion **20261013.0.5**, **not installed or physically retested**.

## Live evidence on .4

The user operated a b.note with Linux Mousepad focused. The agent used only
read-only SSH observations and the existing authorized Windows status endpoint.
No Desktop Commander, agent keyboard/clipboard input, driver changes or
NVDA/Orca restart was used. Windows authorization subsequently expired; later
Linux observations were read-only and did not renew or bypass that authorization.

Before testing, authorized status confirmed a connected transport, attached
semantic bridge, negotiated semantic braille and temporary-message support.
Remote control was local at those status checks; the later control handoff and
gestures were user-operated and not independently captured on Windows.
The installed manifest identified .4 and all nine Python files directly under
`nvda-addon/addon` matched the .4 checkout. This does not independently identify
the code loaded in the running NVDA process. The four bundled shared IPC modules
were not compared in that disk check.

The user's public sentence was **`Alpha Barlio Charlie`**, rather than the
originally proposed `alpha bravo charlie`. C in this sentence has zero-based
character offset **13**. The earlier 60-second routing observation retained
Mousepad focus and caret 17 with no recorded caret events. The user later
reported that routing at C announced C and confirmed intervening caret movement.
The subsequent caret readback of 6 cannot verify that particular C press.

| Check | Evidence and result |
| --- | --- |
| Direct C routing (#59) | Positive user-reported NVDA announcement. Exact Linux application of that press remains **unverified** because timing and intervening movement were not controlled. |
| Input-help message appearance and timeout (#72) | User answered yes to message appearance and restoration of the Mousepad line/cursor. **Limited physical PASS** for this one interaction. Separate Linux probes read 6 before and after. Exact message wording was not reported. |
| Routing while the message was visible (#72) | User confirmed dismissal, line/cursor restoration and no C announcement. Linux readback changed **6 → 9**. User subsequently clarified that the message was still visible at the press and there were no other caret moves. **Reported Linux caret-preservation failure**, with its precise cause and event timing still unisolated. |

No gesture-correlated Windows protocol trace or Linux event trace was captured
for the last check. The separate numeric readings and user report are not proof
that the queue race below caused this particular 6 → 9 movement. Do not replace
that uncertainty with an end-to-end PASS or attribute it to a braille driver.

## Independently reproduced queue defect

The semantic input decider lets NVDA queue its ordinary routing script after a
focus-recovery callback. The script chooses its target buffer when it executes.
If a Linux temporary message was visible when the routing key was pressed but
its timer expires before script execution, that press routes into the underlying
Linux text. Two presses queued while the message is visible can likewise make
the second press route after the first dismisses the message. A later Linux or
Windows message can instead be dismissed by the older queued press.

Source-backed tests run the actual NVDA routing script and message, routing and
timeout methods with isolated presentation dependencies. A routeable test buffer
uses the production RemoteA11yTextInfo caret sender. The unmodified .4 bridge
fails all four focused regressions: timeout, two queued presses, replacement
Linux message and replacement Windows message. The timeout and two-press cases
route to offset 13 and emit a remote caret request. These are deterministic
automated reproductions; the buffers are not a physical device or live NVDA.

## Fix and compatibility

A recognized routing press on a currently visible, Linux-owned message now
captures that message's ownership and queues a guarded native message route.
The ordinary routing script is suppressed for that press. If the original
message is still current, NVDA performs its normal routing dismissal. Expiry,
prior dismissal, message replacement, control/session changes, disconnect,
transport/handler replacement and termination make the queued operation inert.
It never becomes a route into the main buffer.

Weak references to the original message regions distinguish replacements even
when lifecycle hooks are missing, without keeping expired message text alive.
Stock NVDA TextRegion supports weak references. Custom message regions without
weak-reference support retain their ordinary native script path; this guarded
queue behavior is not established for those custom implementations. NVDA's
input-help and gesture-capture path remains native. Both cellIndexes and the
legacy routingIndex shape are supported; an empty cellIndexes list preserves
native no-action behavior. A fresh press after message expiry still routes the
current Linux text normally.

Linux implementation, controller marker, installation, root compatibility
wrappers and IPC permissions are unchanged. No Orca restart is required by this
source change. Using .5 in live NVDA will require a separately authorized
companion install/reload; none was performed here.

## Source and validation

NVDA source reference: **1406f9f8a04eb50f7317af87aba3a9d439c2a772**:

- [Global routing script](https://github.com/nvaccess/nvda/blob/1406f9f8a04eb50f7317af87aba3a9d439c2a772/source/globalCommands.py)
- [Native message, timer and routing handling](https://github.com/nvaccess/nvda/blob/1406f9f8a04eb50f7317af87aba3a9d439c2a772/source/braille/brailleHandler.py)
- [Input decider, capture and queued execution](https://github.com/nvaccess/nvda/blob/1406f9f8a04eb50f7317af87aba3a9d439c2a772/source/inputCore.py)

Read installed Orca **42.0**, package **42.0-1ubuntu2**, including
`scripts/default.py` enterLearnMode/exitLearnMode. Those handlers present
input-help messages and change learn-mode/keyboard-grab state; they do not
write the text caret. Read the installed BrailleExtender **26.06.05-eefe85d**
`patches.py` routing override, which delegates to native handler routing in its
normal mode. No Orca or BrailleExtender code was copied or modified, and active
BrailleExtender routing configuration was not independently identified.

- Original .4 bridge: **four expected regression failures**, zero harness errors.
- Fixed full Windows companion suite: **248 tests passed**, Python 3.13,
  `configobj==5.0.9`; includes the 38-test message-restoration module and isolated
  Windows kernel/IPC tests.
- Ruff **0.16.4** check and format validation passed after correcting import order.
- Companion .5 built successfully; all packaged Python sources compiled.
- Package contains 17 entries and 13 Python modules. It was built for review;
  it was not installed into the active NVDA session.
- `git diff --check` passed.
- Linux suites were not rerun for this Windows-only change. No new live .5,
  audible speech or physical-device acceptance was performed.

Keep #59 and #72 open. Retest caret preservation while dismissing a visible
message on .5, then confirm direct C routing at offset 13 without other caret
moves. Panning/timer reset, disabled messages, later Windows messages, handoff,
reconnect, other applications and broader physical acceptance remain pending.
No GitHub Actions polling or merge was performed.
