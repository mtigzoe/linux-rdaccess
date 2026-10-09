# Semantic braille routing and speech audit — 2026-10-09

## Expected behavior

NVDA-native braille caret routing should interrupt Orca/remote speech before
moving the caret. Delayed Say All callbacks must neither resume reading nor
overwrite the chosen position or selection. Invalid and stale requests must
leave current speech alone. See the
[NVDA Linux behavior contract](../.github/NVDA_LINUX_BEHAVIOR.md).

## Native reference

Followed [Orca source references](../.github/ORCA_SOURCE_REFERENCES.md). Installed
Orca reports `42.0`; package metadata is `42.0-1ubuntu2`. Inspected installed
`orca.py`, `braille.py`, `scripts/default.py` and `speechdispatcherfactory.py`
under `/usr/lib/python3/dist-packages/orca/`.

Retrieved the pinned 42.3
[Orca runtime](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/orca.py),
[braille implementation](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/braille.py),
[default script](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py)
and [speech backend](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/speechdispatcherfactory.py).
ASTs of `_processBrailleEvent`, `processRoutingKey` in the default script,
`__sayAllProgressCallback`, `_say_all`, `sayAll` and `stop` match the installed
methods. This comparison applies to these methods, not the complete versions.

Native braille routing interrupts speech before dispatch; ordinary panning keys
are listed among the exceptions. Speech Dispatcher posts progress callbacks on
GLib and posts a continuation after END. Orca's default Say All callback restores
the spoken caret and clears selection on interruption/completion. The tests reuse
existing licensed native method excerpts with simulated speech/AT-SPI state.

## Confirmed defect — automated-tested reproduction

`lrd_a11y_caret` validated snapshot ownership and moved the AT-SPI caret, but
bypassed the raw routing path's speech stop and routing lifetime increment.
Consequently, an already queued END could continue forwarding the next utterance,
and a late CANCEL could overwrite the explicitly chosen position.

Two TCP regressions establish the effects: after semantic routing to offset 9,
an END forwards `SECOND` instead of a single cancel; a delayed CANCEL restores
offset 3 instead of retaining 9. Eight new unit methods cover interruption order,
late callbacks, routing before the first synthesis idle, replacement Say All,
invalid/stale input, declined setters, stop failures and modern/property setters.

The final ten methods were run with the genuine model, adapter and controller
generator imported from main `5e48d58`. They produce 11 assertion failures,
including subtests, with no errors or skips. The invalid/stale-input method is a
positive control which already passes on the original implementation.

The first TCP cancellation fixture omitted native `lastInputEvent`, causing a
fixture error before caret rollback could be inspected. Added the existing native
state value and repeated the baseline before changing production code; both TCP
methods then failed on the intended behavior with no errors. All final baseline
and passing results use that corrected fixture.

## Implemented — code-reviewed

Pass the controller's existing routing speech-stop callback through the adapter
to the AT-SPI caret operation. Run it only after validating the semantic object,
focus/script/window lifetime, character bounds and a usable setter. It increments
the routing lifetime before stopping local speech and sending the NVDA Remote
cancel, then invokes the setter once. Existing Say All guards expire old progress,
END continuations and CANCEL caret restoration while preserving a new run.

Invalid requests and objects without a writable caret do not stop speech. A
supported setter which declines or fails is not retried; native braille dispatch
also interrupts before its handler's result is known. Local stop failures remain
contained, and routing lifetime invalidation still prevents old callbacks from
continuing the remote reading.

The generated controller marker advances from v113 to v114 and recognizes v113
for upgrade from the original backup. The updater installs the adapter and model
beside it. Wire messages and root Python compatibility wrappers are unchanged.

## Automated-tested validation

| Coverage | Result |
| --- | --- |
| Existing braille matrix contract | 90 tests passed |
| Existing remote-protocol matrix contract | 34 tests passed |
| Existing speech/focus matrix contract | 10 tests passed |
| Existing keyboard/browse matrix contract | 79 tests passed |
| Adapter, AT-SPI model/bounds, speech callbacks/lifecycle/sequence, braille protocol/reload and installed CLI | 172 tests passed |
| Focused legacy patch/install regressions | 44 tests passed |

These are 429 distinct focused tests under Python 3.10.12, with no final failures
or skips. All ten added methods reside in modules already selected by the
compatibility matrix; its inventory remains unchanged. Existing tests also cover
control handoff, departure, reconnect and stale snapshot ownership.

A disposable install generated the genuine prior v113 controller, upgraded it to
v114 from the unchanged original backup, copied both new runtime modules, and
remained idempotent. Configuration and backup modes remained 0600. The installed
standalone adapter rejected an out-of-range route without stopping speech and
called the interruption hook before a valid caret write. No real configuration
was modified. Changed/generated Python compilation, Python 3.10 grammar, exact
matrix inventory, root-file preservation and whitespace checks passed.

## Known issue / not verified

Native callback fixtures and actual loopback TCP establish application-side
writes, callback lifetimes and outbound cancel/speech packets. They do not verify
Windows NVDA utterances, braille text/dots, audible speech or physical braille.
Real XFCE, Thunar, Mousepad, terminal, Firefox and VS Code acceptance remains
unverified. This environment has no `DISPLAY` or `WAYLAND_DISPLAY`.

Native silent synthesis timing remains independent of Windows NVDA completion.
A provider may refuse a valid caret operation after speech is interrupted; the
bridge reports the failure without retrying. Other Orca versions and mixed
runtime versions are unverified. Restart Orca after installing the v114 controller
and revised adapter/model. GitHub Actions were not monitored and the PR is left
for independent review.
