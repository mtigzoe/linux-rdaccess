# Live accessibility acceptance session: 2026-10-18

Issues: [#57](https://github.com/mtigzoe/linux-rdaccess/issues/57),
[#59](https://github.com/mtigzoe/linux-rdaccess/issues/59),
[#61](https://github.com/mtigzoe/linux-rdaccess/issues/61).

Status: preparation complete to the extent described below; no live gesture
has been attempted in this session. All three issues remain open. This record
contains no new physical acceptance or production defect claim.

Date uses Miriam's America/New_York timezone. Branch:
`docs/live-acceptance-2026-10-18`. Repository review baseline:
`6d24df2179f7484f4a01a66a708afc24dde1173e` (`origin/main`, fetched this session).
The main checkout was clean and already at that commit. This file is maintained
in a separate worktree; existing worktrees and Claude's work were not changed.

## Safety and evidence rules

Miriam performs each physical action. The assistant gives one test at a time,
then waits for her written observation. No response means no result. Preserve
her exact wording, including partial or unexpected braille, except that private
content must not be copied into this public record.

Before a disruptive action, obtain permission for that specific action, explain
the affected computer and possible loss of access, and establish recovery.
Previous sessions' authorization does not authorize this session. No agent
desktop input, focus movement, settings change, installation, restart,
disconnect or reconnect has been performed during preparation.

Do not enable diagnostics implicitly. Local test API access requires fresh
five-minute NVDA Tools authorization. Routing traces additionally require the
diagnostics checkbox and explicit permission. The separate one-shot message
routing permission does not authorize general input. No test APIs, routing
traces, full accessibility trees or content-bearing logs were read here.

Audible speech is UNVERIFIED unless a reliable observation is available.
Braille, a queued speech call and silence do not establish audible speech.
Label presentation as Windows NVDA semantic braille, Orca temporary status,
raw Orca cells, or unknown only to the extent supported by current evidence.
An Orca-generated status message may be rendered using Windows NVDA's native
message presentation; record content origin and renderer separately.

Cyber's issue #79 build, its worktrees and its services/resources were not
accessed or changed. Keep subsequent checks lightweight and stop if stability
or accessibility is affected. No deliberate crash, injection failure, network
interruption or held-key transition is authorized by this record.

## Installed baseline from read-only inspection

| Component | Evidence this session | Limitation |
| --- | --- | --- |
| Windows | Windows 11, reported by Miriam | OS build not collected |
| NVDA | Installed executable product version 2026.2; file version 2026.2.0.57664 | Disk metadata does not attest loaded code |
| NVDA process | One process observed, PID 19184 | Process executable path was unavailable from this query |
| NVDA keyboard layout | Saved main configuration says desktop | Active profile and configured NVDA modifier keys not yet confirmed |
| Windows Linux companion | Installed manifest 20261014.0.2 | Main builds 20261014.0.4; active companion versus legacy integration not attested |
| RDAccess | Installed manifest 20261012.0.5 | It can own the Linux integration while the companion is inactive |
| NVDA Remote Access | Reported installed by Miriam | Exact running version/backend and current control/connection state unverified |
| Physical display | Eurobraille b.note 80, reported by Miriam | Connection method, active driver, cell count, translation and tether not confirmed; saved display setting is auto |
| Cyber OS | Release metadata: Linux Mint 21.3 | Active XFCE version not collected |
| Orca | Package metadata: 42.0-1ubuntu2 | Exact loaded modules unverified |
| Linux controller | Installed remote_controller.py marker v121 | Main generated controller is v123 |
| Linux installation source | Installed remote_access.py compatibility marker v121 | Marker alone does not prove full source identity or loaded runtime |
| AT-SPI | python3-pyatspi 2.38.2-1; libatspi2.0-0 2.44.0-3 | Package metadata only |
| Inspection access | Existing batch-mode SSH with strict host-key checking succeeded | No desktop/control/connection state inferred from SSH |
| Remote Desktop Commander | Device inventory reported both Cyber and Windows laptop offline | No connection repair or device setting change attempted |

Static SHA-256 comparison found ten of eleven compared tracked companion
Python files equal to main; `remoteAccessSemanticBraille.py` differs. The
installed Linux Orca adapter, AT-SPI model and caret diagnostics equal main;
installed runtime `remote_access.py` differs. These are disk comparisons only.

The controller and companion on disk are older than reviewed main. In
particular, v121 does not establish deployment of the later v122 lifecycle
change or v123 Caps Lock capture fix; companion .2 does not establish deployment
of .3 queued document-route ownership or .4 one-shot message routing. We have
not proposed or performed an update. Initial observations, if authorized, apply
to the installed setup and cannot accept these newer changes.

## Repository and historical evidence reviewed

Read issue bodies and all available comments: #57 (six), #59 (seven), #61
(five). Read the behavior contract, Orca source-reference guidance, NVDA Remote
backend documentation, companion documentation, relevant tests and audits.

| Issue | Existing software evidence, not rerun this session | Remaining human/physical acceptance |
| --- | --- | --- |
| #57 | Direct commands and native title adapter; Insert/Caps ownership, pass-next, locks, layouts, capture, repeats and session/focus guards. PR #82 fixed non-web letter suppression. PR #140 advances controller v122 to v123 for rejected Caps capture ownership/retry. | Actual title/input-help/Elements List, handoff, layouts/modifiers/locks, capture and exit, held/repeated/released keys, pass-next, focus changes and natural rejection recovery through Windows NVDA. |
| #59 | Semantic snapshots/TextInfo, Unicode mapping, stale context rejection, message restoration, pending native update before routing, queued document/message route ownership; mocked NVDA, source-reference, relay and isolated Linux checks. | Exact tactile names/roles/states/values, editing caret and cursor, pan boundaries, route/home, long text, queued focus changes, status restoration, raw-overwrite prevention and reconnect on the b.note. |
| #61 | Genuine isolated relay/controller reconnect and held-Shift cleanup at a test injection boundary; queued title teardown regression; session-generation/lifecycle tests and isolated Orca restart harness. | Current installed Windows NVDA and physical keys/display through handoff, reconnect, modifier cleanup, fresh navigation, duplicate/stale input and presentation, and recovery after approved restart/interruption. |

Historical observations remain historical: terminal typing recovery, limited
input-help message appearance/return, physical left-pan showing Linux content,
and legacy-path handoff state changes. None is carried forward as this
session's PASS. Earlier ambiguous caret movement and overflowing/mixed traces
do not identify a new defect or prove caret preservation.

Expected gaps are not automatically regressions: forwarded Insert+N is consumed
without opening a remote NVDA menu; the Windows NVDA menu requires local
control. NVDA+F7 uses a Linux category chooser/native Orca list where supported,
not NVDA's Windows Elements List dialog.

The installed Orca 42 default script's `presentTitle()` calls `presentMessage()`
for the generated title. Its native braille flash depends on braille or the
braille monitor being enabled and `enableFlashMessages` being enabled; duration
depends on the existing flash settings. These method bodies were read without
importing them into the active process. Actual settings and title presentation
remain unverified. Windows NVDA message policy is an additional presentation
constraint when the semantic message extension is negotiated.

For presentation attribution, semantic capability negotiation alone does not
prove a rendered snapshot or physical receipt. A false negotiation flag alone
does not prove active raw output. Authenticated status may come from legacy
RDAccess and always leaves physical braille unverified. No such status was
requested this session. Current title/braille source therefore remains unknown.

## Coordination with Claude's #61 procedure

Reuse [Claude's merged procedure](issue61-live-acceptance.md) and
[its results template](issue61-live-acceptance-results-template.txt), from
[PR #145](https://github.com/mtigzoe/linux-rdaccess/pull/145), prepared against
`b4d741f`. No replacement #61 procedure is created here. When #61 begins, use
its step identifiers and record session-specific observations in that template.

Apply Miriam's current instructions while using it: written and tactile
observations do not establish audible speech; every disruptive operation needs
its own specific permission; split combined actions into individual prompts
and records. Establish safe local Windows focus separately before local typing.
Record actual timing for race attempts; no failure observed is not proof of
absence. Unchanged content across reconnect cannot identify stale versus rebuilt
output. Distinguish a browse cursor from an editing caret, and do not infer
absence of held Down repeats from a caret already at the final line. Verify
Say All against the active layout before prompting it. These are session
interpretation limits, not modifications to Claude's procedure.

The procedure's INCONCLUSIVE maps to UNVERIFIED in this session record.
NOT RUN maps to UNVERIFIED when unattempted, or BLOCKED when a specific
dependency prevents a required check. Preserve the original procedure label
alongside that mapping. F1 deliberate injection/release failure is blocked by
the absence of an approved safe method and must not be induced. Record a
naturally occurring rejection if one occurs; do not manufacture one.

## Proposed first keyboard case (not authorized or attempted)

- Issue: #57.
- Test ID: K57-01, single title query on the installed baseline.
- Date: 2026-10-18; execution time not applicable (not run).
- Windows NVDA: installed 2026.2; loaded version not independently attested.
- Linux controller: disk v121; loaded version unverified; main v123.
- Braille display and connection: Miriam reports Eurobraille b.note 80;
  connection method unconfirmed.
- Linux application/control: awaiting Miriam; use an already-open public,
  nonsensitive Mousepad window if available. Do not open or move focus merely
  to satisfy this proposal without separate agreement.
- Exact gesture: NVDA+T once, using the already-configured NVDA modifier;
  no other gesture in this observation. Modifier setting must be confirmed.
- Preconditions: Miriam identifies current application/control, confirms Linux
  control is already active and input help is off, and agrees to this single
  query. Any needed handoff/setup is a separate, specifically approved step.
- Expected behavior: Linux window title is requested once through Orca; no
  application letter T, focus/caret change or stuck key. Record any title/status
  braille exactly; current message settings may affect its visibility. A lack
  of braille alone is not evidence of an audible-speech failure.
- Observed behavior from Miriam: no observation supplied this session.
- Presentation: unknown; semantic braille, temporary status and raw-cell
  attribution have not been established for this session.
- Audible speech: UNVERIFIED; no reliable observation collected.
- Unintended application key/focus/caret change: UNVERIFIED.
- Stuck keys: UNVERIFIED; do not send an extra probe within this observation.
- Result: UNVERIFIED (proposed only, awaiting readiness and specific agreement).
- Reproduction count: 0 attempts, 0 observations.
- Authorized sanitized diagnostics: none collected.
- Effect/recovery to explain before execution: Windows output may briefly
  change while Linux processes the title query; no planned disconnect/restart.
  If unexpected behavior occurs, release all keys and stop. If access is lost,
  Miriam's normal Insert+Alt+Tab local-control recovery is available; do not
  have the agent perform it. Reconnection/restart requires separate permission.

## Session tally and validation

PASS: 0. FAIL: 0. BLOCKED attempted cases: 0. UNVERIFIED recorded case: 1
(K57-01, not attempted). Remaining acceptance cases are unattempted and are
not counted as test executions. F1's design blocker is documented above.

New confirmed defects requiring fixes: none. New physical/live verified
behaviors: none. Automated suites were reviewed, not rerun; no new software
test PASS is claimed. This documentation-only change requires content/link
inspection and git diff checks, not active-desktop or production tests.

Keep #57, #59 and #61 open until Miriam explicitly confirms acceptance. No
issue or unrelated production file was modified. CI is not polled or awaited,
and this session authorizes no merge.
