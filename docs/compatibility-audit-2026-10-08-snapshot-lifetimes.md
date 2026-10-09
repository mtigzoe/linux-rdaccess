# Raw braille focus and disconnect compatibility audit

Base: merged PR #36, `origin/main` at
`7cb5f19065684e179684db753dab31df89470160`.
Branch: `fix/nvda-orca-snapshot-lifetimes-20261008`.

Reviewed fixes through PRs #31–#36 and their regressions. This change preserves
the restored NVDA shortcuts, GI accessors, keyboard ownership, semantic focus
lifetimes, speech interruption, and outgoing transport ownership.

## Confirmed defects

### Queued raw braille commands survived a focus change

Raw panning and routing checked transport generation and display geometry,
but had no focus lifetime guard. A routing command received for one editor
could execute after another editor acquired focus. A queued pan also survived
a focus change away and back to the original control. PR #35 guarded semantic
actions and caret commands; it did not cover raw Orca commands.

The refresh hook now publishes a bounded, opaque focus lifetime. Raw commands
capture it at receipt and validate it against the published and live focus on
Orca's main loop. The receiver does not query AT-SPI. Refreshing the same focus
keeps queued pans valid, including successive pans that themselves refresh.

Enrollment belongs to the controller whose refresh hook published the
snapshot. Older hooks and geometry-only paths retain their existing behavior.
A refresh without accessible focus still permits raw panning; transitions
between absent and present focus create different lifetimes. The wire protocol
and native cell generation are unchanged.

Controller v103 upgrades to v104; customization braille v4 upgrades to v5.
Historical hook bodies remain recognized, private backups remain intact,
reloads retain one native refresh callable, and upgrades are idempotent.

### Controller disconnect could deadlock receiver teardown

The controller reset wrapper held its input lock while native `disconnect()`
called `transport.close()`, which acquires the connection lock. Receiver
teardown already held the connection lock while calling the controller's
disconnect callback, which acquires the input lock. Concurrent paths could
wait on each other indefinitely.

The wrapper still releases owned keys and invalidates queued work under the
input lock, then releases it before calling native disconnect. Other reset
callbacks retain their serialization. The pinned upstream implementation is
[Orca Remote's controller](https://github.com/serrebidev/orca-remote/blob/d47a085945576d8e973f9c686587bdfc90ae061c/orca-scripts/remote_controller.py).

## Regression evidence

New tests execute the production patch generators, native transport receiver
and sender, real loopback TCP framing, and explicitly drained GLib callbacks.
The disconnect regression orders native receiver teardown against controller
close. A bounded acquisition diagnoses the lock inversion and lets cleanup
finish even against the broken implementation.

The unchanged PR #36 source was extracted to a disposable directory and run
with the new regression tests: **four tests, three failures**. Raw routing,
focus-away-and-back panning, and concurrent disconnect failed. Same-focus
panning passed. Logs: `/tmp/rdaccess-snapshots-main36-before.log`.

Five new loopback tests cover these failures plus same-focus refreshes and
focus-free raw panning. The routing test also confirms that a fresh snapshot
accepts a new route. Historical hook tests include genuine v4 runtime and
on-disk upgrades, backup preservation, and rejection of modified hooks.

## Validation

| Check | Result |
| --- | --- |
| Python 3.10.12 full suite, private Xvfb | **1,232 tests passed; zero skips.** Includes native XTest, lock-state, Liblouis, GI, and 22 loopback tests. |
| Python 3.12.13 focused lifecycle, loopback, braille and speech | **103 tests passed; zero skips.** Native GI/Liblouis coverage comes from system Python 3.10, not this subset. |
| GTK/AT-SPI private gallery | **38 checks passed; 57 events.** |
| Seven-application private GUI run | **53 checks passed before a VS Code routed-caret timeout.** Settings, Thunar, Mousepad, Terminal, calendar and Firefox checks completed. |
| VS Code alone, fresh private profile | **9 checks passed; 52 events.** The six other applications were explicitly excluded from this focused retry. The caret timeout did not reproduce. |
| rdAccess main `7bfc0c86aa97044e044558d9cac24f9ba39c9d08` | **7 producer/consumer contracts passed on each Python version; 2 reverse action/heartbeat checks passed on Python 3.10.** |
| Actual main36-generated controller upgrade | v103 to v104 passed; original backup retained; second update was a no-op. |
| Ruff 0.16.10 E9/F821/F822/F823, compilation, Python 3.10 grammar, shell syntax, whitespace | Passed. |

The first full run found eight existing braille geometry regression failures
in the initial guard. Controller enrollment and absent-focus handling were
corrected, focused braille checks passed, then the full suite above passed.
No further full-suite repetition was performed. Focused totals overlap full
discovery and should not be added to it.

Final full log: `/tmp/rdaccess-snapshots-full-final.log`.
Python 3.12 log: `/tmp/rdaccess-snapshots-python312-final.log`.
GUI logs: `/tmp/rdaccess-snapshots-{gtk,real-gui,vscode-recheck}.log`.
Contract logs: `/tmp/rdaccess-snapshots-contracts-{310,312}.log`.

## Limits and later live checks

These tests use private Xvfb/D-Bus sessions, disposable application profiles,
test doubles, and loopback sockets. No active desktop, installed connector,
Orca/NVDA session, physical braille device, or real keyboard lock state was
changed. Audible NVDA output and physical routing remain untested.

Raw messages have no snapshot identifier. A command delayed on the wire until
after a newer snapshot is published cannot be associated with its original
display by this local queue guard. Focus lifetimes also do not detect every
same-focus text or viewport change. No protocol extension is proposed here.

The private XFCE clock still lacks keyboard activation and calendar selected
date semantics. The VS Code caret timeout remains recorded as an unreproduced
provider timing result. Say All and modifier paths yielded no additional
confirmed defect in this pass.

Later live checks: route and pan while rapidly switching editors; verify fresh
commands work after returning focus; disconnect during held Shift plus a letter
and during remote braille activity; confirm release cleanup and reconnect.

Changed implementation: `accessibility/orca_adapter.py` and
`connection/remote_access.py`. Regressions: `test_nvda_remote_loopback.py` and
`test_braille_hook_reload.py`.
