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

## Prepared companion .6 diagnostics

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

The .6 package has **not been installed or physically tested**. Installation
and NVDA reload require separate explicit authorization under the test-session
workflow; the agent has prepared the source/package for that review. Keep #59
and #72 open. The next useful check pairs this opt-in trace with the numeric
Linux observer and one two-press message-dismissal interaction.

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

Linux behavior was not changed or retested as a suite. No GitHub Actions polling
or merge. No live .6, audible-speech or physical-device acceptance is claimed.
