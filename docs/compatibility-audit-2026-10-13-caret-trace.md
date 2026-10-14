# Follow-up caret investigation — 2026-10-13

Related: #59, #72 and PR #85. The original reported **6 → 9** movement remains
unattributed. The .5 queue fix has source-backed regression coverage; it is not
proof of the cause of that historical live movement.

## Installation and live observations

The user reported installing and launching companion **20261013.0.5**. Its
manifest identified .5 and **all thirteen packaged Python files matched the
installed files**. The current status schema does not independently report the
loaded companion version. Fresh user authorization and `start-all` subsequently
confirmed Linux readiness, a connected Windows transport, an attached bridge,
negotiated semantic braille/message support and, at some checks, active control.
The user performed the gestures. Control was local at other prechecks; the later
manual handoffs and actual gestures were not protocol-traced on Windows.

A bounded read-only comparison confirmed the exact public Mousepad fixture
**`Alpha Barlio Charlie`**, twenty characters. Only equality/counts were emitted;
the observer did not serialize desktop text. C has zero-based offset **13**.
Every completed observation below retained the original focused text object and
reported zero dropped caret events.

| Follow-up check | Numeric/user evidence | Interpretation |
| --- | --- | --- |
| Initial intended input-help entry | 60.090 s, 0 → 14, 31 caret events. User confirmed arrow keys and routing as well as input help on. | Mixed navigation; cannot isolate input help or routing. |
| Idle window before an exit prompt | 20 → 20, no caret events. Window ended before the prompt. User later reported one input-help-off press. | No gesture acceptance claim from this expired window. |
| Isolated input-help entry | 60.076 s, 20 → 20, no caret events. User confirmed input help on, one gesture after the prompt; response arrived during the window. | Limited observed caret preservation for this one entry. Windows handoff/runtime help state was not independently traced. |
| Intended C-key message dismissal | 60.081 s, 20 → 13, fifteen caret events. User confirmed visible-message dismissal/line restoration without C speech, then confirmed extra navigation/routing. | User-confirmed display restoration; caret preservation and direct C routing are unverified in this mixed trace. |
| Simplified two-press check | 60.081 s, 5 → 20 at 6.731 s, then 20 → 7 at 14.720 s. The first movement preceded the prompt. User confirmed both NVDA+1 and one routing press occurred after the prompt, input help turned on, the message was visible, the line returned, and there were no other test presses. | **Reported caret-preservation failure within the two-press check**. The later 20 → 7 is relevant; which operation caused it is still unisolated. The earlier 5 → 20 is not attributed to those presses. |

Additional readbacks changed between windows, including 9 → 0 and 14 → 20;
those transitions were not recorded and have no assigned cause. The admission
of other inputs in two follow-up traces does not alter the user's earlier .4
statement that the original visible-message press had no other caret moves.

No Desktop Commander, agent keyboard/clipboard input, agent NVDA/Orca restart, driver
change, active runtime injection or broad speech-log collection was used.
Expired Windows authorization was not bypassed; further prompted gestures waited
for fresh user authorization. The read-only Linux observers did not renew it.

## Writer-monitor limitation

A temporary accessibility-bus monitor matched only `org.a11y.atspi.Text`
`SetCaretOffset` calls for the original Mousepad target and emitted bounded
numeric offsets/times and a writer category. An isolated private-bus test
verified one numeric call and that the monitor stayed connected, without GUI
input. Later live windows also reported the monitor connected at completion.

However, a read-only `GetApplicationBusAddress` query confirmed that Mousepad
offers a **direct application channel**. Installed libatspi is **2.44.0-3**;
[the matching upstream 2.44.0 source](https://github.com/GNOME/at-spi2-core/blob/f38e40e8685400ddb66759aa009e18c12c898de4/atspi/atspi-misc.c)
opens such a channel and uses it for application calls. Those calls bypass the
accessibility-bus monitor. Therefore an empty call list **cannot exclude an
Orca caret write**, and no writer attribution is claimed for these live traces.
No peer address, raw process arguments, object identifiers or text was emitted.

## Independent alternative mechanisms

An isolated replay used the existing semantic-routing/Say All test harness,
with fake caret 6, requested route 7 and native Say All current offset 9.
Input help consumed the routing request without a direct caret write. The native
cancel callback then set the fake caret to **9**. This is not live evidence.
The replay's `__sayAllProgressCallback` AST exactly matched installed Orca
**42.0**, package **42.0-1ubuntu2**. Native cancellation can therefore produce
the same numbers without applying a requested routing offset; this does not
identify the original cause or justify overriding Orca's native placement.

Read NVDA source **1406f9f8a04eb50f7317af87aba3a9d439c2a772**:

- [Remote keyboard forwarding](https://github.com/nvaccess/nvda/blob/1406f9f8a04eb50f7317af87aba3a9d439c2a772/source/_remoteClient/client.py)
  calls `_dismissLocalBrailleMessage` for forwarded key events, including releases.
- [Native local message ownership/dismissal](https://github.com/nvaccess/nvda/blob/1406f9f8a04eb50f7317af87aba3a9d439c2a772/source/_remoteClient/localMachine.py)
  marks a shown native message as local UI and can dismiss it through that method.

A source-backed isolated test executes those native ownership/dismissal methods
and the native routing script: Remote Access dismissal ends a Linux-owned
message, then a later fresh route sends offset 9. The prepared diagnostic trace
distinguishes that sequence from a guarded message route or an expired queued
route. This establishes another possible logical-buffer sequence, not physical
display timing or the cause of either live movement. Saved BrailleExtender
configuration said `routingCursorsEditFields = normal`; active profile/runtime
routing settings were not independently read.

## Companion .6 diagnostics

Build **20261013.0.6** retains the .5 queue fix and adds a separate, unchecked
numeric-routing checkbox in the existing five-minute authorization dialog.
Collection stays in memory, caps at twelve records, and stops/clears with expiry,
revocation, profile/desktop transitions, shutdown or new consent. It retains
only fixed event/state enums, booleans, relative times, and bounded routing/caret
positions. Text, node/gesture identifiers, paths, relay data and ordinary typing
are excluded. `dropped` discloses overflow or unrecordable metadata.

The trace observes the existing routing decision, native Remote Access message
dismissal, Linux message ownership, incoming caret snapshots, and semantic caret
send calls. It preserves original dismissal return values/exceptions and restores
its observer only if another add-on has not replaced it. Disabled or faulty
diagnostics must not change routing. `linux_owned` describes cached ownership
for the current handler/session/control generation; `buffer` separately shows
whether the message or main buffer is active. `capture` records NVDA's native
input-help/gesture-capture flag, not an independently queried Orca help state.
`same_focus` compares a caret request/snapshot with the current focus; it is null
for other events rather than inventing a target comparison.

`nvda-braille-trace` uses the authenticated, argument-free version 2
`braille_trace` read. Version 1 status/connect/cancel and descriptor formats remain
unchanged. The read cannot enable collection or perform input/connection actions.
Event `elapsed_ms` and `snapshot_ms` use the same Windows capture clock, allowing
approximate alignment with a paired Linux observation; they are not physical
display timestamps. A `caret_sent` event means the send call returned, not that
Linux applied the offset. Delegated raw routes, other add-ons' emulation, native
Orca writes and incomplete traces require additional evidence.

The user chose to install .6 and restart NVDA themselves, then reported ready.
The installed manifest and **all fourteen packaged Python files matched .6**.
The running endpoint accepted the version 2 diagnostic read and returned
`available: true`; this confirms the diagnostic feature is active, although the
status schema still does not independently report the loaded build number.
Connection, bridge attachment and semantic message support were confirmed.

Two preparation sessions filled the twelve-record limit before an instructed
gesture test. Their reads reported **168** and **132** dropped records. Linux
initially had a terminal focused, so no test prompt was issued. A later bounded
read confirmed the exact twenty-character Mousepad public fixture, caret **20**.
No .6 routing or message-dismissal acceptance is claimed from these incomplete
preparation traces. Preparation must finish before recording is authorized;
revoking the existing session and granting new consent clears the trace. Trying
to authorize again while it is still active returns busy and does not reset it.

After a later fresh grant, authorization, connected transport and active Linux
control were confirmed before the test prompt. The trace contained three setup
records and no drops; the Linux observer started at caret **20**. Its first
**60.134 s** window ended at 20 with no caret events. A read after that window
still contained only the three setup records. A second observation window was
started for the same requested interaction, explicitly without asking the user
to repeat any presses. The windows had a gap; this was not continuous capture.

The second **60.077 s** window retained the original focus and recorded
**20 → 18 → 15 → 13 → 9 → 5 → 2 → 6**, with zero dropped Linux events. Windows
retained three routing decisions, for indices **19**, **12**, and **74**. Each
decision recorded `buffer: main`, `linux_owned: false`, `capture: false`,
`control: true` and `route_native`. The last retained route was followed by
`caret_sent` with offset **18**. The Linux offset-18 event is close in time under
approximate clock alignment; this correlates a main-buffer semantic request
with a Linux movement, without proving delivery solely from the send call.
No accepted Linux-message `message_shown` record precedes these retained routes.
The final Windows snapshot reported **29 dropped records**, so later routing
and message behavior cannot be reconstructed from it.

The user said the instructions were unclear and confirmed **arrow keys,
panning and routing** during this recording. This is mixed navigation, not an
isolated two-press reproduction or a physical message-dismissal acceptance.
A later bounded read found caret **15**; the unrecorded 6 → 15 transition has no
assigned cause. An earlier **60.128 s** idle window at 20 had no gesture prompt
because Windows authorization was inactive, and establishes no gesture result.

Keep #59 and #72 open. The next check should use a single ordinary physical
route to the public fixture's C at offset 13 after input-help-off preparation.
For #72, first capture message entry/timeout alone and verify Linux message
ownership before attempting routing dismissal. No agent installation, NVDA
restart or test input was performed.

## Validation

- Full Windows companion suite: **271 tests passed**, Python 3.13,
  `configobj==5.0.9`, including source-backed NVDA routing/message methods and
  isolated real Windows authentication/pipe tests.
- Launcher/orchestration suite: **10 tests passed**, including the read-only
  diagnostic command and unsupported-endpoint fallback.
- Ruff **0.16.4** source checks passed using the companion policy for its shared
  wire modules and focused import/syntax checks for launcher changes.
- Ruff format validation and `git diff --check` passed.
- Companion .6 built successfully: **18 archive entries, 14 compiled Python
  modules, 52,585 bytes**; archive CRC and unique-path checks passed.
  SHA-256: `e144784afbc46ad0341cd6c7d15936b3fece17f948380e9ce5dd6baa9c7a64b5`.

Linux behavior was not changed or retested as a suite. The former Linux checkout
path `/home/miriam/linux-rdaccess` was absent during this follow-up, so its
previous revision is not a current installed-runtime verification. A repeat of
the temporary AST comparison could not read its fixture at that missing path;
the earlier successful comparison remains historical evidence only.

Only documentation changed during this installation/live follow-up;
`git diff --check` passed, and unchanged successful suites were not repeated.
No GitHub Actions polling or merge. No isolated .6 gesture, audible-speech or
physical-message acceptance is claimed.
