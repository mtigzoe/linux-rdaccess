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
| #58 — Live validation: Windows NVDA speech, interruption and Say All | **Needs live testing** | No speech changes. Audible announcements, Ctrl interruption and Say All still require Windows-side observation. |
| #59 — Live validation: physical braille routing and Windows NVDA presentation | **Needs live testing** | Two companion defects above fixed with regressions. Prior Windows VS Code context/panning report remains unverified on the physical display. |
| #60 — Live validation: Linux Mint application accessibility matrix | **Needs live testing** | Ancestry correction covers a deterministic context defect. No new per-application keyboard, speech or braille acceptance was performed. |
| #61 — Live validation: disconnect, reconnect and stale input lifecycle | **Needs live testing** | Retained outbound object commands now expire. Real handoff/reconnect, held modifiers and physical routing still need acceptance. |
| #72 — Live NVDA braille acceptance for Linux #69 and Windows rdAccess #9 | **Needs live testing** | Existing temporary-message handling preserved. Physical timeout, panning/routing, local-control and reconnect checklist remains incomplete. |
| #76 — Stage 2: opt-in local NVDA control IPC for AI test sessions | **Still open** | IPC already implemented by Linux PR #75 and merged Windows rdAccess PR #10; PR #78 extracts it. Authenticated status and existing-connection reuse worked through the legacy owner. Standalone integration/review and remaining live acceptance are not established. |

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
