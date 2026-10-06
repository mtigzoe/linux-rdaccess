# Compatibility audit, October 7, 2026

Base: `main` at `244a1e2` (PR #14 was merged on October 6, so this round is a new
branch and a new PR). Authorities: Orca 42.3 (`ORCA_42_3`) and NVDA 2026.2
(`release-2026.2`) source. This round adds the live-test trace
([live-trace-diagnostics.md](live-trace-diagnostics.md), controller v80) and fixes
one gap found by cross-checking NVDA's gesture declarations (controller v81).
Nothing here is live-verified; the live acceptance checklist is unchanged.

## NVDA+ gesture cross-check

All `NVDA+` gestures declared with `@script(gesture=...)` in NVDA's
`globalCommands.py` (147 declarations, 223 layout-expanded entries) were mapped to
VK/extended identities and replayed through the patched controller with the new
trace, in both layouts, to read each result's disposition.

| result | entries |
| --- | --- |
| suppressed (consumed; unsupported command, unsupported object/review, collision) | 188 |
| translated to a native Orca operation | 24 |
| not mapped (non-extended navigation-cluster VKs, see below) | 9 |
| forwarded to Orca | 2 (both artefacts, see below) |

Defect found and fixed: NVDA binds NVDA+Numpad5, NVDA+NumpadMinus,
NVDA+Shift+NumpadMinus, NVDA+NumpadDivide, NVDA+NumpadMultiply and
NVDA+NumpadEnter with plain `kb:` gestures (`globalCommands.py` lines 1335, 1382,
1464, 1618, 1644, 1812), so they exist in the laptop layout too. The controller
consumed them only in the desktop layout; with `LINUX_RDACCESS_NVDA_LAYOUT=laptop`
they reached Orca as Orca-modifier+keypad keys (Orca 42 binds Orca+KP_Divide to
route-pointer-to-item and Orca+KP_Enter to its own commands, see
`desktop_keyboardmap.py`). Their VK identities are unambiguous in NVDA's
`vkCodes.py` ((0x0C, any), (0x6D, any), (0x6A, any), (0x6F, any), (0x0D, extended)).
Regression: `tests/test_layout_keypad_gestures.py` fails for exactly the six laptop
cases before the fix.

Findings left unchanged:

- The two forwarded entries are NVDA+Numpad3/Numpad9 (next/previous in flow) in the
  laptop layout. NVDA names these identities `(0x22, False)` and `(0x21, False)`,
  non-extended PageDown/PageUp. The controller does not treat a non-extended
  navigation-cluster VK as the keypad without proof in the payload, so the
  gestures remain unintercepted by design. The desktop `0x63`/`0x69` entries are
  VK_NUMPAD3/9, which NVDA names `numLockNumpad3`/`9` and leaves unbound; their
  comment was corrected, behaviour is unchanged (consuming an unbound NVDA+key).
- The nine unmapped entries are NVDA+Numpad1/2/4/6/7/8, NVDA+NumpadDelete and
  NVDA+Shift+NumpadDelete (non-extended navigation-cluster identities, same rule)
  plus NVDA+Shift+F9, which the replay script could not name (key-name case); the
  controller's own list already consumes it.

## Review and object navigation

Unchanged: parent/next/previous/first-child, focus<->navigator, activate
navigator, mouse<->navigator, flowed next/previous, review character/word/line,
review top/bottom/start/end and review Say All stay consumed. Orca 42 flat review
(`KP_*` bindings) has its own item model and a global review context; it is not
NVDA's navigator/review cursor, and nothing in Orca 42's public script API
reproduces NVDA's object hierarchy walk. These commands need live semantic work.

## Reviewed, no provable defect found this round

Read for the areas below against the code; no failing case was constructed, which
is not evidence of correctness for the live paths. Ctrl speech interruption (Ctrl
cancels NVDA once, repeats do not resend, 150 ms throttle for local cancels);
generation checks on queued GLib callbacks; reset/held-key ownership (failed
releases stay owned for retry); Caps Lock deferral and Num Lock repeat; the Orca
hooks' use of Orca's own mode gate (`useStructuralNavigationModel`) so
letters/table keys are untouched in focus mode, editable controls and browser
chrome.

## Live-only gaps

Firefox: real browse/focus mode transitions after tab switches and returns from
browser chrome; ARIA application/grid widgets; whether `inDocumentContent` is
false for the address bar on Mint's Firefox; contenteditable. Tables: nested
tables, row/column spans (the edge commands pass computed coordinates to Orca's
`goCell`; span behaviour is Orca's), non-uniform tables, XFCE shortcut
interception of Ctrl+Alt+Arrow. Speech: audible cancellation and Say All pacing
against Windows NVDA's synthesizer. Braille: Orca `panBrailleLeft/Right`
semantics against NVDA's scroll commands, routing, tether/follow-focus. Desktop
applications (Thunar, panel/menu, dialogs, Mousepad, Xed, VS Code): no static
defect identified; no application-specific code was added.
