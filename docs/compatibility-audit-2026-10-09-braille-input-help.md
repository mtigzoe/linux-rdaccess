# Raw braille input help audit — 2026-10-09

## Expected

Remote braille routing and return-to-focus should present their native localized
descriptions during input help, without moving the caret or leaving flat review.
A queued help request must not turn into a real command after help exits.
Preserve each native handler's help preference: Orca's default panning handlers
remain usable in help. See the
[NVDA Linux behavior contract](../.github/NVDA_LINUX_BEHAVIOR.md).

## Native reference

Followed [Orca source references](../.github/ORCA_SOURCE_REFERENCES.md). Installed
Orca reports `42.0`; the package is `42.0-1ubuntu2`. Inspected installed
`script.py`, `input_event.py` and `scripts/default.py` under
`/usr/lib/python3/dist-packages/orca/`.

Retrieved the pinned 42.3
[script dispatcher](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/script.py),
[input handler implementation](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/input_event.py)
and [default handlers](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py).
ASTs of `Script.processBrailleEvent`, `InputEventHandler.__init__`,
`InputEventHandler.processInputEvent` and `setupInputEventHandlers` match the
installed methods. This establishes equivalence of those methods only.

Braille dispatch resolves native input handlers. Their public `learnModeEnabled`
metadata documents whether help describes a command or permits its action.
Default routing/home handlers enable help; both panning handlers explicitly
disable it. The keyboard help presenter also reads that public metadata.

The installed and pinned `processInputEvent` bodies read the private spelling
`_learnModeEnabled`, while their constructor assigns `learnModeEnabled`. This
change follows the declared public handler preference and description contract;
the tests do not execute that differing native braille dispatcher or establish
its behavior in a live Orca process.

## Confirmed defects — automated-tested

The raw NVDA Remote braille path called script methods directly, bypassing native
help metadata. Routing and home invoked their native action handlers instead
of presenting help. Custom panning handlers which enabled help also
executed instead of describing the command. Requests queued during help could
execute after it ended.

Nine new unit methods and two new TCP methods were run with the genuine
controller generator imported from main `b908cbe`. They produce 19 assertion
failures, including subtests, with no errors or skips. Positive controls cover
native exemptions and obsolete session/focus contexts which already worked.

## Implemented (code-reviewed)

The raw braille dispatcher captures the script and help state on receipt, retains
its existing session/display/focus checks, and rechecks help before invoking the
queued operation. Commands which use help cannot become actions after exit, and
help which begins before dispatch suppresses the action. Descriptions come from
the originating script's native handler and use `presentMessage` or its snake-case
API. Missing metadata/descriptions/presenters suppress routing/home in help.

Default panning and explicit native help exemptions still execute. Routing/home
help interrupts prior speech before presenting the description, using the
existing local stop and NVDA cancel path. It does not increment the routing
lifetime because no new caret position is chosen. Custom panning help preserves
the native panning exception to speech interruption.

The generated controller advances to v115, recognizing v114 for upgrade from the
original backup. Root Python compatibility wrappers are unchanged. One keyboard
fixture accepts the braille dispatcher's added method keyword; its panning
assertion is preserved.

## Automated-tested validation

| Coverage | Result |
| --- | --- |
| Braille matrix contract | 99 tests passed |
| Remote-protocol matrix contract | 36 tests passed |
| Keyboard/browse matrix contract | 79 tests passed |
| Speech/focus matrix contract | 10 tests passed |
| Adapter, speech lifecycle, braille protocol/reload, installed CLI | 91 tests passed |
| Focused legacy patch/install regressions | 44 tests passed |

These are 359 distinct focused methods under Python 3.10.12, with no final
failures or skips. Added the new unit suite to the existing braille matrix job and
its checked inventory. Both TCP methods run in the existing protocol job.

TCP tests observe cancel followed by one localized utterance and no native
routing call. Queued home help produces no output/action after exit; a fresh home
then produces one cancel and one native call. Unit coverage includes help changes,
native/custom preferences, unavailable help metadata, snake-case APIs, adapter
import failure, session handoff/disconnect and focus/script/window changes.

A disposable install generated the genuine prior v114 controller and upgraded it
to v115 from the unchanged original backup. It preserved private configuration
backups and 0600 permissions, copied both runtime modules and remained idempotent.
No real configuration was modified. Changed/generated Python compilation, Python
3.10 grammar, exact matrix inventory, root-file preservation and whitespace
checks passed. GitHub Actions were not queried or monitored.

## Known issue / not verified

Fixtures and actual loopback TCP establish command ownership and outbound
speech/cancel packets. They do not establish Windows NVDA utterances, displayed
braille, audible speech or physical braille. Real Linux application acceptance
and other Orca versions remain unverified. No graphical display is available.

This change covers raw Remote Access routing/home/panning. NVDA-native semantic
object requests and braille-emulated keyboard gestures use separate paths and
were not given new help behavior here. Restart Orca after installing the v115
controller. The PR remains for independent review; no merge was performed.
