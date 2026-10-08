# Pre-live NVDA/Orca audit, October 8, 2026

Reviewed latest `origin/main` at `981ea76`, after a clean fast-forward pull.
Fixes are on `fix/prelive-nvda-review-20261008`; this branch is not merged.
The automated pre-live checks pass. Windows NVDA end-to-end behavior still
requires the live checks below. The installed Mint integration was left intact.

The recommended architecture remains Windows NVDA Remote Access -> Orca Remote
relay transport -> Orca 42 speech/braille and native application scripts.
The generated controller owns input and queues Orca operations on its main loop;
the adapter uses Orca's browser-mode gates and native navigation APIs. Optional
semantic braille support must preserve raw-cell fallback. The retained experimental
xrdp path uses separate speech, braille and A11Y DVC links, AT-SPI snapshots, and
focus resynchronization. The Windows SSH controller invokes an allowlisted
installed Linux command; desktop discovery supplies the graphical environment.
These boundaries were reviewed without changing command mappings or protocols.

| Reproduced problem | Correction | Regression evidence |
| --- | --- | --- |
| A missing or failing optional native-braille capability offer suppressed raw display cells. | Isolate negotiation failure and continue raw-cell forwarding. Recognize and upgrade the existing v2 customization hook to v3. | Three new negotiation/upgrade tests, plus the pre-existing real-Liblouis alignment test that failed on starting main. |
| After a deferred Insert press failed, another key pressed while Insert remained held reached Linux as plain input. | Retain the unsuccessful pending Insert until retry, physical release, or control handoff. Suppress unsuccessful chord keys. | Four controller regressions and a real XTest test verifying Insert precedes the recovered key and both release cleanly. |
| An obsolete socket-creation attempt could connect after close, overwrite a replacement, or run stale callbacks/cleanup during a handoff. | Track connection ownership and serialize socket publication, connected callbacks, sender creation, failed-attempt cleanup, and final teardown with close. Reject obsolete native connector retries. | Eight transport regressions use the complete pinned upstream source, native worker threads, and synchronization barriers. Upgrade/idempotency and tampering checks also pass. |
| SSH launch could combine a selected desktop with inherited SSH DISPLAY/XAUTHORITY or stale session variables. The remote helper discarded a final environment entry without its NUL terminator. | Replace the graphical environment as a unit, reject a selected session without a display, and retain the final entry. | Two CLI environment tests and three launcher regression methods, including missing-display and final-entry cases. |
| Integer zero slider/progress values disappeared from semantic snapshots. | Preserve zero while keeping None as an empty value. | A real numeric-value regression in `test_prelive_ssh_focus.py`. |
| Failed AT-SPI child/state queries were treated as a completed search with no focus, clearing reconnect focus. | Mark provider failures as incomplete and retain cached focus. | Four query-failure/resync regressions. |
| XFWM's focused top-level window, or a toolkit's focused ancestor, won over the actual keyboard control. A cached top-level focus bypassed a fresh search. | Prefer focused descendants across active windows; keep a top-level fallback ahead of inactive windows. Re-search cached window/frame/dialog focus. | Four additional focus tests and an actual GTK/AT-SPI check that resolves the checkbox instead of XFWM's window. |
| The GTK gallery declared `entry` and `tree table` for controls exposing `text` and `table`. | Correct the fixture metadata. | The reusable GTK smoke compares all 14 declared roles with actual AT-SPI roles. |

Thirty new unittest methods cover the runtime changes and preservation cases.
The GTK runner is `tools/gtk_atspi_smoke.py`; it creates its own Xvfb display,
D-Bus session and temporary settings, and checks the display is Xvfb before
injecting keys. No application-specific production workaround was added.

The starting-main baseline ran 1,096 tests on both Mint and WSL and reproduced
one error: raw braille output disappeared without the optional capability method.
An initial Windows-sandbox attempt had temporary-file permission errors. The
first Linux source export also converted shell files to CRLF; rebuilding the
archive with `git -c core.autocrlf=false archive` restored the original LF blobs.
Neither environmental issue required changing tests or source line endings.

| Final check | Result |
| --- | --- |
| Mint 21.3, XFCE 4.18.1, Orca 42.0; Python 3.10.12 full suite under Xvfb | 1,126 passed, zero skips; 43.439 s |
| Mint, isolated Python 3.12.15 full suite under Xvfb | 1,108 run: 1,096 passed, 12 dependency skips; 41.683 s |
| Independent Ubuntu 22.04 WSL/Python 3.10 full suite under Xvfb | 1,126 passed, zero skips |
| Expanded X11/XTest/lock-state/latency suite, Python 3.10 and 3.12 | 43 passed on each interpreter; includes Insert recovery and the existing <5 ms injection assertion |
| Actual Mint GTK/AT-SPI smoke | 32 checks passed: 14 roles, keyboard Tab/focus events, checkbox state, text/caret, semantic focus lookup/snapshots, modal entry and Escape focus restoration |
| Installed Orca 42 keybinding diagnostic | Seven key cases passed: remote D/Shift+D and releases, focus-mode/local D, Ctrl+D; event metadata restored and modifier bindings checked |
| Linux fixtures -> latest rdAccess `main` (`7bfc0c86aa97044e044558d9cac24f9ba39c9d08`) | Seven semantic contracts passed on Python 3.10 and 3.12; reverse action and heartbeat contracts passed |
| Windows SSH controller, native Windows Python 3.14 | Six unit tests passed; actual SSH `status` action found the installed Linux CLI and returned redacted status |
| Private temporary copies of installed controller/local machine/transport/customizations | Upgrade, idempotency, original-backup preservation and 0600 permissions passed; installed originals unchanged |
| Python static checks | Compileall passed on 3.10/3.12; all 105 Python files parse with the 3.10 grammar; Ruff 0.16.10 E9/F821/F822/F823 passed (extracted partial-source fixtures excluded from name analysis) |
| Shell/PowerShell/static diff checks | All shell scripts pass `bash -n`; three PowerShell scripts parse; `git diff --check` passes |

The Python 3.12 skips are two module-level GI dependency records and ten native
Liblouis tests. The GI records replace twenty underlying bridge tests, so the
test totals differ. System Python 3.10 executes all of these cases. No assertion
was weakened to hide a dependency. The focused suite counts overlap the full
suite. Portal/PipeWire/deprecation notices in the disposable GUI session did
not affect its checks.

Reproduce the principal Linux checks from this branch:

```sh
xvfb-run -a python3 -m unittest discover -s tests -t . -v
xvfb-run -a python3 -m unittest -v tests.test_xtest_injection tests.test_live_x11 tests.test_lock_toggle_integration tests.test_compat_xtest tests.test_xkb_lock_state
python3 tools/gtk_atspi_smoke.py
python3 -m compileall -q .
bash -n run_braille_bridge.sh
bash -n start-orca-session.sh
bash -n start-orca-remote.sh
```

GTK smoke additionally needs GTK3/AT-SPI, xfwm4 and xdotool.
The existing workflow contains the fixture/action/heartbeat contract commands;
`tools/orca42_d_landmark_check.py` documents its real-Orca requirements.
Detailed Mint logs and synthetic artifacts remain under
`/tmp/linux-rdaccess-prelive-20261008-ZxxUI3`; WSL uses temporary POSIX source
copies. Private installed-source copies were deleted after validation.

Automated checks establish Orca 42 API/keybinding compatibility, native
Liblouis cell behavior, X11 injection, GTK focus semantics, and protocol
contracts. They do not establish audible output or a live Windows peer session.
Before live acceptance, apply this branch's installation/configuration updates
on Linux, then use the existing live acceptance checklist to verify:

- Windows Remote Access connection/control toggling, rapid input, disconnect
  and reconnect with speech and held keys in flight.
- Audible speech, Ctrl interruption during Say All, pacing and duplicate output.
- Physical 40/80-cell braille negotiation, panning, routing at first/middle/last
  cells, display replacement, and focus/caret tracking.
- Real desktop/laptop keyboard layouts, Caps/Insert, keypad identity, pass-next,
  modifier releases, and local/remote lock-state changes.
- Firefox browse/focus transitions, browser chrome, editable/ARIA controls,
  table spans and XFCE shortcut grabs; Thunar, panels, dialogs, editors, terminals
  and VS Code behavior in the user's desktop.

Braille keyboard typing and unsupported NVDA navigator/review commands retain
their documented limitations. X11 remains the supported injection backend;
Wayland is not verified. A canceled DNS/TLS call is invalidated safely but can
still finish on upstream/OS timeout; this change does not forcibly interrupt it.
No additional reproducible automated product failure remains at this checkpoint.
