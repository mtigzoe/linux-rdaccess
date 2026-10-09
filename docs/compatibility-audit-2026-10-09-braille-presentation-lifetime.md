# Raw braille presentation lifetime audit — 2026-10-09

## Expected behavior

Queued braille routing, panning and return-to-focus belong to the Orca
presentation which produced the displayed cells. A script or window activation
change must expire those commands even while `locusOfFocus` still names the same
accessible. An expired routing/home command must not cancel current speech.
This follows [.github/NVDA_LINUX_BEHAVIOR.md](../.github/NVDA_LINUX_BEHAVIOR.md).

## Native reference

Consulted [.github/ORCA_SOURCE_REFERENCES.md](../.github/ORCA_SOURCE_REFERENCES.md).
The installed package is `orca 42.0-1ubuntu2`, and `orca --version` reports
`42.0`. Inspected its default script, script manager, event manager and braille
implementation under `/usr/lib/python3/dist-packages/orca/`.

Verified availability of the pinned upstream 42.3
[default script](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py),
[script manager](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/script_manager.py)
and [event manager](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/event_manager.py).
ASTs of `panBrailleLeft`, `panBrailleRight`, `goBrailleHome`, `processRoutingKey`,
`setActiveScript` and `processBrailleEvent` match the installed 42.0 methods.
These are comparisons of specific methods, not a claim that the versions are
generally equivalent.

Orca's script manager can update `activeScript` independently of `locusOfFocus`.
Braille commands operate through the active script and its native braille/review
context. The remote bridge must therefore retain the script and window which
owned its output rather than treating accessible identity as sufficient.

## Confirmed defect — automated-tested reproduction

The published raw-braille lifetime included only the accessible's identity.
`braille_focus_is_current()` rechecked that identity before dispatch, but did
not check the active script or window. A queued pan could invoke the replacement
script; routing or home could also stop local speech and send an NVDA Remote
cancel before acting in the wrong presentation context. Refreshing the same
accessible under the replacement script did not distinguish old queued commands
from fresh input.

All nine new regression methods were run against the genuine adapter from main
`eed6224`. They produced 14 failing assertions across subtests with no errors or
skips. Seven unit methods cover script/window transitions, observed changes
followed by a return, fresh publication, equivalent window proxies, script
identity, snake-case APIs, absent accessible focus and failed window comparison.
Two protocol methods cover stale routing/home and subsequent valid commands
over actual loopback TCP.

## Implemented — code-reviewed

Publish an opaque lifetime containing focused-accessible identity, active-script
identity and active-window equality. Retain the same lifetime for unchanged
refreshes and equivalent window proxies. Script instances must be identical.
An observed change creates a new lifetime, so returning to an old script/window
cannot revive an already expired command. Failed reads or window comparisons
invalidate the lifetime without logging application text.

The existing generated controller already checks this adapter lifetime before
queued raw panning, routing and home callbacks. This change strengthens that
check without changing native operations, dot generation, protocol messages or
the v113 controller. The updater copies the revised adapter beside the
controller. Root-level Python compatibility wrappers remain unchanged.

## Automated-tested validation

| Coverage | Result |
| --- | --- |
| Existing braille matrix contract, including seven new unit methods | 55 tests passed |
| Existing remote-protocol matrix contract, including two new TCP methods | 30 tests passed |
| Existing speech/focus matrix contract | 10 tests passed |
| Existing keyboard/browse matrix contract | 79 tests passed |
| Orca adapter, semantic braille, protocol parsing, hook reload and installed CLI | 101 tests passed |

These are 275 distinct focused tests with no final failures or skips. Both new
modules already belong to the Actions matrix; its inventory is unchanged.
The TCP tests observe no outbound cancel for stale routing/home commands, then
observe one cancel for a fresh command after publication of the new context.
They also check that obsolete script handlers are not invoked.

An initial test incorrectly treated braille-emulated keyboard keys as queued.
They execute synchronously on receipt, before the tested activation change, so
the two remaining failures after the first fix were test errors. That case was
removed from the queued-command regression; the final pinned-base reproduction
and all focused suites above use the corrected tests.

A disposable update replaced the genuine old adapter with the revised source,
left the generated v113 controller unchanged, preserved the original private
configuration backup, and remained idempotent. The installed standalone adapter
rejected a changed window. Generated/changed Python compilation, Python 3.10
grammar and whitespace checks passed. No real user configuration was modified.

## Known issue / not verified

This is automated evidence for raw-cell command ownership and cancel packets.
The test peer is not Windows NVDA, and the Orca script/state and speech client
are simulated. It does not establish Windows-side utterances, accessible
name/role/state wording, displayed dots or audible output.

Live Windows NVDA, physical braille, audible speech, Linux application
acceptance, Xvfb and full repository discovery were not run. This shell has no
`DISPLAY` or `WAYLAND_DISPLAY`; no live Windows probe event was collected.
Semantic AT-SPI action/caret commands and synchronous braille-emulated keyboard
input are outside this change. A transition away and back which is never
observed by a refresh or validation cannot be detected by this snapshot guard.

Existing installations need the normal connect/update flow and an Orca restart
to load the revised adapter. GitHub Actions were not monitored or awaited, and
the PR was not merged.
