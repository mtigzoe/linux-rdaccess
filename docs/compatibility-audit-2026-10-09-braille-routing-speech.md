# Remote braille routing and Say All audit — 2026-10-09

## Confirmed defects

Remote `braille_routeTo` called the active Orca script's `processRoutingKey`
directly. Orca 42 normally handles a routing event through
`orca._processBrailleEvent`, which calls `speech.stop()` before dispatching it.
Routing is absent from `braille.dontInteruptSpeechKeys`; ordinary panning is
exempt. The bridge bypassed this interruption, so an earlier Say All could
continue speaking after the user chose a different caret position.

A delayed Say All cancellation also remained eligible when the active script,
window and transport were unchanged. Orca's native default-script progress
callback restores the old text's caret and collapses its selection on
`INTERRUPTED`. The reproduction moved the caret to offset 9 through routing,
then observed the old callback move it back to offset 0.

Before the production changes, three new regression assertions failed:
no native stop occurred, a pending initial Say All idle still spoke `FIRST`,
and a late cancellation restored the pre-routing caret. The fixture uses the
existing extracted Orca 42 Speech Dispatcher methods and native default-script
progress callback, with fake speech clients and accessible text objects.
Their executable method bodies were compared with the installed Orca sources;
docstring indentation was excluded from that comparison.

## Changes

- Run the routing interruption on Orca's main loop, after display, focus,
  session, live cell bounds and routing-handler checks succeed. Unsupported
  or stale commands do not interrupt speech.
- Stop the local speech client and immediately send the existing NVDA Remote
  `cancel` message before invoking the routing handler.
- Increment a routing epoch before stopping. Say All captures that epoch in
  its session guard, so old progress, cancellation and iterator continuations
  cannot replay their caret or speech after routing. A new Say All remains
  eligible, and ordinary Ctrl cancellation retains native caret cleanup.
- Upgrade the generated controller to v108 and Say All customization to v5.
  Preserve the exact historical v4 hook for strict upgrades. The legacy
  script-call fallback performs the same interruption before routing.
- Add the routing regression module to the existing braille contract inventory
  and its workflow matrix entry.

## Focused local validation

| Coverage | Result |
| --- | --- |
| New routing/speech regressions | 8 tests passed |
| Existing braille display, cell alignment, semantic braille and Orca adapter tests | 111 tests passed |
| Say All presentation/callbacks, speech lifecycle/sequence and controller upgrades | 57 tests passed |
| Disposable TCP NVDA Remote loopback, including routing cancel and stale caret rejection | 25 tests passed |
| Installed CLI in private temporary homes and selected configuration checks | 14 tests passed |
| Selected legacy braille tests | 9 tests passed |

These are 224 distinct tests, with no outstanding failures or skips. The updated
braille contract runner also passed all 39 tests in its inventory; those tests
are included in the totals above. Initial test-double errors were corrected
before the final runs.

Additional checks passed: changed Python compilation, Python 3.10 grammar,
generated patch validation, and `git diff --check`. A disposable manual upgrade
generated genuine v107 controller and v4 customization output using the
pre-change module, then upgraded both with the new module. It verified the
original backups, mode 0600, idempotence and Python 3.10 grammar.

## Limits

No live Windows NVDA, audible Speech Dispatcher output, user desktop, Linux
application acceptance session or physical braille display was tested. Full
repository discovery was not run. Loopback tests exercise real transport
framing with native-method fixtures and fake accessible objects; they do not
establish Windows synthesis timing or hardware routing accuracy.

This change covers raw remote routing commands. It does not change panning,
braille home, emulated keyboard commands or semantic AT-SPI action/caret
requests. A native stop failure is logged without its exception text, and the
bridge still sends the NVDA cancellation and attempts routing. The routing
epoch prevents stale bridge callbacks but cannot force a failed native speech
client to stop its audio.

Existing installations need the normal connect/update flow and an Orca restart
to load the updated controller, adapter and Say All wrapper. No real user
configuration was modified during this audit. GitHub Actions were not monitored
or awaited, and the PR was not merged.
