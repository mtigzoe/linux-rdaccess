# NVDA–Orca Say All presentation lifetime audit

Base: `main` at `f1d9628`, containing PR #40.
Branch: `fix/say-all-presentation-lifetime`.

## Confirmed defect

The remote Say All wrapper checked connection, input generation, stop requests,
and replacement runs, but omitted Orca's active script and top-level window.
A completion callback already queued on GLib could therefore forward another
utterance after application/window activation changed. Orca's native progress
callback could also restore the old accessible as locus of focus, move its
caret, and collapse its text selection. Late cancellation and index-mark
callbacks remained usable in that old presentation context as well.

Seven new test methods against unchanged production code produced eight
assertion failures, including subtests. The reproduction uses the frozen Orca
42 speech-dispatcher methods and an unchanged copy of its default-script
progress callback. The latter was checked against the installed native AST;
its copyright and license header are retained in the fixture. Tests observed
an unwanted second utterance, stale caret writes, and stale region-change
notifications. Applications and the speech client are test doubles.

## Fix

Each run now captures the native active script and window before scheduling
its first utterance. Iterator advancement and all progress callbacks check
that context on Orca's main loop. An observed activation change permanently
expires the run, including its cancellation callback, and clears the old
native Say All bookkeeping through the existing guarded cleanup.

Normal caret/locus changes within the current script and window remain valid.
Equivalent window proxies compare by equality. An expired run cannot revive
when its original window returns or clear a replacement run's bookkeeping.

The customization hook advances from v3 to v4. Recognized v1/v2/v3 files upgrade
strictly through the existing private-backup path. As with other customization
patches, applying the files and restarting Orca activates the fix; runtime
hot-upgrade of an already wrapped v3 speech server is not provided.

## Focused validation

| Check | Result |
| --- | --- |
| New native callback, presentation lifetime, proxy equality, and upgrade regressions | 10 passed |
| Existing Say All, speech sequence, speech lifecycle, keyboard customization, and reconnect tests | 65 passed |
| Configuration/private writes and validation | 14 passed |
| Installed CLI acceptance in disposable homes | 4 passed |
| Disposable NVDA Remote TCP loopback, including stale-window speech forwarding | 24 passed |
| Actual v3 output from the saved pre-change generator, upgraded to v4 | Passed; original backup and private modes preserved; repeat update was a no-op |
| Changed Python compilation, Python 3.10 grammar, native fixture AST comparison, and whitespace checks | Passed |

All 117 focused tests passed on Python 3.10.12 with zero skips. An initial
configuration command used an incorrect unittest class name; the corrected
selection passed. The four installer acceptance tests in that invocation also
passed. There are no outstanding test failures.

## Limitations

The full suite, live Windows NVDA/Orca interaction, desktop GUI acceptance,
audible speech, and physical braille devices were not tested. The TCP test uses
production framing on localhost, not a Windows screen reader or external relay.

This guard detects script/window changes when a queued callback or iterator
checks them. A leave-and-return transition entirely between checks is not
observed. Document replacement or focus changes within the same script/window
are not independently invalidated; normal Say All needs to move focus there.
Already forwarded speech is not removed from Windows by this change.
