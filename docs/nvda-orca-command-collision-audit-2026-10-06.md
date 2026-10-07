# NVDA 2026.2 / Orca 42 command collision follow-up

This audit starts from main `a917df5` and controller v89. It checks command
identity and side effects from source and the existing generated-controller,
Orca event-hook, and native-method test fixtures. It does not establish Windows
NVDA Remote or Firefox end-to-end compatibility.

## Source provenance

- [NVDA 2026.2 global commands](https://github.com/nvaccess/nvda/blob/f62c980589d1ac30babf68ad48177e9ad29a2e84/source/globalCommands.py),
  [keyboard handler](https://github.com/nvaccess/nvda/blob/f62c980589d1ac30babf68ad48177e9ad29a2e84/source/keyboardHandler.py),
  [VK identities](https://github.com/nvaccess/nvda/blob/f62c980589d1ac30babf68ad48177e9ad29a2e84/source/vkCodes.py),
  [Windows constants](https://github.com/nvaccess/nvda/blob/f62c980589d1ac30babf68ad48177e9ad29a2e84/source/winUser.py),
  and [browse commands](https://github.com/nvaccess/nvda/blob/f62c980589d1ac30babf68ad48177e9ad29a2e84/source/browseMode.py).
- [Orca 42 common bindings](https://github.com/GNOME/orca/blob/e226add72212718db5960889bb2f7ddced17981b/src/orca/common_keyboardmap.py),
  [desktop bindings](https://github.com/GNOME/orca/blob/e226add72212718db5960889bb2f7ddced17981b/src/orca/desktop_keyboardmap.py),
  [default script](https://github.com/GNOME/orca/blob/e226add72212718db5960889bb2f7ddced17981b/src/orca/scripts/default.py),
  [utilities](https://github.com/GNOME/orca/blob/e226add72212718db5960889bb2f7ddced17981b/src/orca/script_utilities.py),
  [structural navigation](https://github.com/GNOME/orca/blob/e226add72212718db5960889bb2f7ddced17981b/src/orca/structural_navigation.py),
  and [web script](https://github.com/GNOME/orca/blob/e226add72212718db5960889bb2f7ddced17981b/src/orca/scripts/web/script.py).
- The installed `/usr/lib/python3/dist-packages/orca` 42 implementation supplies
  the native methods executed by regression tests. Upstream source files,
  exact revision metadata, SHA-256 manifest, failing reproductions, successful
  focused runs, and Xvfb layout evidence are retained in
  `/tmp/linux-rdaccess-followup/` for this session.

Categories describe controller v89 before this follow-up:
**1** translated correctly; **2** deliberately consumed; **3** existing safe
passthrough; **4** missing exact translation; **5** unrelated Orca action.
Category 3 retains existing behavior; it does not certify full review-cursor
equivalence. `NVDA` means the configured Insert/NumpadInsert/Caps modifier.
Dedicated arrows/Home/End/Page keys have extended Windows identities. Physical
navigation numpad keys require matching scan-code evidence for interception.

## Global and keypad collision matrix

| NVDA command | Orca 42 collision or exact API | Category and outcome |
|---|---|---|
| NVDA+1 | Bookmark 1; enter/exit learn mode API | 1, direct input-help operation |
| NVDA+2–7 | Bookmarks 2–6 or no equivalent setting | 2, protect NVDA typing/review settings |
| NVDA+Tab | Focus reporting versus keypad Where Am I | 1, native basic Where Am I |
| NVDA+T | Time/date instead of window title | 1, native title presentation |
| NVDA+F12 | Web caret-navigation toggle | 1, native time/date with received tap count |
| Desktop NVDA+Up; laptop NVDA+L | Caret line versus flat review | 1, native current-line operation |
| Desktop NVDA+Down; laptop NVDA+A | Caret Say All | 1, native Say All |
| Desktop NVDA+Shift+Up; laptop NVDA+Shift+S | Current selection | 1, native selection reporting |
| Desktop NVDA+End; laptop NVDA+Shift+End | Status reporting | 1, native status presentation |
| NVDA+M, +P, +U | Mouse review, punctuation, progress settings | 1, isolated native operations |
| NVDA+Space | Preferences versus browse/focus mode | 1, manual web-mode operation with document guard |
| NVDA+Shift+Space | Structural navigation switch | 1, native structural navigation API |
| NVDA+Ctrl+Space | Application preferences versus embedded-object exit | 2, no equivalent parent tree-interceptor API |
| NVDA+F2 | Pass-next versus native bypass binding | 1, one-gesture bypass ownership |
| NVDA+F7 | Elements List versus different native entry point | 1, chooser with originating document ownership |
| NVDA+F; NVDA+Shift+F | Caret formatting; review formatting | 2, no exact paired caret/review implementation |
| NVDA+B; NVDA+Shift+B | Foreground reading/battery versus bookmark navigation | 2, no exact native operation |
| NVDA+K | Link destination versus no isolated URL operation | 2, no exact native operation |
| NVDA+S | Multi-state NVDA speech mode versus Orca silence switch | 2, different state machines |
| NVDA+Ctrl+G/S/V/A/U/K/M/O/B/D/W/P | NVDA-specific setting dialogs | 2, global Orca preferences are not individual NVDA dialogs |
| NVDA+Ctrl+C/R/Z/T | Save/revert settings, console, braille tether | 2, no equivalent individual operations |
| Plain Numpad1–9 | Orca flat-review character/word/line conventions | 3, preserved; review scope remains a live semantic risk |
| Plain NumpadEnter; NumpadMinus | Unbound in NVDA; Orca Where Am I / flat-review switch | 3, preserved native extension |
| Plain NumpadDivide/Multiply | Current pointer versus focused/review-item click | **5 → 2**, consume exact physical plain forms |
| Shift+NumpadDivide/Multiply | Button lock versus focused/review-item click | 2, consume exact physical forms |
| Plain NumpadPlus | Review Say All versus Orca first-tap caret Say All | **5 → 2**, consume exact physical plain form |
| Shift+Numpad2; laptop NVDA+Ctrl+Shift+. | Focused shortcut utility | **4 → 1**, isolated speech/braille operation |
| Shift+Numpad1/3/7/9 | Review line/start/end/top/bottom | 2, no independent NVDA review cursor |
| NVDA+Numpad1/7 | Review-mode changes versus flat-review movement | 2, models differ |
| NVDA+Numpad2/4/5/6/8 | Navigator child/previous/current/next/parent versus flat review | 2, no equivalent independent navigator hierarchy |
| NVDA+Numpad3/9 | Navigator flow navigation versus flat-review boundaries | 2, no equivalent navigator-flow state |
| NVDA+NumpadDelete; +Shift+NumpadDelete | Caret/navigator geometry versus find commands | 2, cannot preserve both target semantics |
| NVDA+NumpadMinus; +Shift+NumpadMinus | Navigator↔focus/caret operations | 2, no independent navigator state |
| NVDA+NumpadDivide/Multiply | Navigator↔mouse operations | 2, no independent navigator state |
| NVDA+NumpadEnter | Activate navigator versus title/status | 2, no independent navigator activation target |
| Laptop NVDA+Enter/Backspace/Shift+Backspace/Shift+O | Activate, focus↔navigator, current navigator | 2, same navigator limitation |
| Laptop NVDA+Shift+M/N; NVDA+[/] and +Ctrl+[/] | Navigator↔mouse, pointer click, button locks | 2, no exact isolated script operation |
| Laptop NVDA+Shift+Arrow | Navigator hierarchy | 2, same navigator limitation |
| Laptop NVDA+PageUp/Down; desktop NVDA+PageUp/Down | Review mode / review page | 2, different review models |
| Laptop NVDA+Shift+PageUp/Down | Review pages | 2, different review models |
| Laptop NVDA+Home/End/Left/Right/Up/Down | Review boundaries/character/line | 2, preserve caret/review separation |
| Laptop NVDA+Ctrl+Home/End/Left/Right/. | Review top/bottom/word reporting | 2, preserve caret/review separation |
| Laptop NVDA+.; +Shift+.; +Shift+A | Review character, line, Say All | 2, preserve caret/review separation |
| Desktop NVDA+Ctrl+Arrow/Page; laptop +Ctrl+Shift+Arrow/Page | Synth settings ring | 2, exact ring state not implemented |
| Orca+H/F11/Alt+B/Alt+1–6; desktop Orca+Backspace | No corresponding default NVDA global gesture | 3, no speculative interception added |

Ordinary modified keypad application gestures remain native unless the exact
NVDA chord is recognized. Existing v89 handling of unbound `numLockNumpad3/9`
VK forms is retained; those are distinct from NVDA's non-extended navigation
identities and cannot justify a new navigator mapping.

## Every remaining suppressed global command family

The `_linux_rdaccess_known_unimplemented`, desktop, laptop, collision, and
plain keypad tables were inspected together. The matrix above covers their
keypad, synth, settings, formatting, and focus/review entries. Their additional
global entries remain category 2:

| NVDA gestures | Exact functionality still missing |
|---|---|
| NVDA+N/Q | NVDA menu and quit; opening/quitting Orca is a different operation |
| NVDA+C/R/X/D | Clipboard report, OCR, last speech, annotation details |
| NVDA+F9/Shift+F9/F10 | NVDA review marking, return to mark, select/copy |
| NVDA+F1/Ctrl+F1/Ctrl+Shift+F1/Ctrl+F2/Ctrl+F3 | Developer object/app/display information, logging, plugin reload |
| Desktop NVDA+Shift+S; laptop NVDA+Shift+Z | Per-application NVDA sleep state |
| NVDA+Ctrl+Escape; +Shift+W/=/−/I/L | Screen curtain and Windows magnifier controls |
| NVDA+Alt+Arrow; +Shift+Alt+Arrow | Windows magnifier pan/edge pan |
| NVDA+Shift+D; +Alt+S | Windows audio ducking and sound split |
| NVDA+Alt+R/Tab; +Ctrl+Alt+T | Remote control and touch settings |
| NVDA+Alt+K/L/J/T | Braille autoscroll/rate/mode states |
| NVDA+Alt+M | NVDA math interaction state |
| NVDA+Alt+Home/End | Review selection start/end |
| NVDA+Ctrl+Alt+Arrow | Full row/column reading without moving the NVDA caret/review target |

Orca's `readCharAttributes` queries the focused object with its caret, while
NVDA's two formatting gestures explicitly distinguish caret and review. Orca
flat review and a detailed Where Am I report cannot replace those semantics.
The same distinction rules out mapping navigator and review operations to
similarly named flat-review methods. The focused-shortcut command is the one
suppressed candidate for which a small isolated equivalent was demonstrated.

## Browser matrix

Each row includes the Shift previous-direction gesture. Native structural
navigation depends on Orca's document/focus-mode gate. Adapted commands also
require a fresh remote provenance claim. Refused claims are removed before
typing can leave them for a later local key.

| Keys | NVDA type | Orca 42 outcome | Category |
|---|---|---|---|
| H; 1–6 | Heading / heading level | Same native types | 3 |
| K | Link | Same native type | 3 |
| F | Form field | Native formField goNext/goPrevious API | 1 |
| B | Button | Same native type | 3 |
| X | Checkbox | Same native type | 3 |
| C | Combo box | Same native type | 3 |
| D | Landmark | Translate to Orca M landmark; Orca D is live region | 1 |
| E | Edit | Native entry type | 3 |
| L / I | List / list item | Same native types | 3 |
| Q | Block quote | Same native type | 3 |
| T | Table | Same native type | 3 |
| R | Radio button | Same native type | 3 |
| G | Graphic | Native image type | 3 |
| S | Separator | Same native type | 3 |
| P | Text paragraph | Native paragraph convention retained; scope needs live comparison | 3 |
| U / V | Unvisited / visited link | Same native types | 3 |
| A | Annotation | Orca A is clickable; no exact annotation object | 2 |
| M | Frame | Orca M is landmark; no equivalent frame object | 2 |
| N | Non-link block | No equivalent structural object | 2 |
| O | Embedded object | Orca O is chunk; no equivalent embedded object | 2 |
| W | Spelling error | No equivalent structural object | 2 |
| 7–9 | Heading level | Existing native heading factories | 1 |
| Shift+7–9 | Previous heading level | Shift changes printable AT-SPI strings | **4 → 1**, resolve remote-proven physical keycode |
| NVDA+V | Screen layout mode | Native web layout/object mode | 1 |
| NVDA+Ctrl+F; NVDA+F3/Shift+F3 | Find / next / previous | Native web find operations | 1 |
| NVDA+Shift+F10 | Native selection mode | No equivalent Orca 42 state | 2 |
| Alt+Up/Down | Collapse/expand virtual-caret object | No equivalent isolated API; consume only in browse context | 2 |
| Ctrl+Alt+Arrow | Table cell movement | Native table handler translation in browse context | 1 |
| Ctrl+Alt+PageUp/PageDown/Home/End | Table edge keeping other coordinate | Native table coordinate operation | 1 |

The Shift-heading repair uses `getKeycode('7'/'8'/'9')` and a matching remote
claim, not a punctuation-symbol translation. Isolated Xvfb/Gdk confirms US
level-1 symbols `&`, `*`, `(` for those physical digit keys. Local punctuation,
a different physical keypad key, focus-mode typing, browser chrome, and stale
claims do not become heading navigation. The regression test executes the
installed Orca 42 mode gate for A/F/M/N/O/W/D and Shift-heading typing contexts.

## Focused shortcut implementation and evidence

NVDA's global Shift+Numpad2 and laptop NVDA+Ctrl+Shift+. report shortcuts of
the focused object. Orca's `mnemonicShortcutAccelerator(obj)` returns localized
mnemonic, full menu shortcut, and accelerator. The new adapter uses focus only,
prefers a full menu path over its mnemonic, includes a distinct accelerator,
and delegates one message to native `presentMessage`. Empty shortcut data
reports `No shortcut key`. This native presenter handles both speech and braille
according to Orca's configured output settings. Missing APIs leave the command
consumed; failure or partial presentation does not invoke detailed Where Am I
or retry a second presenter.

The dedicated tests execute native Orca 42 `presentMessage`, click handlers,
Say All, desktop KP_Add bindings, and the web structural gate. Before the fixes,
the controller tests reproduced missing shortcut reporting, incorrect pointer
click passthrough, incorrect caret Say All passthrough, and shifted-heading
failure. See the final validation report for final interpreter and full-suite
counts; the logs here retain the failing reproductions separately.

## Live-test-only risks

- NVDA review scope and Orca flat-review scope, word/line boundaries, repeated
  spelling, and report detail are not proven equivalent by shared key names.
- Actual remote browser quick-navigation output, autofocus and contenteditable
  transitions, caret/review formatting, and accessible accelerator content need
  Firefox/NVDA Remote/Orca testing.
- Pointer clicks and review Say All are explicitly unsupported for recognized
  NVDA gestures; no pointer or review API was guessed to restore them.
- XTest cannot attribute simultaneous identical local and remote keys. Window
  manager grabs can intercept table arrows before Orca sees their claims.
- Legacy missing scan codes retain conservative handling; real Windows Num
  Lock/Shift keypad conversion and braille display shortcuts require live input.
