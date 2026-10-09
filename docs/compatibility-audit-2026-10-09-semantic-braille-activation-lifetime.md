# Semantic braille activation lifetime audit — 2026-10-09

## Expected behavior

NVDA-native semantic braille actions and caret routing belong to the Orca
presentation which published their accessible objects. A script or window
activation change must expire queued requests even when `locusOfFocus` still
identifies the same accessible. A fresh publication must permit fresh requests.
See [.github/NVDA_LINUX_BEHAVIOR.md](../.github/NVDA_LINUX_BEHAVIOR.md).

## Native reference

Followed [.github/ORCA_SOURCE_REFERENCES.md](../.github/ORCA_SOURCE_REFERENCES.md).
Installed `orca --version` reports `42.0`; package metadata is
`42.0-1ubuntu2`. Inspected `/usr/lib/python3/dist-packages/orca/script_manager.py`
and `scripts/default.py`. Retrieved the pinned upstream 42.3
[script manager](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/script_manager.py)
and [default script](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py)
for comparison. The ASTs of `setActiveScript`, `onWindowActivated` and
`onWindowDeactivated` match these installed methods; this does not establish
general equivalence between Orca versions.

`setActiveScript` changes the active script without updating `locusOfFocus`.
`onWindowActivated` assigns `activeWindow` before its key-grab check, which can
return without updating focus. These native transitions establish that unchanged
accessible identity does not establish unchanged presentation ownership.

## Confirmed defects — automated-tested reproduction

1. A queued `lrd_a11y_action` still performs its cached AT-SPI action after the
   active script changes while the focus remains unchanged. The TCP regression
   observes an obsolete click instead of no action.
2. A queued `lrd_a11y_caret` still moves its editor's caret after a window change
   and same-editor refresh. The TCP regression queues old offset 7 and fresh
   offset 5, and observes writes `[7, 5]` instead of `[5]`.

Both paths used a lifetime based only on the focused accessible's ID. Live
validation also checked only that ID. A same-focus refresh therefore preserved
an obsolete receipt token even after script/window activation changed.

Before the production fix, eight new unit methods and two new TCP methods
produced 25 assertion failures, including subtests, with zero errors or skips.
The final tests were also run with the genuine adapter imported from main
`38aaf5d`: ten methods, the same 25 failures, no errors or skips. Two unit
methods are positive controls for equivalent window proxies/unchanged refreshes
and network-thread receipt reads; those already passed on the old adapter.

## Implemented — code-reviewed

The opaque semantic lifetime now contains focus ID, active-script identity and
active-window equality. Publication retains the same token for an unchanged
presentation, and creates a new token for an observed activation change.
Returning to an earlier activation after publication cannot revive an old
request. Validation rechecks all three values on Orca's main loop before touching
the cached AT-SPI object. Failed state reads/comparisons clear the registry and
lifetime; rejected old tokens do not clear a newer valid snapshot.

Receipt reads remain opaque and do not query Orca from the network thread.
Native actions, caret coordinates, protocol messages and the generated v113
controller are unchanged. The existing updater installs the revised standalone
adapter beside that controller. Root Python compatibility wrappers are unchanged.

## Automated-tested validation

| Coverage | Result |
| --- | --- |
| Braille compatibility matrix contract | 82 tests passed |
| Remote-protocol compatibility matrix contract | 32 tests passed |
| Speech/focus compatibility matrix contract | 10 tests passed |
| Keyboard/browse compatibility matrix contract | 79 tests passed |
| Adapter, AT-SPI model/bounds, braille protocol/hook reload, installed CLI | 129 tests passed |

These are 332 distinct focused tests under Python 3.10.12 with no final failures
or skips. Added the semantic braille unit module to the existing braille matrix
job and its checked inventory; both new TCP methods run in the existing protocol
job. No GitHub Actions status was queried or monitored.

Coverage includes queued actions/caret writes, same-focus activation changes
with and without refresh, fresh commands, observed changes and returns, equivalent
window proxies, script identity, snake-case API fallbacks, deactivation and
failed comparisons/reads. Existing matrix tests cover focus changes, control
handoff, master departure and reconnection lifetimes.

A disposable upgrade replaced the genuine old adapter, preserved the current
v113 controller and original configuration backup, kept configuration and backup
permissions at 0600, and remained idempotent. The installed standalone adapter
rejected obsolete action/caret requests and accepted a fresh caret request.
Changed/generated Python compilation, Python 3.10 grammar, matrix inventory and
whitespace checks passed. No real Orca configuration was modified.

## Known issue / not verified

The TCP peer is a simulated NVDA Remote client; Orca state and AT-SPI accessibles
are fixtures. These checks establish request ownership and application-side
calls, not Windows NVDA utterances, displayed braille text/dots, audible speech
or application accessibility acceptance. Live Windows NVDA, physical braille,
XFCE/Thunar/Mousepad/terminal/Firefox/VS Code and other Orca versions remain
unverified. This environment has no `DISPLAY` or `WAYLAND_DISPLAY`.

An activation change and return with no intervening publication or request
validation cannot be distinguished by this snapshot mechanism. The fix covers
changes observed at publication or execution. It does not add a wire presentation
sequence or an activation-event listener. Restart Orca after installing the
updated adapter to replace the imported module and expire existing snapshots.
