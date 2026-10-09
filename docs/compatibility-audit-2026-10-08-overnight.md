# NVDA/Orca compatibility audit, October 8, 2026

Started from fetched `origin/main` at `6149012`, on
`fix/nvda-orca-compatibility-20261008`. Reviewed PRs #28–#33 and confirmed #34
was merged. GitHub reported no open issues. The Windows MCP configuration from
#34 and the NVDA mappings restored by #31 are preserved. No production
installation, running Orca/NVDA session, physical keyboard locks, braille
hardware, or live XFCE configuration was changed.

## Confirmed defects and root causes

| Defect | Root cause and correction | Regression evidence |
| --- | --- | --- |
| A braille navigation gesture released a keyboard key or modifier still held by the controller. | Legacy name-only keyboard events and VK-based braille emulation have different protocol identities but can resolve to the same X key. Compare resolved names before emulation, and borrow an already-held modifier without synthesizing its release. | Name-only Tab, Return, Down, Shift, Ctrl, and Alt regressions fail on the original controller. A private XTest regression confirms that original main physically releases held Tab/Shift/Ctrl/Alt and the correction keeps them down until their owned key-up. |
| Delayed semantic braille activation or caret routing acted on an obsolete focus. | Registry membership alone did not establish the current focus, and transport generation alone did not expire queued work within a connection. Capture an opaque focus lifetime at receipt, validate that lifetime and Orca's live focus on its main loop, and renew it after focus changes or invalidation. | Original unit regressions activate the old button and move the old editor's caret. Loopback regressions reproduce stale queued activation, including an old target still present as a sibling. Additional cases cover queued caret routing, focus moving away and back, valid neighbor actions, and repeated same-focus refreshes. |
| A failed GI Value description/current-value or selection query discarded otherwise usable focus data. | Explicit interface calls bypassed the guarded legacy dispatcher but only caught a narrow set of errors. Use the guarded explicit Value description call and match the legacy dispatcher's exception fallback. Preserve a numeric value when only its description fails; preserve text/caret when selection fails. | Three regression methods originally produce four errors: unsupported/unavailable Value text, failed current-value query during a focus snapshot, and failed selection lookup. All now pass without restoring the shadowed Accessible aliases addressed in #32/#33. |

Self-review added regressions for publication during a same-focus snapshot
rebuild and for focus leaving and returning to the same object. A reusable
object ID is insufficient for the latter; the final implementation uses an
opaque lifetime token. Same-focus rebuilds retain the receipt token until
publication, while failed or oversized builds clear it and the action registry.
These guards preserve valid commands without changing the wire protocol.

The GI fallback follows the query failure contract: for example,
[AT-SPI Value.get_text](https://docs.gtk.org/atspi2/method.Value.get_text.html)
accepts a `GError` output and can return no description. Its failure does not
establish that the control's numeric value or other properties are unavailable.

## Files and added tests

Production changes are limited to:

- `linux_rdaccess_core/connection/remote_access.py`: held-key comparison,
  semantic receipt context, and controller patch v102 upgrades from v99–v101.
- `linux_rdaccess_core/accessibility/orca_adapter.py`: semantic focus lifetime
  publication and live focus checks for actions/caret routing.
- `linux_rdaccess_core/accessibility/a11y_model.py`: guarded GI query fallback.

Sixteen unittest methods were added across five files:

- `tests/unit/braille/test_braille_protocol.py`: four methods for name-only
  key/modifier ownership and patch upgrade/idempotency/backup preservation.
- `tests/unit/braille/test_nvda_native_braille.py`: three methods for obsolete
  action/caret targets and receipt context during snapshot publication.
- `tests/integration/test_nvda_remote_loopback.py`: five methods for queued
  actions/caret, sibling membership, same-focus refresh, and returning focus.
- `tests/unit/accessibility/test_gi_shadowed_accessors.py`: three provider
  failure fallback methods.
- `tests/integration/x11/test_xtest_injection.py`: one actual X server
  held-key/modifier regression.

## Validation

System Python is 3.10.12. Tests use private Xvfb displays, private D-Bus
sessions, disposable profiles/configuration, doubles, and a TCP loopback peer.
The GUI runner verifies display and bus ownership before operating. It uses
the actual desktop VS Code binary, rather than the inherited Remote SSH CLI.

| Check | Result |
| --- | --- |
| Initial restricted headless baseline | 1,194 tests; 11 socket permission errors and 18 expected X11 skips. |
| Baseline with authorized socket access, display removed | 1,194 tests; passed with 18 expected X11 skips. |
| Final full Python 3.10 headless suite | 1,210 tests; passed with 19 private-X11 skips. |
| Final full Python 3.10 suite under private Xvfb | 1,210 tests; passed with zero skips. |
| NVDA Remote loopback | 15 tests included in full discovery; passed. Covers speech/cancellation, framing, key ownership, braille, reconnect and semantic commands. |
| Actual GTK/AT-SPI gallery | 38 checks; passed, 57 accessibility events. |
| All seven real Linux applications | 43 checks; passed, 196 accessibility events, no application skips. |
| Linux → latest rdAccess main (`7bfc0c86aa97044e044558d9cac24f9ba39c9d08`) | Seven semantic contracts passed; reverse action and heartbeat contracts also passed. |
| Compilation and Python 3.10 grammar | Passed; 146 Python files parsed. |
| Ruff 0.16.10 E9/F821/F822/F823 | Passed; extracted partial Orca fixtures excluded from name analysis. |
| Shell syntax and `git diff --check` | Passed. |

The additional headless skip is the new XTest regression; it passes under
Xvfb. No required local dependencies were missing. Local interpreter coverage
is Python 3.10; the existing CI matrices cover Python 3.10/3.12. Counts for
focused suites overlap full discovery and must not be added to its total.

Real application checks cover XFCE Settings Manager, Thunar, Mousepad,
XFCE Terminal, clock/calendar, Firefox, and VS Code: focus, text/caret,
selection, dialogs, menus, and focus restoration. The clock/calendar runner
explicitly reports two provider limitations: keyboard activation cannot open
the clock popup, and the calendar exposes no selected-date semantics. Its
private pointer-open/Escape checks do not establish date-navigation support.

Reproduce the principal checks from the repository root:

```sh
env -u DISPLAY -u WAYLAND_DISPLAY python3.10 -m unittest discover -s tests -t . -v
env -u DISPLAY -u WAYLAND_DISPLAY xvfb-run -a python3.10 -m unittest discover -s tests -t . -v
python3.10 -m unittest -v tests.integration.test_nvda_remote_loopback
python3.10 tools/diagnostics/gtk_atspi_smoke.py
python3.10 tools/diagnostics/real_gui_atspi_smoke.py
python3.10 -m compileall -q linux_rdaccess_core diagnostics tools tests
```

Diagnostic logs for this run are in `/tmp/rdaccess-final-headless.log`,
`/tmp/rdaccess-final-xvfb.log`, `/tmp/rdaccess-final-gtk.log`, and
`/tmp/rdaccess-final-real-gui.log`. Original-failure logs include
`/tmp/rdaccess-braille-before.log`, `/tmp/rdaccess-original-xtest.log`,
`/tmp/rdaccess-semantic-before.log`, `/tmp/rdaccess-semantic-wire-before.log`,
and `/tmp/rdaccess-provider-before.log`. These temporary logs are local
evidence, not committed artifacts.

## Remaining limits and tomorrow's Windows checks

The tests do not verify Windows NVDA's actual gesture consumption, audible
speech, TLS/real relay behavior, or a physical braille display. No live
acceptance was performed. Unsupported navigator/review commands, braille
keyboard typing, repeated current-line spelling, and Wayland remain subject
to the existing compatibility matrix. Same-focus text edits are not versioned
in the semantic wire protocol; the new lifetime guard is for focus changes,
not text revision tracking.

After review and applying the changes during a planned live session, test:

1. Insert and Caps Lock in desktop/laptop layouts; Caps/Num Lock state;
   modifiers, keypad commands, pass-next, and disconnect/reconnect with keys held.
2. Ctrl interruption during Say All; speech pacing, focus announcements,
   duplicates, and output immediately after reconnect.
3. NVDA+N local menu/control toggle; NVDA+F7; NVDA+Ctrl+F and
   NVDA+F3/Shift+F3; Firefox browse/focus transitions and plain F3/Shift+F3
   application behavior. Existing mappings are preserved.
4. Physical display panning, first/middle/last-cell routing, cursor/focus
   tracking, and reconnect. Where the peer emits legacy name-only keys,
   hold Shift/Ctrl/Alt while using a display-emulated navigation key and
   verify that the held keyboard modifier remains effective until release.
5. Rapid focus changes while semantic braille actions/routing are queued,
   including moving away from and back to the same control; normal fresh
   actions and routing must continue to work.
6. Normal application navigation in the tested XFCE applications, Firefox
   and VS Code, with particular attention to dialog focus restoration.
