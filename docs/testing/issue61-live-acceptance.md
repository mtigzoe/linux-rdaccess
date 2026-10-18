# Issue #61: live NVDA and b.note braille acceptance procedure

Status: **procedure and results template only. No live test has been run, and
nothing in this file is acceptance evidence.** Issues #57, #58, #59, #61 and
#72 stay open.

Issue: https://github.com/mtigzoe/linux-rdaccess/issues/61

Results template: [issue61-live-acceptance-results-template.txt](issue61-live-acceptance-results-template.txt)

Baseline: `main` at `b4d741f` (prepared 2026-10-18).

How to use this file: read sections 1 to 5, then run the cases in the order
given in section 7, one step at a time. Record every step in the results
template. Do not decide pass or fail during a step; record what was heard and
read, then classify afterwards (section 10).

## 1. Purpose

Issue #61 is narrowed to live acceptance: Windows NVDA controlling Linux Mint
XFCE through NVDA Remote Access, with linux-rdaccess and Orca 42.0, and the
Eurobraille b.note 80 as the physical display. This procedure turns the five
remaining checkboxes of #61 into single-gesture observations with expected and
observed results.

It adds no tests, changes no production code and does not extend the automated
harness. Automated green checks are not acceptance, and this file does not
change that.

## 2. Roles

Miriam performs every physical action: Windows keys, b.note keys, and any
disconnect, reconnect, handoff or Orca restart.

The assistant (ChatGPT) reads one step at a time, writes down what Miriam
reports, and fills in the results file. The assistant does not send keys, move
focus, restart anything, or change the desktop. If an assistant has an approved
tool session, only the light read-only Linux checks in section 9 are allowed,
and only when Miriam asks for them.

## 3. Session rules

- One gesture per observation. Do not combine actions. Wait about three
  seconds for NVDA speech and braille to settle before the next action.
- One input source. While a case runs, nobody touches another keyboard, the
  mouse, or any b.note key that the step does not name. The 2026-10-06 record
  shows mixed manual and scripted input producing unexplained key events and
  invalidating trials. If any unplanned key is pressed, by anyone, mark that
  step INCONCLUSIVE.
- Use only the fixture page (section 5). Never type passwords or private text.
  Never put Linux focus in a terminal, an editor with real documents, or any
  other application during this procedure.
- Restart nothing except where a case names the restart (R2 and M4), and then
  only Orca, performed by Miriam on purpose. Do not restart NVDA, Remote
  Access, the Linux desktop or XFCE, and do not install, enable, disable or
  reload NVDA add-ons.
- Do not change braille drivers or settings, saved relay credentials, or the
  Linux controller installation. Do not write the relay address, channel key
  or any credential into the results.
- Any agent-driven action goes through the existing five-minute consent
  mechanism and never bypasses it. This procedure needs none.
- Cyber is running the issue #79 Chromium/Electron build. Do not start, stop
  or touch it. Do not change swap, cgroups, CPU limits, Docker, Authentik, SSH
  or XFCE. Keep Linux-side checks to the light read-only commands in
  section 9. If the Linux session is sluggish, record that and stop.
- Do not touch issue #58, issue #57, #59 or #72 from this procedure. Evidence
  that also bears on them goes in the results file only (section 13).
- Do not fix anything during the session. A failure is recorded, then handled
  as in section 11.

Stop conditions: stop at the first FAIL; if a stuck modifier cannot be
cleared; if Linux focus leaves the fixture page unexpectedly; if remote
control cannot be regained within two minutes of the planned recovery step; or
if any hardware problem appears with the b.note.

Stuck modifier recovery: with remote control active, tap and release Shift,
Ctrl and Alt once each, then record whether the symptom cleared. If it did not
clear, stop.

## 4. What existing automated tests already establish

These are not repeated here. They show software behavior at test boundaries.
**They do not establish audible Windows NVDA speech, physical braille, or
real-desktop behavior.**

Fresh input after reconnect; no stuck modifiers, duplicate activation or replay:

- PR #120: real pinned NVDA Remote relay with the patched Orca controller in a
  disposable real Orca; fresh press and release after reconnect; unowned
  releases are not sent.
- PR #121: a held Shift is released and its ownership cleared on disconnect,
  observed at a test-only injection boundary. No real X11 key injection.
- `tests/unit/input/test_lifecycle_invariants.py` and
  `tests/unit/input/test_lifecycle_recovery_edges.py`: queued speech stop across
  reconnect, late deferred Insert and CapsLock release after reconnect, master
  departure releasing held keys, role-changing reconnect expiring queued Orca
  work, and fixed-seed model-checked invariants (see
  [the 2026-10-16 lifecycle audit](../compatibility-audit-2026-10-16-reconnect-lifecycle.md)).
- Orca restart: `tests/integration/isolated_orca_restart_smoke.py` runs in an
  isolated session. See
  [issue-61-connected-orca-acceptance.md](../issue-61-connected-orca-acceptance.md)
  for exactly what it does and does not load. A live Orca restart is untested.

Stale queued shortcuts and old focus, script or window actions:

- PR #124: a queued Orca NVDA+T action no longer runs after teardown; the
  generation expires before held-key cleanup. The regression failed before the
  fix. Installed controller upgrade coverage was added.
- Deferred structural-list guards (request, script, window, document and
  generation checks): static code review only, per the 2026-10-17 comment on #61.
  Not shown to be race-free.

Stale braille routing, panning and speech from a replaced session:

- PR #78 (commit b7f24a7) and PR #90: Windows companion callbacks and native
  braille routing presses are bound to their snapshot, semantic session,
  control generation and connected transport. Tested with mocks and selected
  NVDA source references, not with an installed NVDA or a physical display.
- Speech interruption and Say All lifecycle coverage is tracked under #58.

Handoff:

- Partial live evidence on 2026-10-13: two Insert+Alt+Tab gestures changed
  `remote_control_active` true, false, true while the transport connection and
  semantic negotiation were preserved, and NVDA queued the matching announcements.
  No navigation or text was sent. This was the legacy RDAccess integration with
  the standalone companion installed but inactive. It is not audible speech,
  not braille, and not companion acceptance.

Key injection and release failure:

- Modeled with a fake backend only. Upstream `LocalMachine.send_key` does not
  report injection outcome (see
  [issue-61-upstream-key-injection-safety.md](../issue-61-upstream-key-injection-safety.md)).
  This is why case F1 below is not executable as a live test.

Live-only, therefore the subject of this procedure: all of the above as heard
through Windows NVDA and read on the b.note, plus Orca restart, abrupt
disconnect and recovery on the real desktop.

## 5. Preflight

Complete and record all of P1 to P8 before case H1. Any item that cannot be
completed is recorded as such, and the cases that depend on it are NOT RUN.

P1. Consent and roles. Miriam confirms she is ready to run live tests and that
the rules in section 3 apply.

P2. Environment record. Record in the results file: date and time; repository
`main` commit; Windows NVDA version; NVDA keyboard layout and NVDA modifier
key setting; Remote Access mode (for example hosted locally; do not record the
address or key); b.note 80 connection, driver, cell count, translation table
and tether setting as currently configured (read, not changed); Linux Mint and
XFCE versions; Orca version (expected 42.0); and Orca process ID.

P3. Integration attribution. Record which Linux integration NVDA is using:
the legacy RDAccess integration or the standalone companion, with the
companion build if active. On 2026-10-13 NVDA 2026.2 still used the legacy
integration and the companion was inactive. If the legacy integration is
active, results count for that path only and do not accept the companion fixes
in PRs #78 and #90. Also record the installed Linux controller version and
patch status (the `linux-rdaccess doctor` check named in
[live-x11-diagnostics.md](../live-x11-diagnostics.md); read its help text
before running it).

P4. Linux fixture. Before the session, Miriam (or an assistant with her
explicit approval) opens `tests/fixtures/firefox-acceptance.html` locally in
Firefox on the Linux desktop. Opening this tab is the only Linux desktop
change the procedure assumes. Leave Linux focus inside the page. Reload (F5)
between cases, never during one.

P5. Mechanisms. Choose and record the exact method for each of: handoff
(expected Insert+Alt+Tab, or your configured keys); graceful disconnect;
abrupt break (a Windows-side action that ends the connection without the
graceful command and without restarting NVDA or Orca, for example stopping the
Remote Access host if you host locally; do not disable network adapters,
power off or restart NVDA); reconnect; regaining remote control; and Orca
restart. Orca restart should use the session-aware starters named in
live-x11-diagnostics.md (`start-orca-session.sh` or `linux-rdaccess connect`);
record the exact command and where it was run. For the held-key cases the
graceful disconnect must be performable with the other hand while one key
stays held. If it cannot be, those cases are NOT RUN.

P6. Baseline quiet check. With remote control active and Linux focus in the
page, do nothing for 30 seconds. Record any speech or braille change. Any
unexplained activity means stop and find the source before continuing.

P7. Lock states. Record the Caps Lock, Num Lock and Scroll Lock states. Do not
change them during this procedure.

P8. Recovery plan. Confirm how remote control will be regained after each
planned transition and how a stuck modifier will be cleared (section 3).

## 6. Standard probes and terms

Fixture elements used: Single line editor (value "Single editor alpha"),
Plain multiline editor (three lines: alpha, bravo, charlie), Rich multiline
editor, and the "Reading segment" paragraphs.

Anchor focus: Linux focus in the Single line editor, remote control active.
Reach it by any method and record the method. Confirm by speech or braille.

Tab probe: from the anchor, press Tab once. Expected: focus lands on the Plain
multiline editor and NVDA speaks or shows that name. Landing on the Rich
multiline editor means two stops happened (duplicate). Landing anywhere
earlier means a backward move.

Letter probe: with focus in the Single line editor, press the letter x once,
with no modifier. Expected: one lowercase x is added, once, and nothing else
happens (no select-all, no menu, no NVDA command, no uppercase X). A field may
select its text when focused by Tab, so do not judge position or replacement;
read the field on the b.note and record what it shows.

Quiet interval: no keys on any device for the stated seconds. Record every
speech or braille change during it.

Safe Windows focus: while the connection is down or control is local, keep
Windows focus in an empty Notepad window with no unsaved data.

Output after a transition is acceptable only if it describes the current Linux
focus. Output that continues, repeats or describes something from before the
transition is stale. Record it verbatim and let the classification decide.

## 7. Run order

Core run (the five #61 checkboxes, minimum): P1 to P8, H1, H2, R1, M1a, M1b,
M2, U1, S1, B0 to B3.

Extended run, only after the core run is recorded: R2, M1c, M3, Q1, Q2, M4.

F1 is documented but not run (section 8).

After any FAIL or INCONCLUSIVE, stop and decide with Miriam whether to
continue (section 11). Reload the page between cases.

## 8. Cases

Each step is one gesture followed by its own observation. Record speech and
b.note braille separately. "Expected" states the requirement from #61; it is
not a prediction that the software passes.

### H1. Handoff to local control and back

Criterion: intentional handoff. Start: anchor focus.

- H1.1 Press the handoff keys once. Observe speech and braille. Expected: a
  local-control announcement in Windows NVDA speech; the b.note shows Windows
  NVDA content, not leftover Linux cells.
- H1.2 Wait 5 seconds with no keys. Note any unexpected speech or braille.
- H1.3 Press the handoff keys once. Observe speech and braille. Expected: a
  remote-control announcement; braille shows content for the current Linux
  focus presented by Windows NVDA.
- H1.4 Tab probe. Expected: Plain multiline editor, exactly one stop.

### H2. Local keystrokes do not reach Linux

Criterion: handoff isolation. Start: anchor focus.

- H2.1 Press the handoff keys once (to local). Observe as in H1.1.
- H2.2 With the safe Windows focus, press the letter q once. Expected: q
  appears in the Windows window only.
- H2.3 Press the handoff keys once (back to remote). Observe as in H1.3.
- H2.4 Read the Single line editor on the b.note. Expected: it still reads
  "Single editor alpha" with no q and no other change.

### R1. Graceful disconnect and reconnect

Criteria: fresh input after reconnect; no stale speech or braille; no replay.
Start: anchor focus.

- R1.1 Disconnect using the graceful method from P5. Observe speech and braille.
- R1.2 Quiet interval, 15 seconds. Expected: nothing from the Linux session is
  presented by Windows NVDA.
- R1.3 Reconnect and regain remote control per P5. Observe speech and braille
  and note the order and the time taken.
- R1.4 Quiet interval, 15 seconds. Expected: any output describes the current
  Linux focus only; nothing is replayed from before the disconnect.
- R1.5 Tab probe. Expected: Plain multiline editor, exactly one stop.
- R1.6 Press Shift+Tab once. Expected: back on the Single line editor, one stop.

### R2. Orca restart while connected (extended run)

Criteria: fresh input after Orca restart; no replay. Start: anchor focus.

- R2.1 Record the Orca process ID (read-only, section 9).
- R2.2 Restart Orca with the method recorded in P5. Observe speech and
  braille during the restart.
- R2.3 Wait up to two minutes. Record whether the session reconnects by
  itself and whether you must regain remote control. If it does not recover in
  two minutes, record "did not recover" and stop.
- R2.4 Record the new Orca process ID. Expected: it differs from R2.1.
- R2.5 Quiet interval, 15 seconds. Expected: output describes the current
  focus only; nothing from before the restart.
- R2.6 Tab probe. Expected: Plain multiline editor, exactly one stop.

### M1. Held modifier across a graceful disconnect

Criteria: no stuck modifiers after reconnect. Variants, each a separate trial:
M1a Left Shift, M1b Left Ctrl, M1c Left Alt. Start: anchor focus.

- M1x.1 Press and hold the modifier. Press nothing else.
- M1x.2 While holding it, perform the graceful disconnect with the other hand.
  If that is not possible, mark NOT RUN. Do not substitute another method.
- M1x.3 Release the modifier while disconnected (safe Windows focus).
- M1x.4 Reconnect and regain remote control. Observe.
- M1x.5 Letter probe. Expected: a lowercase x appears once. With Shift stuck
  it would be uppercase. With Ctrl stuck the field would select all or a
  browser shortcut would act. With Alt stuck a menu or access key would act.

### M2. Held navigation key across a graceful disconnect

Criteria: no stale key repeat after reconnect. Start: focus in the Plain
multiline editor on its first line, confirmed on the b.note.

- M2.1 Press and hold Down until the caret reaches the third line, then keep
  holding. Observe speech and braille.
- M2.2 While holding, perform the graceful disconnect with the other hand.
- M2.3 Release Down while disconnected.
- M2.4 Reconnect and regain remote control. Observe.
- M2.5 Quiet interval, 10 seconds. Expected: no caret movement, no speech.
- M2.6 Press Up once. Expected: the caret moves up exactly one line, to
  "Plain editor bravo."

### M3. Held modifier across a handoff (extended run, optional)

Only if physically practical. Start: anchor focus.

- M3.1 Press and hold Left Shift.
- M3.2 With the other hand, press the handoff keys once.
- M3.3 Release Left Shift (safe Windows focus).
- M3.4 Press the handoff keys once to return to remote. Observe.
- M3.5 Letter probe. Expected: lowercase x, once.

### U1. Unexpected disconnect and recovery

Criteria: unexpected disconnect and recovery. Start: anchor focus.

- U1.1 Break the connection using the abrupt method from P5. Observe speech
  and braille.
- U1.2 Quiet interval, 15 seconds. Note any output.
- U1.3 Recover. Record whether recovery was automatic or manual, what you did,
  and how long it took. Stop at two minutes if it has not recovered.
- U1.4 If needed, regain remote control. Observe.
- U1.5 Tab probe. Expected: Plain multiline editor, exactly one stop.

### Q1. Queued command then immediate handoff (extended run, race attempts)

Criterion: stale queued shortcuts. This mirrors the race fixed in PR #124.
Up to five attempts, each starting from the anchor focus.

- Q1.n.1 Press NVDA+T once, then within about one second press the handoff
  keys. Observe speech.
- Q1.n.2 Wait 10 seconds with no keys. Expected: no Linux title speech after
  the local-control announcement.
- Q1.n.3 Press the handoff keys to return. Expected: no unrequested title
  speech from Linux.

A live race attempt can find a failure but cannot prove its absence. Record
"no failure observed in N attempts", never PASS.

### Q2. Elements list across a handoff (extended run, exploratory)

Criterion: old focus or script actions do not affect a new activation. The
2026-10-16 audit lists this as unverified. Start: browse mode on the page.

- Q2.1 Press NVDA+F7. Observe the chooser.
- Q2.2 Without choosing anything, press the handoff keys, wait 5 seconds, press
  them again. Observe.
- Q2.3 Record whether the chooser is still shown, whether Escape is needed, and
  what a second NVDA+F7 does. Expected: no action runs from the old chooser
  and focus does not move because of it. The chooser's state afterwards is an
  observation; the audit predicted NVDA+F7 may be ignored until it is dismissed.

### S1. Say All interrupted by a handoff (evidence shared with #58)

Criterion: no stale speech from a replaced session. Start: browse mode at the
start of Reading segment one; record how you got there.

- S1.1 Press NVDA+Down to start Say All. Let it speak for about five seconds.
- S1.2 Press the handoff keys once during speech. Expected: Linux speech stops
  promptly.
- S1.3 Wait 10 seconds. Expected: no Linux speech resumes.
- S1.4 Press the handoff keys to return. Expected: no reading resumes; any
  output describes the current focus only.
- S1.5 Read the current line. Record which Reading segment you are on.

### B0 to B3. Braille after a transition

Criterion: no stale braille routing or panning; Windows NVDA is the presenter.
Run once after R1 setup as follows, and again after R2 if R2 was run. Routing
correctness itself belongs to #59 and #72; these steps only check for stale
state.

- B0.1 In browse mode on the Reading segment one paragraph, press the b.note
  pan-forward key once. Record the first characters now shown.
- B0.2 Perform R1.1 to R1.4 (graceful disconnect, quiet interval, reconnect,
  quiet interval). Do not press any other key.
- B1 Read the b.note without pressing anything. Expected: content for the
  current Linux focus presented by Windows NVDA. It must not be the window you
  panned to in B0.1 unless NVDA rebuilt it for the new session, and it must not
  be blank or leftover raw cells.
- B2 Press the pan-forward key once. Expected: the display advances one window
  from what B1 showed.
- B3 Press one routing key above a known character. Expected: the caret lands
  on the character under that cell in the current text, with no jump to a
  position from before the transition.

### M4. Held Shift across an Orca restart (extended run, higher risk)

Run only after R2 is recorded and Miriam gives an explicit go-ahead at that
moment. Orca stopping while Shift is injected may leave Shift held in the
Linux X session until released. Recovery is in section 3.

This case needs a second operator, or an assistant-run restart approved by
Miriam, because the restart command cannot be typed while one hand holds Shift
and the other keeps remote control. If neither is available, mark NOT RUN.

- M4.1 Press and hold Left Shift in remote control.
- M4.2 Restart Orca as in R2.2 at Miriam's signal.
- M4.3 Release Left Shift. Reconnect and regain remote control if needed.
- M4.4 Letter probe. Expected: lowercase x, once.

An abrupt Orca termination is not part of this procedure. Add it only with
Miriam's explicit approval.

### F1. Key injection or release failure: not run by design

Criterion: failed key injection or release. Status: NOT RUN, and not
executable as a live test here.

Reason: the automated coverage uses a fake backend, upstream
`LocalMachine.send_key` does not report injection outcome, and inducing a real
failure would mean disabling or breaking X11 injection on the active desktop.
Do not attempt it by stopping xdotool or ydotool, changing X permissions, or
similar. A live method needs a separate approved design that is reversible and
does not touch the active desktop. Until one exists, #61 checkbox 4 cannot be
fully satisfied, and only Miriam can decide whether to accept the automated
model for this item.

If a real injection failure happens naturally during another case, record it
as an observation. The optional trace in section 12 would show it as a
rejected or raised forward or a failed reset.

## 9. Optional light read-only Linux checks

Only when Miriam asks, only with an approved tool session, and never during a
step: they must not add input or load.

- Orca process ID: `pgrep -af orca` (read-only).
- Focus and lock indicators on the existing XFCE session:
  `python3 diagnostics/x11/live_x11.py --display :0 --target firefox` and
  `python3 diagnostics/x11/live_x11.py --display :0 --watch-locks 30`.
  See [live-x11-diagnostics.md](../live-x11-diagnostics.md). Do not use the
  tool's `--key` options or `--activate` during this procedure.

These do not show what Windows NVDA spoke or what the b.note displayed.

## 10. Recording and classification

Record per step: exact keys; Linux application and focus; expected speech and
braille; observed speech and braille (for braille, the text read and where);
differences from local Orca, including any audible Linux-side speech; session
state before and after; reproducibility (times tried, times seen); and whether
any unplanned input occurred.

Result values: PASS (observed matches expected, no unplanned input), FAIL
(observed contradicts expected, no unplanned input), INCONCLUSIVE (unplanned
input, missing observation or ambiguous), NOT RUN. For race attempts use "no
failure observed in N attempts".

Do not substitute local Orca speech, Linux-side checks or braille for Windows
NVDA speech. Physical braille stays unverified until Miriam confirms what she
read on the b.note.

## 11. If a case fails

1. Stop. Do not run further transition cases until Miriam decides.
2. Clear any stuck modifier per section 3 and record whether it cleared.
3. Record the exact sequence, state before and after, and reproducibility. Try
   to reproduce once with the same single input source.
4. Do not change code in the session. File a focused issue for a confirmed
   live defect. The fix starts with a failing regression test, then the
   smallest fix, in a separate PR. No speculative fixes.

## 12. Optional metadata trace (not required)

[live-trace-diagnostics.md](../live-trace-diagnostics.md) describes a
metadata-only input trace enabled by `LINUX_RDACCESS_TRACE=1` in Orca's
environment, which requires restarting Orca with that variable set. That
changes how the production Orca is started, so it needs Miriam's explicit
approval and is not part of the core run. If used, it can show for H, R, M and
Q cases a `reset` record with an empty `failed` list and a new `gen`, no
`stale_skipped` actions executing, and any rejected or raised forward. Note:
that document names `tools/summarize_input_trace.py`; the file is now at
`tools/diagnostics/summarize_input_trace.py`.

The Windows companion routing trace (`nvda-braille-trace`) is not needed here
and must not be enabled for #61.

## 13. Mapping to #61 and cross-issue evidence

#61 checkboxes and the cases that address them:

1. Fresh input after reconnect and Orca restart; no stuck modifiers, duplicate
   activation or cross-session replay: R1, R2, M1a to M1c, M2, M3, M4.
2. Stale queued shortcuts and old focus, script or window actions never affect
   a new activation: Q1, Q2, and the probes in the other cases.
3. No stale braille routing or panning, or speech, from a replaced session;
   Windows NVDA is the presenter: S1, B0 to B3, and the braille and speech
   observations in H1, R1 and U1.
4. Intentional handoff, unexpected disconnect, recovery, and key-injection or
   release failure: H1, H2, U1, M3; F1 stays NOT RUN until a safe method exists.
5. Record exact keys, app and focus, expected versus observed speech and
   braille, local Orca differences, session state and reproducibility: the
   results template, for every step.

Closure: only Miriam decides. A fully passing run still leaves #61 open if F1
is NOT RUN, unless she explicitly accepts that.

Cross-issue evidence: some steps also bear on other issues (S1 on #58; B3 on
#59 and #72; modifier steps on #57). Note this in the results file only. This
procedure does not comment on, update or close #57, #58, #59 or #72, and a
passing #61 session does not satisfy their own acceptance criteria.
