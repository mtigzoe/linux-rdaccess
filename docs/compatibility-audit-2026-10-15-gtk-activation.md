# GTK activation CI investigation — 2026-10-15

PR [#92](https://github.com/mtigzoe/linux-rdaccess/pull/92) and issue
[#79](https://github.com/mtigzoe/linux-rdaccess/issues/79) remain open. This
follow-up changes only diagnostic window activation and CI evidence handling.
The Chromium source-build and NVDA/physical-braille limitations from the
[native Unicode investigation](compatibility-audit-2026-10-15-native-chromium-selection.md)
remain outstanding.

## What the failed job actually ran

In [run 38777751586](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38777751586/job/116569703410),
head `2f2a43b`, GTK startup and four AT-SPI event registrations passed.
Activation failed after the existing 15-second wait with:

```text
AssertionError: Timed out: GTK window activation by window manager
```

The seven-real-application step was **skipped**. The apparent `XFAIL VS Code
#79 ... fixture` line came from the mocked classifier unit test during the
compile step; it was not a native VS Code result. The later private Mousepad
routing/caret step passed both tests. The unit test now captures and asserts
its expected XFAIL output, avoiding that ambiguity in future job logs.

The prior [passing run 38758120277](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38758120277),
head `54a43e4`, used the same runner image `20261004.315.1` and packages:
xfwm4 `4.16.1-1`, xdotool `1:3.20160805.1-4`, AT-SPI `2.44.0-3`,
Code `1.142.0-1792035033` and Firefox `158.0`. Its native Code checks passed
Right=2/Left=1 and selection; the final count was 53 with zero expected failures.
The GTK runner, public GTK fixture, real-application runner and GUI workflow
are byte-for-byte unchanged between these two commits.

The failed activation predicate returned unsuccessful command results throughout
the wait; it did not raise a three-second subprocess timeout. The runner
discarded xdotool stderr and the workflow did not upload the private session's
WM/application logs. Therefore the **exact original X11/WM failure cannot be
established retrospectively**. This is an activation infrastructure/harness
failure, with no demonstrated GTK application, semantic bridge or Unicode-change
regression. A transient or failed WM startup is consistent with the evidence,
but remains an inference, not an established cause.

## Confirmed harness defects and correction

The old GTK check selected the final title match without requiring visibility
or membership in the window manager's client list. It retried
`xdotool windowactivate --sync`, discarded errors and trusted a zero command
exit as proof of activation. The real-application runner used the same sync
command inside a three-second subprocess timeout. That timeout could escape
its longer readiness wait.

The pinned [xdotool command source](https://github.com/jordansissel/xdotool/blob/v3.20160805.1/cmd_windowactivate.c)
and [sync wait implementation](https://github.com/jordansissel/xdotool/blob/v3.20160805.1/xdo.c)
show why the process exit alone is insufficient: the sync loop can exhaust its
internal wait without proving the requested active ID. The
[EWMH specification](https://specifications.freedesktop.org/wm/1.5/ar01s03.html)
defines the WM self-check, managed client list and actual active-window property.

The shared helper now uses each caller's **one existing wait budget**
(GTK 15 seconds; real applications 18 seconds) to:

1. Verify the root/child WM self-check and activation support.
2. Select a visible candidate that is also a WM-managed client.
3. Send **one non-sync activation request**.
4. Read the exact active-window ID while rechecking WM/target validity.

It never resends activation. Command errors and timeouts remain fatal. A stale
active ID after WM loss or target removal cannot produce success. No caret,
selection, focus, application or semantic assertion was weakened and no new
expected-failure classification was added.

Numeric state and bounded command stderr are retained in
`window-activation.jsonl`; failed activation also prints its state. Both
workflows that call the GTK runner explicitly install `x11-utils` (`xprop`)
and preserve the GTK transcript, WM stderr, application stderr and exit status.
The actual private runtime stays in a short `/tmp` path; only its fixture logs
are copied to the artifact directory. `pipefail` propagates GTK and observer
failures through `tee`.

## Focused native verification

All native checks used SSH to `cyber.local`, private Xvfb/D-Bus sessions and
fresh settings. The exact CI xfwm4 package was downloaded and unpacked into
the disposable tree, **not installed**. The host's installed xfwm4 remains
4.18.0; the affected checks below used the private 4.16.1 executable.

| Test | Result |
| --- | --- |
| Unchanged GTK runner, installed WM | 38 checks passed. |
| Unchanged GTK runner, private CI WM | 38 checks passed. |
| Updated GTK runner, private CI WM | 38 checks passed; actual active ID matched the managed visible target. |
| Updated GTK runner, CI WM deliberately delayed one second | 38 checks passed with one activation request after readiness. |
| Controlled unavailable WM, unchanged runner | Exit 1, same outer timeout signature as CI. |
| Controlled unavailable WM, updated runner | Exit 1; WM/self IDs 0, no activation sent, failure state and WM stderr preserved. |
| All seven real applications with updated helper and CI WM | 59 checks passed, zero skips and zero expected failures. Code Right=2/Left=1 passed. |
| Private Mousepad routing and GTK caret diagnostics | Both integration tests passed. |
| Focused Linux unit modules | 29 tests passed: 19 existing diagnostic tests and 10 new activation cases. |
| New activation unit module, Windows | All 10 cases passed. |

An additional attempt to run the existing diagnostic module on Windows hit
sandbox `WinError 5` errors while creating/accessing its temporary directories,
before those tests reached their checks. The complete focused pair passed on
Linux; the Windows attempt is not counted as a full-suite pass.

The unavailable-WM control proves that the old signature can result from a
missing environment prerequisite and that the correction does **not** hide
that failure. It does not prove that the original CI WM exited. The delayed
case is a controlled readiness test, not a production sleep or retry workaround.

Scoped Ruff, formatting of the new helper/tests, Python compilation, workflow
YAML parsing and whitespace checks passed. The
[numeric evidence](gtk-activation-evidence-2026-10-15.json) preserves CI facts,
native summaries, failure state and installed-Code hashes. Raw private logs
remain under `/tmp/lrd-gtk-activation-20261015-xBVJD7` on the test host.

The affected CI workflow is requested again on the updated branch; its new
result is intentionally not polled or awaited. The original CI cause remains
limited by the missing historical logs. Keep PR #92 open for review and inspect
the preserved activation evidence if CI fails again. No active desktop,
installed Code/Orca/NVDA/Remote Access, physical device settings or user documents
were changed. No merge or issue closure was performed.
