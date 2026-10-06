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

## Follow-up — October 5, 2026

The sections above preserve the earlier v32 checkpoint and its validation
results. The current controller is v36. This follow-up records a subsequently
confirmed native-keyboard failure and the remaining compatibility work; it does
not establish end-to-end Firefox speech or full NVDA compatibility.

### Native keyboard path repaired

The legacy customization called `KeyboardEvent.is_pressed_key()`, but installed
Orca 42 exposes `isPressedKey()`. This raised an exception inside the patched
native keyboard-event processor. Direct adapter commands such as title reporting
could still work while ordinary keyboard navigation failed in this path.

The customization now uses `_linux_rdaccess_event_is_pressed(event)`, which
accepts the installed camel-case API and the snake-case API. The repair preserves
the native-handler and injected-key-marker paths. Its
`CUSTOMIZATION_EVENT_API_MARKER` is accompanied by a validator that checks the
actual helper and the affected calls; a marker alone does not establish a
complete repair. The upstream raw-key file logger remains disabled.

The repair was applied to the live installation. `linux-rdaccess doctor`
reported all four compatibility checks current: native Orca keyboard events,
the controller input shim, fast key injection, and the Orca API adapter. This
confirms the installed patch checks, not successful Windows-to-Firefox navigation
or speech. New implementation test results belong to the follow-up round report,
not the historical validation table above.

Windows configuration was independently checked: **desktop** keyboard layout,
`NVDAModifierKeys=7` (Caps Lock, numpad Insert, and extended Insert), and
`handleInjectedKeys=true` (Handle keys from other applications enabled).

### Plain arrows in Firefox

Orca 42 already binds plain Down to next-line navigation and plain Up to
previous-line navigation. Its caret handler moves the document caret, speaks the
resulting line, and updates braille. The web script uses that handler only when
`caretNavigationEnabled` is true, focus mode is off, the caret context is within
document content, and Shift is absent. Browser chrome and interactive controls
instead need their normal application handling. At document boundaries, no new
movement or speech can be valid.

The repaired native path must now be tested with one observed remote arrow at a
time. Record the active Gecko script, document/chrome role, focus mode, caret
navigation setting, caret context before and after, and resulting speech/braille.
Those observations distinguish input delivery, mode, caret movement, and output
failures. Ordinary arrows must not receive a global screen-reader translation.

One separate source-supported collision can disable this behavior: NVDA+F12
reports time/date, whereas Orca+F12 toggles caret navigation. The controller does
not currently intercept NVDA+F12. When the forwarded NVDA modifier is also an
Orca modifier, that shortcut can turn off document arrow reading. This is a
remaining compatibility risk, not the confirmed cause of the user's Firefox
failure.

Sources:

- [Orca 42 web-script mode checks](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/scripts/web/script.py#L1028).
- Installed Orca 42 `caret_navigation.py`: arrow bindings, `_next_line`,
  `_previous_line`, and the Orca+F12 caret-navigation toggle.
- [NVDA 2026.2 date/time binding](https://github.com/nvaccess/nvda/blob/release-2026.2/source/globalCommands.py#L411).
- [Orca reading commands and modes](https://help.gnome.org/orca/commands_reading.html).

### Compatibility boundaries and collisions

The current direct command mappings provide a useful desktop subset. Unmapped
NVDA chords still reach Orca's ordinary handling, which can execute a different
command when the two screen readers share a modifier. That fallback is not a
claim of compatibility.

| Area | Remaining gap or collision |
| --- | --- |
| Desktop/laptop layout | Laptop NVDA+Down means next review line, but the shim forces Say All. Laptop NVDA+End means end of the review line, but the shim forces status reporting. Laptop NVDA+A means caret Say All and can reach Orca's browse/focus toggle. Laptop NVDA+L and NVDA+Shift+End lack their current-line and status equivalents. |
| Caret reporting | Desktop NVDA+Up has no current-line implementation. Orca's `sayLine(obj)` offers a caret-based operation to assess; entering flat review is not equivalent. Selection, formatting, caret location, and link destination need individual semantic checks. |
| Repeated commands | Focus/title/status mappings provide first-press equivalents. NVDA's repeated spelling and clipboard variants are not implemented by those direct calls. |
| Structural navigation | D/Shift+D translation exists. M means NVDA frame versus Orca landmark; O means embedded object versus Orca chunk; A means annotation versus Orca clickable. N/nonlinked text, W/spelling errors, and heading levels 7–9 lack matching enabled structural objects in Orca 42. Shared letters and comma/Shift+comma container commands still need predicate and boundary tests. |
| Table navigation | NVDA Ctrl+Alt+Arrow differs from Orca Shift+Alt+Arrow. First/last row, first/last column, and row/column reading need separate comparisons. Editable grids must retain their application shortcuts. |
| Find and refresh | NVDA+Ctrl+F, NVDA+F3/Shift+F3, and NVDA+F5 lack explicit document equivalents. Orca Find searches flat-review window contents and is not automatically an equivalent document search. |
| Object and review navigation | NVDA navigator-object hierarchy and object/document review are not supplied by the direct adapter. Orca flat review is a spatial representation of visible contents; its keypad item operations do not prove NVDA word-review semantics. NumpadPlus means review Say All in NVDA and caret Say All in Orca. |
| Other fall-through commands | NVDA+B/read-active-window can invoke Orca+B/next-bookmark. NVDA+F12 can toggle caret navigation. Shift speech-pause semantics, input help, and other unmapped commands need explicit behavior and collision checks. |

Layout handling must be explicit before adding laptop aliases. Physical remote
key messages do not identify whether Windows NVDA interprets them using desktop
or laptop layout. A future compatibility setting must select the intended layout
and resolve conflicting gestures accordingly. For the verified current Windows
configuration, the test baseline is desktop; laptop support remains a separate
coverage target.

References:
[NVDA system-caret commands](https://download.nvaccess.org/documentation/en/userGuide.html#SystemCaret),
[NVDA review commands](https://download.nvaccess.org/documentation/en/userGuide.html#ReviewingText),
[NVDA browse-mode commands](https://download.nvaccess.org/documentation/en/userGuide.html#BrowseMode),
and [Orca flat-review limits](https://help.gnome.org/orca/howto_flat_review.html).
The installed Orca 42 `common_keyboardmap.py`, `desktop_keyboardmap.py`, and
`structural_navigation.py` provide the local binding evidence for this table.

### Scoped compatibility test matrix

Use the controlled [Firefox navigation fixture](../tests/fixtures/firefox-navigation.html)
for initial document, editor, select, button, and mode tests. Add dedicated
fixtures for tables, frames, embedded objects, and review behavior before
claiming coverage of those cases. Each case needs both a state-change observation
and output evidence; a successful injection call alone is insufficient.

| Context | Actions | Required observation |
| --- | --- | --- |
| Static document in browse mode | Down, Down, Up; Left/Right; Ctrl+Left/Right; Home/End; Ctrl+Home/End | Correct caret/object transitions and expected speech/braille, without duplicate movement. |
| Start/end of document | Up at start; Down at end | Bounded behavior without incorrect wrap or manufactured output. |
| Browser chrome | Address bar and menus; arrows and Tab | Native navigation and focus feedback. |
| Editable content | Input, textarea, contenteditable; arrows and Shift-selection | Editing and selection preserved, with no document-navigation interception. |
| Interactive widgets | Select/listbox, radio group, ARIA application/grid | Widget operation and presentation in focus mode. |
| Mode transitions | NVDA+Space; Tab into/out of editor; NVDA+Shift+Space | Correct mode announcement and restored arrow/letter behavior. |
| Structural content | Heading, landmark, link, form, container, frame, embedded object | Correct category, forward/reverse traversal, and boundary behavior. |
| Tables | Static cells, spans, edges, editable grid | Correct cell coordinates/content and preserved application shortcuts. |
| Reading/reporting | Say All/Ctrl stop; current line; focus/title/status | Correct cursor ownership and output; repeated-press semantics assessed separately. |
| Layout/modifier boundaries | Desktop/laptop; Insert/Caps; Num Lock on/off | No command collision, lock toggle, stuck modifier, or keypad substitution. |
| Lifecycle and braille | Reconnect/handoff; held-key release; real display pan/routing | Released key state, discarded stale work, and verified hardware output. |

Windows Firefox navigation and speech remain **unverified** at this follow-up.
The first acceptance check is the user's plain Up/Down case through the repaired
native path, followed by the desktop fixture cases above. Source alignment and
Linux-side tests do not replace these end-to-end observations.

### Table cell navigation, controller v37

Orca 42's `structural_navigation.py` binds table-cell navigation to
Shift+Alt+Left/Right/Up/Down (handlers `tableCellGoLeft`, `tableCellGoRight`,
`tableCellGoUp`, `tableCellGoDown`). Shift+Alt+Home/End go to the first/last
cell of the table, not to a row or column edge, so NVDA's row/column-edge table
commands have no Orca 42 equivalent and are not translated.

Controller v37 reuses the existing Orca-side `KeyboardEvent.shouldConsume`
hook that translates NVDA D to Orca M. A remote extended arrow with exactly
Ctrl and Alt held (no Shift, Win, Orca or NVDA modifier) marks one key; the hook
rewrites the event's modifiers to Shift+Alt only when
`useStructuralNavigationModel()` is true and the matching Orca handler belongs
to the `tableCell` structural-navigation object. Orca's own gating therefore
decides browse mode, focus mode and document context. The key release follows
the identity chosen for its press. Opt out with
`LINUX_RDACCESS_NVDA_TABLE_KEYS=0`.

Not established: Windows NVDA speech or braille for these keys, behavior in a
real Firefox table, and whether the window manager delivers Ctrl+Alt+Arrow to
Orca at all. XFCE's default workspace shortcuts use Ctrl+Alt+Arrow; check them
with `xfconf-query -c xfce4-keyboard-shortcuts -lv | grep -i "Primary>.*Alt"`
before concluding the translation is broken. Line reading (NVDA+Up) is a
separate round.

### Controller v38 hardening

- Both Orca-side key hooks (NVDA D and the table arrows) now restore the event
  if Orca's handler lookup raises after the event was rewritten. Previously the
  exception was logged but the event stayed rewritten, so Orca continued with a
  modifier or key the user never pressed.
- Table arrows keep one translation per key. Rolling from Ctrl+Alt+Down to
  Ctrl+Alt+Right while Down is still held no longer strands Down's release.
- Launchers: `start-orca-session.sh` uses only the current user's newest XFCE
  session, reads `environ` NUL-separated (a value containing a newline could
  forge another variable), keeps its log in a private state directory instead
  of a predictable `/tmp` file, and detaches Orca from the terminal.
  `start-orca-remote.sh` no longer needs `$USER` and is executable, as the
  README runs it.
- `graphical_session_env` chooses the user's newest session instead of the
  first one `/proc` happens to list.
