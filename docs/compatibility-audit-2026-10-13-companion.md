# Companion issue audit and braille regressions — 2026-10-13

All seven open linux-rdaccess issues and their discussions were reviewed against
main and the existing companion PR #78. Earlier fixes in Linux PRs #69, #73,
#75 and #77, and Windows rdAccess PRs #10, #12 and #13 were not reimplemented.
Two additional defects were reproduced in the standalone Windows companion.
Their corrections are **Fixed (automated-tested)**; the live acceptance issues
remain open.

## Confirmed defects

### Retained braille objects can send stale activation and caret requests

Related trackers: #59 (routing) and #61 (session/control lifetime).

Each `RemoteA11yObject` previously received the bridge's unguarded bound action
and caret senders. An old NVDA TextInfo or object retained after a newer focus
snapshot could still send requests. Reusing an object ID after a new hello did
not make the old reference safe. Local control, replacement transports and a
disconnect before fallback were also missing from this outbound check.

The reproduction retains an object and TextInfo, changes the snapshot or
activation, then calls `doAction` and `_setCaretOffset`. The old bridge emits
both `lrd_a11y_action` and `lrd_a11y_caret`. The correction binds these callbacks
to the displayed object map, semantic session and control generation, and
checks current transport identity/connection and remote keyboard control before
sending. Current object actions and routing continue to send normally.

Regressions cover same-ID snapshot replacement, new-session ID reuse, return
to local control, return to remote control, transport replacement, disconnection,
focus replacement and reconnect. Existing fallback/termination rejection is
also retained. This does not change the wire protocol or Linux Orca handlers.

### Same-ID focus updates retain outdated Linux ancestry

Related trackers: #59 (presentation) and #60 (application focus/context).

The bridge rebuilt braille regions only when focus ID changed or the remote
region was missing. When the same object moved to another dialog or lost its
parent, the old context region stayed in the buffer. When an ancestor's label
changed, rebinding its object did not regenerate the rendered text: NVDA's
`handleUpdate(focus)` updates the focus region, rather than all ancestors.

Regressions keep the focus ID unchanged while replacing/removing its parent or
renaming the dialog. The old code displays the previous `Settings` context.
The correction compares ancestry identity and presentation properties before
rebinding regions, and rebuilds context when they change. Unchanged ancestry
uses the existing update path and preserves the panning window. Tests use the
real NVDA focus-context functions from the local NVDA source reference with
runtime leaves stubbed; this is not a physical-device test.

Modified implementation: `nvda-addon/addon/globalPlugins/linuxRdAccess/remoteAccessSemanticBraille.py`.
Regressions: `nvda-addon/tests/test_remoteAccessSemanticBraille.py` and
`nvda-addon/tests/test_semanticBrailleContext.py`. The package is versioned
`20261013.0.1`; build metadata and installation examples identify that version.
Linux implementation and legacy root wrappers are unchanged.

## Open issue classification

| Issue and title | Classification | Evidence and remaining work |
| --- | --- | --- |
| #57 — Live validation: NVDA keyboard commands and modifier ownership | **Needs live testing** | Existing direct-command/layout/lock tests reviewed. No new confirmed keyboard defect; bounded real keyboard tests were blocked before input. |
| #58 — Live validation: Windows NVDA speech, interruption and Say All | **Still open** | User reports “Tab” on Tab but not Shift+Tab, and Orca's “push button” wording. Speech still forwards Orca text; Tab's source is unresolved. Interruption/Say All remain unverified. |
| #59 — Live validation: physical braille routing and Windows NVDA presentation | **Still open: physical failure reported** | Eurobraille b.note left pan still showed a Windows VS Code label. Two further BrailleExtender interactions reproduced and corrected in build .2; installation and physical confirmation are pending. |
| #60 — Live validation: Linux Mint application accessibility matrix | **Needs live testing** | Limited Windows-origin Firefox Tab delivery/focus changes observed. Complete application navigation, speech, braille and routed caret acceptance remain incomplete; VS Code failure is tracked in #79. |
| #61 — Live validation: disconnect, reconnect and stale input lifecycle | **Needs live testing** | Retained outbound object commands now expire. Real handoff/reconnect, held modifiers and physical routing still need acceptance. |
| #72 — Live NVDA braille acceptance for Linux #69 and Windows rdAccess #9 | **Needs live testing** | Existing temporary-message handling preserved. Physical timeout, panning/routing, local-control and reconnect checklist remains incomplete. |
| #76 — Stage 2: opt-in local NVDA control IPC for AI test sessions | **Still open** | Standalone companion is installed/active; authenticated connected status and expiry were observed. Remaining integration review and end-to-end acceptance are incomplete. |

Do not close these trackers based on the automated results below.

## Automated validation

- Baseline `c01456b`: running the seven new tests against the prior bridge in an
  isolated temporary module produced **11 expected failing checks in six tests**,
  with no test errors. The unchanged-context control passed; fallback and
  termination rejection were already working.
- Native Windows, Python 3.13: **200 companion tests passed**, including the
  seven added tests, actual isolated DPAPI/ACL/overlapped pipe tests, packaging,
  semantic braille, plugin coexistence and consent lifecycle coverage.
- Native Windows, Python 3.13: **39 launcher/start-all/controller/import/layout
  compatibility tests passed**. Argparse errors printed by rejection tests are
  expected, not suite failures.
- Linux Mint host, installed checkout `ac1dbdb`, Python 3.10: **130 related
  braille and TCP protocol loopback tests passed**, with no skips, after native
  AT-SPI was preloaded. Tested modules: `test_nvda_native_braille`,
  `test_braille_input_help`, `test_temporary_braille_messages`,
  `test_braille_display_lifecycle`, and `test_nvda_remote_loopback`.
  These are automated tests of the unchanged Linux path, not GUI acceptance.
- The initial Linux invocation ran 126 tests and had one GI initialization error
  (`PyGLibUserDirectory` enum re-registration) and a consequent long-text
  loopback assertion failure. Loading native `gi.repository.Atspi` before test
  mocks avoids the initialization contamination. No production GI fix is claimed.
- Companion Ruff check and format check, and `git diff --check`: passed.
  The first `python -m ruff` attempt encountered a uv temporary Scripts-path
  error; invoking the installed `ruff` executable through uv succeeded.
- Companion package built and ZIP/source/manifest contents verified. It was not
  installed into the active NVDA session.
- Full Linux/X11/GUI application suites were not run. GitHub Actions are left
  to run automatically; do not wait for them or merge PR #78.

Linux validation preloads AT-SPI before importing mocked test modules:

```python
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
import unittest

modules = [
    "tests.unit.braille.test_nvda_native_braille",
    "tests.unit.braille.test_braille_input_help",
    "tests.unit.braille.test_temporary_braille_messages",
    "tests.unit.braille.test_braille_display_lifecycle",
    "tests.integration.test_nvda_remote_loopback",
]
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(modules))
raise SystemExit(not result.wasSuccessful())
```

## Readiness and live limitations

`doctor` and `status` reported Windows NVDA running, SSH reachable and Linux
configuration ready. Read-only SSH confirmed installed Orca **42.0**. Plain SSH
`linux-rdaccess status` was not on the noninteractive PATH; the existing
`/home/miriam/.local/bin/linux-rdaccess status` command succeeded. No Orca restart
or configuration change was made.

After the user activated a fresh five-minute session, `nvda-status` and
`start-all` returned authenticated connected status, semantic negotiation and
existing-session reuse. Remote keyboard control was **false** at the planned
handoff. These responses did **not** establish standalone companion activation:
NVDA's log showed `Linux companion inactive: RDAccess already provides the Linux
integration`, and bridge callbacks were from `globalPlugins.rdAccess.handlers`.
The inactive companion and legacy owner were not disabled or replaced.

The computer-use helper could list Windows windows, but NVDA Viewer
accessibility was limited by Windows integrity. Inspecting the existing Firefox
test window then stopped Computer Use because its Windows browser URL policy
was unsupported. **No handoff, navigation, keyboard injection, or other UI input
was sent.** The restriction was not bypassed through another automation method.
Physical braille was never marked PASS.

Next acceptance requires explicit approval to disable the older RDAccess
development add-on, install the prepared companion and restart NVDA, followed by
a fresh five-minute authorization. Repeat the issue-specific keyboard/speech and
physical braille checks using an approved supported input path. A connected
endpoint alone must not be treated as evidence that the intended add-on is active.

## Follow-up authorized handoff check

At approximately 09:25 America/New_York on 2026-10-13, after the user relaunched
NVDA and authorized another five-minute session, authenticated status reported
connected transport, remote control active and semantic braille negotiated.
The installed companion manifest now identified **20261013.0.1**, but the new
NVDA log again reported the companion inactive because RDAccess provided the
integration. The consent service and braille callbacks were still owned by
`globalPlugins.rdAccess`, so these results are **legacy integration** evidence.

A read-only Linux focus probe confirmed the existing `:0` desktop and focused
GNOME Terminal. No navigation or text input was sent to that terminal. The
Windows File Explorer input target was observed before each bounded action.
Two actual `Insert+Alt+Tab` gestures through Windows NVDA Remote changed the
authenticated control state **remote → local → remote**, preserving the
connected transport and negotiated semantic braille. NVDA's log showed the
corresponding queued `Controlling local computer` and `Controlling remote
computer` announcements. This establishes the observed control-state handoff;
it does not establish audible sound or physical braille output, held-key
cleanup, a reconnect, or live acceptance of the companion's corrections.

Remote control was restored to its original state. Approval to disable the
legacy RDAccess add-on and restart NVDA was requested; no add-on state was
changed during this check. The previous browser-tool restriction was not
bypassed: this check used the supported Windows File Explorer target, with no
browser UI automation.

## Standalone companion activation after explicit approval

The user explicitly approved disabling legacy RDAccess and restarting NVDA.
At 09:34 America/New_York on 2026-10-13, the legacy add-on was disabled through
NVDA's persisted add-on state while NVDA was stopped, then NVDA was started
again. The state was backed up before replacement; all other add-on state was
preserved. Two initial shutdown/file-replacement attempts failed before applying
the change, and NVDA was relaunched with its prior state before the corrected
replacement succeeded. No forced process termination or security-setting
change was used.

Verification after startup:

- NVDA **2026.2** is running.
- RDAccess is in `disabledAddons`, with no pending disable remaining.
- The companion is enabled and its log reports
  **`Initialized Linux Remote Access Companion`**, with the initialization
  callback owned by `globalPlugins.linuxRdAccess`.
- All **13 installed Python files** match the verified
  `linuxRdAccess-20261013.0.1.nvda-addon` package byte for byte.
- `nvda-status` reports **`required_or_expired`**, as expected after restart:
  the previous consent was not carried forward. A fresh five-minute session
  was requested before any new remote input or connection action.

This establishes installation and standalone plugin activation, not live
semantic braille, speech, routing or panning acceptance. Legacy RDAccess's
RDP/Citrix functionality is disabled until that add-on is re-enabled. Its source
copy has not been removed from the rdAccess repository by this configuration
change. The active Orca session and relay credentials were not modified.

## Standalone authorized connection and physical panning follow-up

The user authorized a new session at 09:42:48 America/New_York on 2026-10-13.
Authenticated status now reported the standalone bridge connected, semantic
braille negotiated and temporary-message support available. Earlier negotiation
was pending immediately after restart; no Orca restart or relay-credential
change was made by the agent to obtain this later state. The log identified
focus/presentation callbacks from `globalPlugins.linuxRdAccess`, with remote
focus present, braille enabled and focus tether active.

Read-only Linux observation found Firefox on the existing `:0` desktop. Focus
changed from a menu to a push button before the planned menu-navigation check.
One Windows-origin Down Arrow was sent while authenticated remote control was
active; before/after AT-SPI observations both reported a Firefox push button.
There was no observed focus change, and no menu-navigation PASS is claimed.

After control was observed local, one actual `Insert+Alt+Tab` enabled remote
control; authenticated status confirmed the change with connection and semantic
negotiation retained. A subsequent Tab attempt was interrupted by the
computer-use helper's concurrent-user-input guard. Its outcome is inconclusive;
the observed later menu-item focus cannot be attributed to that attempt.
Automated navigation was paused. Broad log windows contained unrelated Windows
speech/braille updates and control changes; these were not used as proof of a
companion defect or end-to-end presentation success. The five-minute
authorization window elapsed and automated input remained stopped.

The user was then asked to pan one step on the physical display **while
controlling Linux Firefox**, and directly reported **"Linux Firefox content"**.
Record this as **Physical-braille-tested: limited PASS for this single panning
observation**, rather than automated/viewer-only evidence. The exact label,
direction, device model and cell positions were not recorded, and the result
does not establish routing, long-line panning/wrapping, caret tracking,
temporary-message restoration, reconnect, or all applications. Issue #59 and
the related live acceptance trackers remain open. Later status/CLI responses
must continue to report physical braille as `unverified`; this human evidence
does not authorize an automatic physical acceptance claim by the endpoint.

## Bounded Firefox Tab follow-up after the CI investigation

The user activated fresh five-minute authorization. Authenticated status
confirmed connected transport, attached standalone bridge, semantic braille
negotiation and temporary-message support. Remote control was initially false,
then observed true before the navigation gestures; no agent-origin handoff
shortcut was sent during this interval.

Input used Windows File Explorer through the supported computer-use API,
with the address-bar focus observed before input and unchanged afterward.
Linux observation reused the existing bounded `Focus` diagnostic on the
existing `:0` Firefox session and a temporary read-only AT-SPI listener. The
listener recorded roles and opaque in-memory identities, never control names
or editable contents. No application launch, text entry, configuration change,
Orca restart or connection restart was performed.

| Gesture | Evidence | Assessment |
| --- | --- | --- |
| First Tab | Observer baseline was Firefox push button, identity 1; a focused event at about 41.7 seconds identified a separator, identity 2. A separate focus snapshot agreed. | **Limited PASS:** this Windows-origin Tab reached Linux and changed accessible focus. |
| First Shift+Tab | Linux focus snapshot returned to a push button, with authorization/control still active. The 60-second observer had ended before this gesture. | Role restoration observed; original object identity **not verified**. |
| Repeated Tab | A new observer again recorded push button 1 → separator 2 at about 19 seconds; the separate focus snapshot agreed. | **Limited PASS:** repeated delivery and focus change. |
| Planned second Shift+Tab | The immediate post-Tab status reported `required_or_expired`. No further input was sent. | **NOT TESTED:** fresh authorization required. |

The second observer completed with separator identity 2 still focused. Thus no
fully captured Tab/Shift+Tab return to the original object is claimed. Speech
and physical braille for these gestures await direct user confirmation; these
AT-SPI/IPC observations do not certify presentation, routing/caret, temporary
messages or reconnect behavior. All seven acceptance trackers remain open.

The separate, pre-existing VS Code caret failure is tracked in
[issue #79](https://github.com/mtigzoe/linux-rdaccess/issues/79), with preserved
native-render evidence and bounded diagnostics in
[PR #80](https://github.com/mtigzoe/linux-rdaccess/pull/80). Its failure is not a
passing acceptance result for PR #78.

## Eurobraille b.note left-pan report and BrailleExtender correction

The user subsequently reported that **left panning still showed a Windows
VS Code label while controlling Linux Firefox**, and identified the physical
display as a **Eurobraille b.note**. This is a reported physical failure of
build `20261013.0.1`; the earlier single “Linux Firefox content” observation
cannot establish general panning acceptance. Firmware, display size, exact
cell contents and whether the failure occurs at the line boundary were not
recorded. The saved display selection is `auto`; the exact loaded driver was
not established by the model report alone.

Read-only inspection confirmed the standalone companion initialized, without
the legacy-owner conflict. BrailleExtender is enabled, with installed manifest
version **26.06.05-eefe85d**. Its installed implementation exposes two concrete
compatibility paths which the companion's prior tests did not cover:

1. `braille_terminal.make_patched_handle_gain_focus` replaces
   `BrailleHandler.handleGainFocus` and calls
   `braille.getFocusContextRegions(...)`. It has neither an unqualified getter
   in its function globals nor a `__wrapped__` link to the core method. The
   companion previously scoped only an unqualified getter, then fell back to
   the replacement unchanged. A regression reproduced **Windows application →
   Apply changes** regions instead of **Settings → Apply changes**. Left pan can
   expose that Windows ancestor even though the Linux focus region is present.
2. BrailleExtender's `GlobalPlugin.script_braille_scrollBack/scrollForward`
   are distinct bound methods from GlobalCommands' scripts. The companion
   classified them as remote gestures, forwarding them instead of queuing
   Linux-region recovery and running NVDA-coordinate panning locally.

The correction scopes both the core function-global getter and the braille
module export for the synchronous remote-focus call. Other objects still use
that lookup's original getter. Both lookup paths are restored on success or
exception, and Windows focus is unchanged. The installed BrailleExtender
handler remains in place. Its two known bound pan aliases now remain local
and queue the existing session/control-guarded recovery before the script;
unrelated and same-named scripts from other add-ons still forward normally.
No BrailleExtender files or user preferences were modified.

Modified code: `remoteAccessSemanticBraille.py`. Three new regression methods
cover the replacement context handler, restoration after an exception, and
local/forwarded pan ownership. Against pre-fix `e50acd4`, they produced **five
expected failing checks**, including both pan directions; the other tests had
no errors. With the correction, **56 focused braille tests passed**, and the
complete native Windows Python 3.13 companion suite passed **203 tests**.

An additional isolated subprocess compiled the actual installed
BrailleExtender focus factory and both pan method bodies, with NVDA runtime
leaves stubbed. It confirmed Linux-only ancestry, restoration of ordinary
Windows context after the scoped call, and both pan methods executing locally.
The inspected file hashes are:

- `braille_terminal.py`: `360e652f51bb60b04f32ce52c97dd759683f56ba0996bee32bfcf7dda8ac7d76`.
- `__init__.py`: `3b3727501f1b671aeaa51cc3fe80c6b58283fa496b7c4b7c4af9b73ad7dabf84`.

This is installed-source validation, **not a live physical-device PASS**.
The temporary harness required bootstrap/stub corrections before completing;
only its final completed checks are counted. Ruff **0.16.4**, pinned by the
companion workflow, passed check and format check for all companion sources.
The first root-level explicit-config invocation flagged an unchanged build-test
import group; the actual CI-equivalent commands passed without unrelated
formatting changes. `git diff --check` passed.

The prepared package is **linuxRdAccess-20261013.0.2.nvda-addon**, **47,010
bytes**, SHA-256 **`ca98b226a26e9b74e27723fcc589ec06f2581451a70aa35da0427ed3e4c82691`**. All 17
archive entries, including 13 Python files, match source/manifest/documentation.
A second Python 3.13 build matched byte for byte. A system-Python cross-interpreter
comparison had equal archive contents but different compressed bytes;
cross-interpreter byte reproducibility is not claimed.

Build .2 is **not installed**. Installation/restart require separate approval,
and all physical routing/panning, temporary-message and reconnect acceptance
remains open. New GitHub Actions are not monitored or awaited; PR #78 stays open
and unmerged.

## Speech wording and key echo remain open

The user also reported **“Tab”** when pressing Tab, no corresponding **“Tab”**
on Shift+Tab, and **“push button”** when navigating to a button. These are
human-reported observations, not an automated audible capture. The user could
not confirm the physical label following the earlier agent-origin Tab.

The Linux host has Orca package **42.0-1ubuntu2**. Its installed customization
uses `_linux_rdaccess_speech_sequence` for outbound `speak`; that helper wraps
scalar text as a sequence and preserves its wording. The companion explicitly
formats semantic focus for **braille only**, leaving speech with Remote Access.
Thus forwarding Orca's role wording does not provide NVDA-formatted semantic
speech. No role-string replacement or new speech protocol is introduced here.

Read-only persisted settings show NVDA `speakCommandKeys=False`, while Orca
`enableKeyEcho=True` and `enableActionKeys=True`; installed Orca classifies Tab
as an action key. The saved default Orca profile has modifier echo disabled.
These are candidate evidence for the announcement difference, not proof of
its exact source: active runtime profile/utterance origin was not captured.
Issue #58 remains open for role presentation, key echo, interruption and Say All.

During the fresh consent interval, Shift+Tab reached a Firefox push button,
with a captured focused event at about 46.3 seconds, then Tab produced a link
focus snapshot. Other navigation was observed before the agent's gesture, and
the timed observer ended before the return event. Original-object restoration
is still not claimed. Consent was checked active before input; after expiry,
no further input was sent. Speech, physical braille and routing acceptance
remain separate from these role snapshots.
