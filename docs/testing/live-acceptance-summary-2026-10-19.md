# Live acceptance summary — 2026-10-19

Acceptance is **incomplete**. Issues [#57](https://github.com/mtigzoe/linux-rdaccess/issues/57), [#59](https://github.com/mtigzoe/linux-rdaccess/issues/59) and [#61](https://github.com/mtigzoe/linux-rdaccess/issues/61) remain open. [PR #146](https://github.com/mtigzoe/linux-rdaccess/pull/146) remains draft pending documentation review. Miriam has not confirmed acceptance.

This summarizes the [dated evidence record](issue61-live-acceptance-results-2026-10-19.txt). The [merged #61 procedure](issue61-live-acceptance.md) remains the acceptance reference. This summary adds no production fix or acceptance claim.

| Issue | Evidence recorded | Still needed |
| --- | --- | --- |
| #57: keyboard/modifier ownership | One assisted remote-to-local control transition with physical Windows-content report; another automated entry was inconclusive. | Physical command and modifier tests, layouts, capture, held/repeated keys, releases and queued commands. NVDA+T has not completed. |
| #59: physical braille | Miriam read Windows content and handoff status notices on the b.note. | Focused Linux object text/role/state/value, caret, physical routing/panning, input help, reconnect behavior and supported presenter attribution. |
| #61: lifecycle/handoff | Partial handoff state and tactile evidence; one timed quiet observation with changed focus and uncertain manual activity. | Successful preflight/full H1, isolation, reconnect/restart, stale input/output, queued work and approved failure/recovery cases. F1 remains NOT RUN under the merged procedure. |

## Results that can be used

- **ASSISTED-RETURN-01:** one requested Windows handoff, observed remote-to-local state change, connection preserved; Miriam reported **“Windows content.”** This is narrow control/content evidence.
- **FRESH-P6-01 entry:** the key API returned normally, but two checks still showed local control; Miriam reported **“Windows content.”** **INCONCLUSIVE:** actual delivery/recognition remains unverified.
- **Timed P6 observation:** a 30.037-second wait occurred. The fixture was focused before the observation; a later check found terminal focus. The exact focus-change time is unknown. Miriam affirmed manual activity and answered **“Not sure”** about its timing. **INCONCLUSIVE.**
- **ASSISTED-RETURN-02:** the first post-check was remote and a later check was local. With manual activity reported, the change cannot be credited solely to automation. **INCONCLUSIVE.**

Miriam reported these tactile notices, preserved verbatim:

> Remote computer rontorl.

> contorl local computer.

These are handoff-status observations. They do not establish the focused Linux editor's presentation or uninterrupted quiet. Audible Windows speech remains **UNVERIFIED**.

## Environment and limits

The Linux controller's v123 files were verified on disk after the previously approved Orca restart; exact loaded bytes remain unverified. Windows standalone companion **20261014.0.2** remains installed; **.4 was not installed**. Semantic negotiation does not attest physical display output.

Latest verified Windows state was connected/local at **14:32:27 EDT**. Linux focus was terminal at the **14:31:48 EDT** read. A **14:45:29 EDT** read-only preflight found the existing public Firefox fixture available but inactive. Recheck before any new action.

No confirmed production defect follows from the inconclusive input attempts. No production fix, restart, setting change, installation, disconnection, or build change is proposed.

## Assisted testing preference and next step

Miriam asked whether the agent can perform the tests remotely to reduce her keyboard work. This question did **not** approve the proposed manual entry/read/return sequence. That trial and the prepared bounded fixture restoration have **not run**. No further key, focus, connection, setting, installation or restart action was authorized by this question.

Use existing Desktop Commander, SSH and Python diagnostics for read-only observations, software checks, comparison and recording. Do not add a second remote-control application or use Linux injection as Windows NVDA acceptance evidence. Further agent-driven gestures or fixture focus changes still require an explicit bounded scope; earlier one-shot approvals are exhausted.

A source inspection of [NVDA 2026.2's Remote Access menu](https://github.com/nvaccess/nvda/blob/release-2026.2/source/_remoteClient/menu.py) found no control-handoff menu command. It therefore supplies no verified menu alternative to the inconclusive injected shortcut. This is a source finding, not a fresh check of the installed application's live state or a diagnosed input defect.

The agent can reduce manual work, but software logs and Braille Viewer cannot establish physical b.note cells, routing or panning. Keep hardware observations, real keyboard coverage and Windows speech evidence separate from software checks. Do not claim all three issues can be accepted unattended.

The old timing question is closed as **“Not sure”**; it will not be reconstructed or repeated. No new gesture or quiet interval was performed for this update. Any future live trial needs fresh connection/focus checks, one agreed input source, and a reliable return to Windows before Miriam types on the same laptop.

Keep the issues open and PR #146 draft until their respective requirements and documentation review are confirmed.
