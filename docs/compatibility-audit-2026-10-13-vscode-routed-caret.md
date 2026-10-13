# VS Code routed-caret CI failure classification — 2026-10-13

**Classification: confirmed pre-existing intermittent VS Code/Electron/AT-SPI
caret failure. One native-editor render race is now captured; other failure
paths and a reliable fix remain unresolved. Not introduced by PR #78.**
The routing failure is tracked in [issue #79](https://github.com/mtigzoe/linux-rdaccess/issues/79)
and remains open. This follow-up improves failure evidence; it
does not skip VS Code, retry routing, extend the timeout, or claim a routing fix.

## Evidence before and during PR #78

- [Main run 38192669607](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38192669607)
  failed at `df517ae` on 2026-10-12, before the companion extraction. The setter
  was accepted, but caret offset stayed at 12. Target events were 0, 25, 13, 12,
  with no event reporting requested offset 1.
- [PR #78 run 38411001738](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38411001738)
  failed at `e26ae4a` with the same diagnostics.
- [PR #78 run 38404978184](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38404978184)
  passed at `52f1a1e`. Both failed and successful historical runs installed
  VS Code `1.141.0-1791276758`.
- The GUI runner and `linux_rdaccess_core/accessibility/a11y_model.py` are
  unchanged between main and PR #78. The clean Linux checkout at main commit
  `ac1dbdb` and the archived PR head have identical normalized source lines.
  Windows checkout/archive line endings differ, rather than implementation.
- The isolated GUI test directly calls the Linux AT-SPI caret helper. It does
  not load the Windows companion or use Windows NVDA Remote/physical braille.

Completed logs and artifacts were read once for diagnosis. No new CI run was
requested, polled or awaited.

## Local reproduction in a private desktop

Linux Mint, system Python 3.10, desktop VS Code **1.141.0**, build commit
`2a59476c9bfcb90b3ddc372c36762471b7dfad1c`. The existing runner verifies its own
Xvfb display and private D-Bus daemon before changing accessibility status. Each
run creates fresh Code settings, extensions and fixture files. The active desktop,
Orca, NVDA connection, installed add-ons and relay settings were untouched.

| Test | Observed result |
| --- | --- |
| Unmodified main `ac1dbdb`, VS Code only | Initial run and next four passed; fifth repeat failed with offset 12 and no caret-1 event. |
| Archived PR head `e26ae4a`, six applications (`--skip firefox`) | Settings, Thunar, Mousepad, Terminal and Calendar checks passed; VS Code failed with the same routed-caret timeout. |
| Temporary 200ms pause before routing | Six runs passed; this alone did not establish reliability. |
| Temporary event/focus-aware 200ms quiet period | Five repeats passed; sixth failed, reporting target caret events **1 then 12**. This experimental workaround was removed. |
| Temporary trace-enabled quiet-period probe | Ten passed; logging/timing changed the experiment and these samples did not negate the prior failure. |
| Final diagnostic-only changes, VS Code only | Three passed, fourth failed. New evidence: requested=1, before=12, final=12, focused=True, elapsed about 18 seconds, **no target caret event after the request**. Failure remains a nonzero exit. |

The fixture types a 13-character value, presses Left, verifies caret 12, then
requests caret 1 through the existing helper. The accepted request sometimes
has no observable effect; another failed experiment briefly reached 1 before
returning to 12. A nominal API acknowledgement therefore cannot establish
successful routing.

Upstream [AT-SPI Text.set_caret_offset documentation](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Text.set_caret_offset.html)
defines a successful return as caret movement. VS Code's
[installed-revision TextAreaInput source](https://raw.githubusercontent.com/microsoft/vscode/2a59476c9bfcb90b3ddc372c36762471b7dfad1c/src/vs/editor/browser/controller/editContext/textArea/textAreaEditContextInput.ts)
suppresses closely spaced selection changes and changes within 100ms of its own
textarea updates. That is a plausible timing factor, **not a complete root-cause
proof**: the quiet-period failure demonstrates that waiting alone is insufficient.
The exact failing VS Code/Chromium/native accessibility interaction is still open.

## Follow-up: captured native-editor render overwrite

A private, loopback-only Chromium debugging connection observed the disposable
renderer while the original AT-SPI routing assertion ran. The actual editor was
a `DIV.native-edit-context` with native EditContext enabled, rather than a
textarea. The prior textarea-source timing hypothesis therefore did not fully
describe this default configuration.

The [preserved metadata trace](vscode-caret-render-trace-2026-10-13.json)
records the failing sequence relative to the accepted request:

| Time | Observation |
| --- | --- |
| -17ms | DOM selection-change event reports caret 12, native EditContext selection 12. |
| 0ms | AT-SPI accepts the request for caret 1. |
| +37ms, before render write | DOM anchor/focus are **1**; native EditContext selection remains **12**. |
| +37ms, after render write | `SimpleScreenReaderContent.updateScreenReaderContent` calls `Selection.setBaseAndExtent(12, 12)`, restoring DOM caret **12**. |
| +43ms | The next delivered DOM selection-change event reports **12**. |
| About 18 seconds | AT-SPI readback still reports 12; the assertion fails. |

The stack identifies the native screen-reader content render path. In the
[installed-revision SimpleScreenReaderContent source](https://raw.githubusercontent.com/microsoft/vscode/2a59476c9bfcb90b3ddc372c36762471b7dfad1c/src/vs/editor/browser/controller/editContext/native/screenReaderContentSimple.ts),
each focused screen-reader render writes the model selection back to the DOM,
even when the model selection has not changed. In this captured failure, that
write overwrote the external DOM caret before its selection-change event could
update the model. This is direct evidence of one upstream failure mechanism;
it does not prove every timeout has the same cause.

Native instrumentation reproduced the timeout in the first selection-aware
run and the first run with a keyboard-continuation check prepared. The initial
textarea-only observer had recorded no relevant events because it targeted the
wrong DOM element type; its two passing runs and third failing run were retained.
Instrumentation can affect timing, so the prior uninstrumented-main reproduction
remains the independent evidence that this is a real pre-existing defect.

Changing only the **disposable profile** to `editor.editContext=false` produced
one pass, including Right moving the routed caret from 1 to 2, then a second
run failed with the original timeout. Disabling native EditContext therefore
is not a demonstrated fix. No user settings or installed VS Code files changed;
no retry, profile workaround or renderer patch is shipped by this PR.

Renderer traces contain only fixture metadata, offsets, event types, and
selection-write stacks. Their times are observations from wall clocks with
millisecond resolution, not provider event-generation times. Full logs and
private fixture traces are preserved in the same evidence directory, under
`selection-trace-*`, `model-trace-*`, and `legacy-model-*`.

## Diagnostic changes and validation

The runner retains a bounded deque of 80 caret-event timestamps, offsets and
source proxies. On routing failure it prints only the last ten events for the
target after the request, with relative milliseconds, before/requested/final
offsets, elapsed time and current focus. Timestamps are observer callback receipt
times, not the originating provider's event-generation times. Labels, editable text, object IDs and
unrelated control events are excluded. The same setter and 18-second readback
assertion remain in use.

- Linux: **11 focused diagnostic unit tests passed**, including three new
  regressions for target/request-time filtering, output bounds/privacy and
  bounded caret timestamp collection.
- Windows Python 3.13: the three new metadata regressions passed. The Linux-only
  whole module has pre-existing POSIX permission/path assumptions and is not a
  Windows acceptance suite.
- Scoped Ruff critical-error check, Python compilation and `git diff --check`
  passed.
- Ruff format check flags both existing source files on unchanged main and the
  changed files. Broad existing formatting was not rewritten in this focused PR.
- Native GUI runs above preserve both passing and failing evidence. Their
  failure is **not** reported as a successful acceptance test.
- Full repository discovery, Windows NVDA speech, physical routing/caret and
  live user-desktop acceptance were not performed for this follow-up.

## Preserved evidence and remaining work

The original CI artifacts remain attached to the linked runs. Full CI logs,
artifact contents and local run logs were preserved under the local temporary
directory `lrd-vscode-review-20261013`; the corresponding private Linux evidence
is under `/tmp/lrd-vscode-review-20261013`. In particular:

- `main-ac1dbdb-vscode-5.log`: unchanged-main reproduction.
- `head-e26ae4a-full-except-firefox.log`: PR-head reproduction.
- `fixed-vscode-6.log`: failed experimental quiet period, including 1 → 12.
- `diagnostic-vscode-4.log`: final timed, focused, target-only failure.

Next work is to resolve the captured upstream render overwrite and remaining
selection/model/AT-SPI failure paths, then verify
real NVDA-origin VS Code routing/caret behavior under fresh consent. Keep the
focused defect and acceptance issues #59/#60 open. PR #78 remains open and
unmerged; this classification does not turn its failed GUI check into a pass.
