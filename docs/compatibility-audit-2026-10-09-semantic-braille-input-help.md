# Semantic braille input help audit — 2026-10-09

## Expected

NVDA-native semantic braille routing should describe its command during Orca
input help without activating a control or choosing a text caret position.
A request received during help must not become an action after help exits.
Preserve localized native descriptions, explicit handler exemptions, and
focus/session ownership. See the
[NVDA Linux behavior contract](../.github/NVDA_LINUX_BEHAVIOR.md).

## Native reference

Followed [Orca source references](../.github/ORCA_SOURCE_REFERENCES.md). Installed
Orca reports `42.0`; the package is `42.0-1ubuntu2`. Inspected installed
`input_event.py`, `scripts/default.py` and `braille.py` under
`/usr/lib/python3/dist-packages/orca/` and retrieved their pinned official
[input event source](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/input_event.py),
[default script](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py)
and [braille source](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/braille.py).

The installed and pinned ASTs match for `InputEventHandler.__init__`,
`InputEventHandler.processInputEvent`, `KeyboardEvent._presentHandler`,
`Script.setupInputEventHandlers`, `Script.processRoutingKey`,
`Component.processRoutingKey` and `Text.processRoutingKey`. This establishes
equivalence of those methods only, not of the versions as a whole.

Native component routing invokes the accessible action; native text routing
sets its caret through script utilities. These are the operations represented
by the bridge's semantic action/caret requests. The common native routing
handler enables help by default and supplies its localized description. Its
public `learnModeEnabled` preference documents whether help describes a command
or permits the action; the keyboard help presenter uses that public metadata.

As recorded in the [raw braille help audit](compatibility-audit-2026-10-09-braille-input-help.md),
both installed and pinned `processInputEvent` read `_learnModeEnabled` while the
constructor assigns `learnModeEnabled`. This fix follows the declared public
handler contract and does not claim a live reproduction of that native
braille-dispatch spelling discrepancy.

## Confirmed defects — automated-tested

The semantic action and caret callbacks bypassed the raw braille help dispatcher.
With Orca help enabled, `lrd_a11y_action` activated the control and
`lrd_a11y_caret` moved the text caret instead of presenting help. Both operations
also executed when queued during help and dispatched after help exited, or
when help began before dispatch.

The 11 new regression/control methods run against the genuine controller
generator from main `409d6e6` produce 19 assertion failures, including subtests,
with no errors or skips. Native exemptions and stale presentation/session
controls already pass on that baseline.

## Implemented (code-reviewed)

Both semantic handlers capture help state on receipt and consult a common
main-loop help guard before performing an action or writing a caret. During
help, the guard validates the request's existing semantic object/presentation
context before cancelling speech or presenting a description. Obsolete requests
cannot announce help in a replacement focus, script, window, snapshot or session.

Current requests use the active script's `processRoutingKeyHandler` description
and `presentMessage`, including snake-case alternatives. Missing metadata,
description or presenter suppresses the action. Requests queued in help expire
after exit; an explicit native `learnModeEnabled=False` exemption still permits
the operation. Fresh requests after exit retain their previous behavior.

Help uses the existing local speech-stop and NVDA cancel path before presenting
the description. It does not increment the routing epoch, because no new caret
position was chosen. Native Say All END continuation expires while its CANCEL
callback retains native spoken-word caret/selection placement.

The generated controller advances from v115 to v116 and recognizes v115 for
upgrade. No adapter/model API or root Python compatibility wrapper changed.

## Automated-tested validation

| Coverage | Result |
| --- | --- |
| Braille matrix contract | 107 tests passed |
| Remote-protocol matrix contract | 39 tests passed |
| Keyboard/browse matrix contract | 79 tests passed |
| Speech/focus matrix contract | 10 tests passed |
| Adapter, speech lifecycle, braille protocol/reload, installed CLI | 91 tests passed |
| Focused legacy patch/install regressions | 44 tests passed |

These are 370 distinct focused methods under Python 3.10.12, with no final
failures or skips. Added eight unit methods and three TCP methods to suites
already selected by the existing compatibility matrix; its module inventory
requires no change. TCP tests inspect real bridge packets: cancel followed by
localized speech for each semantic request, no action/caret write during help,
no output after queued help expires, and working fresh requests after exit.

Unit coverage includes help entry/exit timing, native exemptions, missing
metadata, snake-case APIs, unknown objects, handoff/disconnect and
focus/script/window/snapshot changes. Native Say All fixtures separately verify
queued END cancellation and spoken-word caret restoration on CANCEL. An initial
fixture incorrectly expected the pre-END offset after delivering END; native
END advances the context offset, so END and CANCEL are tested independently.
That fixture correction required no production change.

A disposable installation generated the genuine prior v115 controller, upgraded
it to v116 from the unchanged original backup, preserved configuration backups
and 0600 permissions, copied both standalone modules and remained idempotent.
Executing that installed controller with its copied adapter/model preserved
semantic help and fresh actions after exit. No real configuration was modified.
Changed/generated Python compilation, Python 3.10 grammar, exact matrix
inventory, root-wrapper preservation and whitespace checks passed.

## Known issue / not verified

Automated fixtures and loopback TCP do not establish Windows NVDA speech or
displayed braille, audible speech, physical braille, or real Linux application
acceptance. No graphical display is available; live Windows/NVDA and other Orca
versions remain unverified. The opt-in speech probe was not enabled.

Restart Orca after installing the v116 controller. Braille-emulated keyboard
gestures remain a separate path outside this fix. GitHub Actions were not queried
or monitored; no merge was performed. The PR remains for independent review.
