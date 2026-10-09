# Remote browse input-help audit — 2026-10-09

## Confirmed defect

Orca 42's native `KeyboardEvent.shouldConsume()` assigns its command presenter
while `orca_state.learnModeEnabled` is set. The bridge's custom browse hooks
ran first, so remote Find, Find Next/Previous, layout, form-field, heading-level
and table-edge gestures could execute commands instead of describing them.
Table-edge help could query AT-SPI cells. These hooks also swallowed command
descriptions in focus mode and browser chrome.

Using the physical binding's description would describe another command for
some translated gestures: Orca+V changes verbosity, while the plain F3 emitted
by CapsLock+F3 can select Orca's shortcut list. A deferred consumer received
during help could also execute after help was turned off.

The 13 new regression methods were run against genuine v111 controller output
generated with main commit `6d7f283`. They produced 44 failing assertions across
their subtests, with no errors or skips. The frozen dispatcher and presenter
are unmodified Orca 42 methods; their ASTs match the installed native methods.

## Fix

After claiming an eligible remote gesture, detect learn mode before resolving
document context, navigation actions or table cells. Call the original native
dispatcher to retain its refusal checks and script bookkeeping, then select
the native handler for the NVDA command being translated. Orca's native
presenter retains the handler's localized description and `learnModeEnabled`
preference. Heading levels 7–9 use Orca's localized level-description pattern
when no registered handler exists, without constructing a navigation action.

Table edges and unsupported NVDA gestures have no exact native command
description here. Preserve native help dispatch without presenting an unrelated
physical binding or performing an action. Ordinary landmark and table-arrow
help continue through the native presenter.

Keep release ownership for gestures received in help. Turning help off before
their release or deferred callback cannot execute those gestures; fresh remote
presses can execute normally. Help callbacks also check shortcut capture,
active-script identity and the control-session epoch before presenting.

The generated controller advances from v111 to v112 and recognizes v111 for
upgrade. Root-level Python compatibility wrappers are unchanged. The browser
regression module already belongs to the existing GitHub Actions
`keyboard-and-browse` matrix entry, so its inventory remains unchanged.

## Focused validation

| Coverage | Result |
| --- | --- |
| Keyboard/browse matrix contract, including 13 new regression methods | 68 tests passed |
| Legacy browse, landmark/table translation, provenance and releases | 71 tests passed |
| Controller upgrades, patch integrity and direct commands | 40 tests passed |
| NVDA Remote TCP loopback matrix contract | 28 tests passed |
| Installed CLI in private temporary homes | 4 tests passed |

These are 211 distinct focused tests with no final failures or skips. Coverage
includes localized forward/reverse descriptions, Insert and CapsLock Find
gestures, repeats, releases, stale callbacks, native duplicate/timestamp
refusals and shortcut capture. An initial patch put a handler lookup in the
wrong helper; the failing run exposed it, the lookup was corrected, and all
affected suites passed. The final browser module also passed after adding the
native-compatible `function` attribute to the description-only heading handler.

A disposable update generated genuine v111 output with the pinned base, then
upgraded it to v112. Current patch validation, original backup contents, mode
0600, idempotence, generated/changed Python compilation, Python 3.10 grammar,
native fixture AST comparisons and whitespace checks passed.

## Limits

Native dispatcher and presenter bodies execute with simulated Orca scripts,
module globals and keyboard events. Live Windows NVDA, audible help speech,
physical braille, Linux application acceptance, Xvfb and full repository
discovery were not run. Loopback tests use real TCP framing with a simulated
Orca runtime. Direct controller script-command input-help paths were not
changed by this fix.

Existing installations need the normal connect/update flow and an Orca restart
to load the updated controller and hook. No real user configuration was changed.
GitHub Actions were not monitored or awaited, and the PR was not merged.
