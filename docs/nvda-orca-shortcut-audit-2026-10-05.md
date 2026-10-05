# NVDA-to-Orca shortcut audit — October 5, 2026

Starting revision: `3404d8439139ad4c45af9a8ce50acf736dab41c6`, checked after
fetch on `feature/nvda-orca-input-compat`. PR #14 is open and unmerged.
Controller compatibility remains **v32**; local-machine/XTest remains **v8**.

This checkpoint inventories existing behavior and identifies the next live
tests. It does not establish that every shortcut works through Windows Remote
Access. No production mapping is added or changed.

## Evidence and scope

The local XFCE/X11 display is `:0`, Orca is 42.0, and the installed input shim,
XTest shim, and Orca adapter pass `linux-rdaccess doctor`. Orca has an established
TCP relay connection. The user confirms remote control works, the Windows speech
probe is enabled and forwarded on port 8765, and Insert+T works.

The Windows command reference is NVDA 2026.2; the user's installed NVDA version
and keyboard layout have not been independently determined. The current shim
recognizes the desktop forms listed below. Laptop alternatives require their
own audit rather than treating identical physical keys as identical commands.

Sources used:

- [NVDA 2026.2 User Guide](https://download.nvaccess.org/documentation/en/userGuide.html),
  especially system caret, review, browse mode, and single-letter navigation.
- [NVDA 2026.2 command bindings](https://github.com/nvaccess/nvda/blob/release-2026.2/source/globalCommands.py).
- Installed Orca 42 source under `/usr/lib/python3/dist-packages/orca/`:
  `scripts/default.py`, `scripts/web/script.py`, `structural_navigation.py`,
  `desktop_keyboardmap.py`, `common_keyboardmap.py`, and `input_event.py`.
- [Controller and XTest patch generator](../remote_access.py),
  [runtime adapter](../orca_adapter.py), and existing compatibility tests.

## Existing direct commands

Calls run through the controller's GLib scheduler and the active-script adapter.
The scheduler checks input generation again before execution. Consumed commands
retain repeat/release ownership. Translated Caps Lock chords mark the deferred
modifier as used rather than injecting its press.

| Windows gesture | Existing Orca operation | Boundary checked in current code |
| --- | --- | --- |
| NVDA+Tab | `whereAmIBasic(None)` and verified aliases | Uses Orca's locus of focus; no manufactured keypad chord. |
| NVDA+T | `presentTitle(None)` | Works independently of Orca's physical modifier configuration. |
| NVDA+End | `presentStatusBar(None)` | Requires extended End; keypad End remains distinct. |
| NVDA+Down | `sayAll(None)` | Requires extended Down and no additional modifiers. |
| NVDA+Space | `togglePresentationMode(None)` | Resolves on the active script; ordinary Space passes through. |
| NVDA+Shift+Space | `toggleStructuralNavigation(script, None)` | Allows Shift, excludes Ctrl/Alt/Super. |
| NVDA+F2 | `bypassNextCommand(None)` | Also arms a receive-side one-command latch before GLib dispatch. |
| NVDA+F7 | Category chooser, then native structural object's `showList(script, None)` | Cancel completes the command; nested-loop return rechecks generation. |

Orca 42's basic Where Am I operates on `locusOfFocus`. It is not an arbitrary
review-cursor operation. Detailed Where Am I, spelling/repeated-press variants,
and current caret line/word/character require separate live semantics tests.

## Structural navigation

The default letters agree for headings, links, form controls, lists, tables,
graphics, paragraphs, blockquotes, separators, and visited/unvisited links:
`H K F B E X C R L I T G P Q S U V`, with Shift for reverse traversal.
Orca 42 also binds heading levels 1–6. Different eligibility predicates can still
produce different results even when the shortcut letter agrees.

The existing D/Shift+D hook handles the verified landmark difference: Orca uses
M for landmarks and D for live regions. It requires a fresh remote-D marker,
an active structural-navigation model, allowed modifiers, and an actual
structural-navigation handler for the translated key. Release reuses the
translated press identity. Normal application input stays under Orca's ordinary
handling; no general printable-character translation table is introduced.

Source differences requiring live tests:

| Candidate | What needs establishing before a mapping |
| --- | --- |
| NVDA M for frames versus Orca M for landmarks | A real frame-navigation failure and an exact Orca equivalent; the structural object registry has no separate frame binding. |
| Ctrl+Alt+Arrow versus Orca Shift+Alt+Arrow table cells | Correct document/table context, editable-grid exclusion, boundaries and spans. Orca delegates table movement through structural navigation and `goCell`. |
| Desktop NVDA+Up and review commands | Caret reading versus Orca flat review, including the cursor that moves. |
| Numeric keypad review commands | Orca's “item” operations versus NVDA's word review; shared key positions do not prove equivalent units. |
| Laptop NVDA+A and NVDA+Shift+End | Layout intent must be known; the shim currently uses the desktop Say All and status forms. |
| NVDA F3/F5/F9/F10/F12 families | Find, refresh, review/copy, and time commands need individual source and live comparisons. No umbrella F-key translation is justified. |

NVDA+Shift+Space already has the intended single-letter-navigation toggle
counterpart. The underlying Orca toggle and manual presentation toggle still
need remote testing in document content, editable controls, and browser chrome.
O/chunk and other commands with different object predicates are not claimed
equivalent solely because a binding exists.

## Modifier, application, and keypad boundaries

Insert and Caps Lock are recognized as NVDA modifiers. Plain Caps Lock is
deferred until release or until an untranslated chord needs the physical key;
translated commands do not release/re-press it. Tests cover repeats, two NVDA
modifiers, successful-forward ownership, failed releases, and generation reset.
Real lock behavior and reconnect behavior remain separate live checks.

Ordinary arrows, Home/End, Page Up/Page Down, Tab/Shift+Tab, and application
function-key shortcuts use the raw input path unless a documented NVDA chord
above consumes them. Ctrl has an explicit remote cancel path; unrelated
modifier-only presses do not acquire that cancel behavior. Shift pause semantics
have not been shown equivalent to NVDA's speech pause. Alt/Super application
shortcuts are excluded from the direct screen-reader chord mappings.

Keypad resolution retains non-extended navigation identity for `KP_Insert`,
`KP_Delete`, `KP_Home`, `KP_End`, the four keypad arrows, `KP_Prior`, `KP_Next`,
and `KP_Begin`. Press ownership retains the resolved X keycode for release.
XTest and fallback cannot replay an event already queued by XTest. The Xvfb
tests inspect real server key state; they are Linux-side isolation tests.
Num Lock ON/OFF at both endpoints, all keypad pairs, and real reconnect/handoff
still require end-to-end observation.

## Lock-feedback investigation

The user reports silent Num Lock and Caps Lock while controlling Linux. During
the completed passive Num Lock window, all three indicators remained OFF and
the metadata-only Windows receiver received zero speech events. No local input
was injected. Confirmation that the requested remote press occurred during
that window is pending, so this result cannot yet be classified as injection
failure or missing presentation.

The installed controller has no independent post-injection XKB announcement.
That fact alone does not establish the live root cause. A confirmed transition
with a functioning probe and no speech would support missing feedback. A
confirmed press without a transition would instead require input-path tracing.
Queued speech plus silence would require Windows output investigation.

Any eventual feedback feature must query the resulting named Linux indicator,
run presentation on Orca's main thread, suppress duplicate native presentation,
and discard stale-generation work. A Caps Lock NVDA chord must produce neither
a physical toggle nor a false announcement. No lock-feedback fix is implemented
at this checkpoint.

## Braille and privacy

Pan back/forward, routing, and to-focus already delegate to Orca APIs. Routing
requires an unambiguous bounded cell index. Unknown or malformed semantic
commands are redacted; typed braille does not become keyboard input. These
commands still need real hardware tests, one action at a time.

No raw keyboard logger or normal speech logger was enabled. The brief opt-in
text receiver was restricted to the controlled lock window and wrote no output
file. The longer waiting window used metadata only. AT-SPI inspection retained
roles/states and redacted accessible names.

## Validation and next live action

| Check | Result |
| --- | --- |
| Python 3.10 focused compatibility/adapter/lifecycle/XTest unit tests | 215 tests, PASS. |
| Python 3.10 full repository suite | 499 tests, PASS, 8 skipped. |
| Python 3.12.13 full repository suite | 481 tests, PASS, 10 skipped. |
| Xvfb injection and live-X11 diagnostic tests, Python 3.10 | 18 tests, PASS, no skips. |
| Same Xvfb tests, Python 3.12.13 | 18 tests, PASS, no skips. |
| `compileall`, both interpreters | PASS. |
| `git diff --check` | PASS. |

Python 3.12 has no GI/AT-SPI/liblouis Python bindings in this isolated interpreter.
The bridge and braille-bridge test modules are therefore skipped as modules;
their 20 tests run on Python 3.10. The other full-suite skips cover tests that
require an isolated X server; the separate Xvfb runs execute those checks.
No new regression test is claimed because no new bug has yet been reproduced.
Existing checks exercise the boundaries above and do not prove Windows speech
or braille. Exact pushed revision and CI outcome belong to the round report.

First resolve whether the Num Lock press occurred in the observed interval.
Then test Caps Lock separately. Continue with one remote action at a time for
focus/title/status, Thunar traversal, Say All/Ctrl, mode toggles, Elements List,
pass-next, table/frame candidates, held keys/keypad identity, and real braille.
The live audit remains open while those checks are pending.
