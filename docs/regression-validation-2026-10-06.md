# Regression validation, October 6, 2026

Branch: `fix/defer-insert-nvda-modifier`.
Fetched base: `e2f0b40cffe8d4b8b4898769a67edb6c0e1de6b4`, identical to origin,
with a clean working tree before changes. PR #15 was not merged and this
repository was never switched to `main`. Existing compatibility work and
installed Orca files were preserved.

## Confirmed regressions fixed

1. Laptop NVDA layout forwarded seven plain Shift+numpad gestures even though
   NVDA 2026.2 declares them globally: Numpad1/2/3/7/9 and Divide/Multiply.
   They now retain the existing ownership behavior in both layouts. No new
   NVDA-to-Orca command mapping was added. Dedicated navigation keys and
   payloads without physical-keypad evidence retain their previous behavior.
   Controller v89 recognizes and upgrades v88; original backups and idempotence
   are tested. Twelve laptop subcases failed before the fix.
2. Braille polling continued through a received batch after a handshake or
   attribute-reply write dropped the channel. Subsequent frames could write
   through `None` and raise `AttributeError`. Polling now stops immediately.
   Both new tests reproduce the original errors and cover retry/reconnect.
3. An A11Y action callback could drop its channel while sending focus, followed
   by a pending XON handshake on `None`. Polling now stops before that handshake
   or later callbacks. The new test reproduces the original error and verifies
   retry, a replacement handshake, and cached-focus replay.

No stale assertion was weakened to obtain a pass. Input tests were expanded
for both layouts, repeat/release ownership after Shift release, reset and late
releases, dedicated-key boundaries, and v88 upgrade behavior. The input review
found no additional demonstrated defect in deferred Insert/Caps, F2 pass-next,
Num/Scroll repeats, selection reporting, malformed-frame cleanup, failed
synthetic injections, transport disconnect/reconnect, or controller reset.

The layout correction is supported by [NVDA 2026.2 global commands](https://raw.githubusercontent.com/nvaccess/nvda/release-2026.2/source/globalCommands.py)
and [Orca 42 mouse bindings](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_0/src/orca/desktop_keyboardmap.py).
The detailed input record below identifies the exact source lines.

## Final results

| Suite | Python 3.10.12 | Python 3.12.13 |
| --- | --- | --- |
| Full suite under isolated Xvfb | 849 run, 849 passed, no skips | 831 run, 829 passed, 2 module skips |
| CI X11 injection and live diagnostics | 18 passed, no skips | 18 passed, no skips |
| Expanded X11 lock/ownership/fallback tests | 37 passed, no skips | 37 passed, no skips |
| Focused input/adapter/braille/transport tests | 542 passed, no skips | 532 passed, no skips; GI bridge module excluded |
| Available DVC modules | 92 passed including GI bridge tests | 72 passed without GI bridge modules |
| Semantic consumer contract | 7 passed; action and heartbeat assertions passed | 7 passed; action and heartbeat assertions passed |
| Compile checks | Passed | Passed |

All final automated suites passed. The two Python 3.12 discovery skips are
`tests.test_braille_bridge` and `tests.test_bridge`: the temporary interpreter
lacks the system GI/AT-SPI bindings. These are module skips, replacing twenty
tests which execute successfully on system Python 3.10. No test was altered
to hide this dependency limitation.

The existing real-Orca42 script also passed seven asserted event cases with
hardware-code restoration and the expected Orca modifier matches. The XTest
latency test passed its existing threshold of less than 5 ms per complete
keystroke on both versions. No measured latency value is printed by that test.

Files changed: `remote_access.py`, `a11y_link.py`, `braille_link.py`,
`tests/test_remote_access.py`, `tests/test_a11y_link.py`,
`tests/test_braille_link.py`, `README.md`, and this report.

## Environment and root command record

Logs, temporary Python, and consumer checkout are under
`/tmp/linux-rdaccess-validation`. They are local artifacts, not committed.
CI was read from `.github/workflows/remote-a11y-tests.yml`.
Consumer revision: `e672c1db5164ea7ff47832db9509cb10777a1508`.

The first sandboxed fetch could not write `.git/FETCH_HEAD`; the authorized
retry succeeded with Git metadata writes enabled. Sync commands were:

```sh
git fetch origin
git switch fix/defer-insert-nvda-modifier
git pull --ff-only origin fix/defer-insert-nvda-modifier
git status
git rev-parse --short HEAD
git rev-parse HEAD origin/fix/defer-insert-nvda-modifier
```

The installed Python 3.12 link was dangling. Temporary setup used:

```sh
/home/miriam/.local/bin/uv --cache-dir /tmp/linux-rdaccess-validation/uv-cache python list --only-installed
/home/miriam/.local/bin/uv --cache-dir /tmp/linux-rdaccess-validation/uv-cache python install 3.12 --install-dir /tmp/linux-rdaccess-validation/python --no-bin --no-registry
git clone --depth 1 --branch main https://github.com/mtigzoe/rdAccess.git /tmp/linux-rdaccess-validation/rdAccess
```

The consumer clone reproduces CI's separate Windows-repository checkout; the
Linux repository remained on the requested branch.

In the following reproducible commands, `P` is `/usr/bin/python3.10` or
`/tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12`.
The initial system runs used the equivalent `python3` executable.

```sh
env -u DISPLAY "$P" -m unittest -v tests.test_a11y_link tests.test_a11y_model tests.test_nvda_remote_check tests.test_remote_access tests.test_linux_rdaccess
env -u DISPLAY "$P" -m unittest discover -s tests -v
"$P" -m py_compile nvda_remote_check.py remote_access.py linux_rdaccess.py tests/test_nvda_remote_check.py tests/test_remote_access.py tests/test_linux_rdaccess.py
"$P" -m compileall .
"$P" -m compileall -q -x '(^|/)rdAccess/' .
git diff --check
```

Initial CI unit runs: 375 passed on each version. Initial requested full
discovery: 844 run, 12 X-server skips; the sandboxed attempt also had one
local-socket `PermissionError` in the speech probe. The same full command
with local socket access enabled passed with the same 12 expected skips.
The Xvfb runs below execute those twelve tests. Final exact-commit unit,
discovery, and compile output is saved as `*-commit-py310.log` and
`*-commit-py312.log`, with the commit recorded in `tested-commit.txt`.

Focused root command, run initially and after fixes on Python 3.10:

```sh
env -u DISPLAY python3 -m unittest -v tests.test_remote_access tests.test_insert_modifier_deferral tests.test_input_trace tests.test_orca_adapter tests.test_layout_keypad_gestures tests.test_nvda_direct_commands tests.test_pass_next tests.test_braille_link tests.test_braille_bridge tests.test_transport_cleanup tests.test_customization_reconnect tests.test_receiver tests.test_dvc_channel tests.test_compat_lifecycle tests.test_state_hardening tests.test_compat_xtest
```

Results: initially 538 passed; finally 542 passed. The same direct command
under Python 3.12 stopped during module loading with `SkipTest` for unavailable
GI. Repeating it without `tests.test_braille_bridge` passed all 532 portable
tests. Full discovery records the module skip normally. Logs:
`focused-py310.log`, `focused-final-py310.log`, `focused-final-py312.log`,
`focused-final-py312-portable.log`.

The contract runner below is an exact transcription of the workflow's fixture,
action and heartbeat steps, with outputs placed under `/tmp`. It ran on each
version before and after the DVC fixes:

```sh
bash /tmp/linux-rdaccess-validation/run-ci-contract.sh /usr/bin/python3.10 /tmp/linux-rdaccess-validation/contract-py310
bash /tmp/linux-rdaccess-validation/run-ci-contract.sh /tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 /tmp/linux-rdaccess-validation/contract-py312
```

## Remaining live-test risks

Automated success does not establish full accessibility compatibility. Live
Windows NVDA Remote plus Orca testing is still required before PR #15 can be
considered ready to merge. The outstanding checks include actual Windows
Insert/Caps configurations and NumLock/scan payloads, selection semantics in
real applications, speech and braille hardware, network reconnect timing with
held modifiers, window-manager key grabs, and simultaneous local/remote keys.

Xvfb verifies real key state, Caps/Num indicators, Scroll Lock press/release,
keypad/arrow separation, failed release retry, and production XTest latency.
Existing tests do not assert every disconnect/reset path against physical X11
state, a real desktop Scroll Lock toggle/indicator layout, or actual xdotool
fallback execution. Fallback ownership and dispatch are tested with mocks.
The real Orca script uses synthetic events and isolated Xvfb/D-Bus, with no
Windows controller or application desktop. No installed runtime was updated.

## Complete delegated command records

The following records include every focused and X-server test invocation,
negative controls, initial environment failures, repeats, counts, and skips.

### Input compatibility

```text
Input compatibility audit
Original commit: e2f0b40 (root owns fetch/sync/full commit identification)
Files changed by this agent: remote_access.py, tests/test_remote_access.py, README.md
Commits created by this agent: none

Test commands and outcomes
1. python3 -m unittest -v tests.test_remote_access tests.test_insert_modifier_deferral tests.test_input_trace tests.test_compat_lifecycle > /tmp/linux-rdaccess-validation/input-audit.log 2>&1
   Original controller v88: 363 tests, 0 failures/errors/skips, 14.091s, exit 0.
2. python3 -m unittest -v tests.test_remote_access.LegacyConfigTests.test_shift_numpad_review_commands_are_consumed_in_both_layouts tests.test_remote_access.LegacyConfigTests.test_shift_numpad_mouse_lock_commands_do_not_click_in_both_layouts tests.test_remote_access.LegacyConfigTests.test_shift_numpad_ownership_is_cleared_on_reset_in_both_layouts tests.test_remote_access.LegacyConfigTests.test_shift_navigation_without_matching_numpad_scan_stays_native > /tmp/linux-rdaccess-validation/shift-numpad-before.log 2>&1
   Added/expanded regressions before fix: 4 tests, 12 failing laptop subcases, 0 errors/skips, 0.900s, exit 1.
   Five review/focus keys leak, four mouse-key scan variants leak, three ownership/reset cases fail acquisition.
   Dedicated/ambiguous navigation exclusions pass before and after fix.
3. python3 -m unittest -v tests.test_remote_access.LegacyConfigTests.test_shift_numpad_review_commands_are_consumed_in_both_layouts tests.test_remote_access.LegacyConfigTests.test_shift_numpad_mouse_lock_commands_do_not_click_in_both_layouts tests.test_remote_access.LegacyConfigTests.test_shift_numpad_ownership_is_cleared_on_reset_in_both_layouts tests.test_remote_access.LegacyConfigTests.test_shift_navigation_without_matching_numpad_scan_stays_native tests.test_remote_access.LegacyConfigTests.test_v88_controller_patch_upgrades_shift_numpad_ownership > /tmp/linux-rdaccess-validation/shift-numpad-after.log 2>&1
   Controller v89 after fix: 5 tests, 0 failures/errors/skips, 1.527s, exit 0.
4. python3 -m unittest -v tests.test_remote_access tests.test_insert_modifier_deferral tests.test_input_trace tests.test_compat_lifecycle > /tmp/linux-rdaccess-validation/input-audit-fixed.log 2>&1
   Controller v89 after fix: 365 tests, 0 failures/errors/skips, 14.585s, exit 0.

Concrete original regression
LINUX_RDACCESS_NVDA_LAYOUT=laptop disabled the existing plain Shift+numpad ownership block,
even though these exact seven existing bindings are global in NVDA 2026.2.
Using the existing LegacyConfigTests controller fixture, Shift+Divide/Multiply forwarded
key-down, repeated key-down, key-up in laptop; desktop forwarded only Shift down/up.
Scan-proven Shift+Numpad1/2/3/7/9 also leaked into ordinary application navigation.
This is an incorrect layout restriction, not a stale expectation or a new Orca mapping.

Minimal fix
Removed only the desktop-layout condition from the existing ownership block. Kept its
same seven gesture identities and modifier/scan guards. Controller marker bumped v88 to
v89 with v88 migration recognition so installed v88 patches can update safely.
Updated current README version and described both-layout scope. Historical docs untouched.

Regression coverage
- Both desktop/laptop layouts for all seven owned gestures.
- Matching scan codes for five review/focus keys; both absent and matching scan for unambiguous Divide/Multiply.
- Auto-repeat and release stay consumed after Shift is released first.
- Empty _lrd_swapped, _lrd_down, _lrd_forwarded after completed gestures.
- Reset clears owned keys; late releases cause no duplicate injection; later unshifted input remains native.
- Dedicated extended Home/End/Down/Page keys, absent scans and mismatched scans remain native.
- v88 upgrade, marker validation, idempotence and existing original backup preservation.

Primary evidence (checked via browser)
NVDA release-2026.2:
https://raw.githubusercontent.com/nvaccess/nvda/release-2026.2/source/globalCommands.py
Line 298: kb:shift+numpadDivide (toggleLeftMouseButton)
Line 309: kb:shift+numpadMultiply (toggleRightMouseButton)
Line 2058: kb:shift+numpad1 (review_startOfLine)
Line 2899: kb:shift+numpad2 (reportFocusObjectAccelerator)
Line 2201: kb:shift+numpad3 (review_endOfLine)
Line 1750: kb:shift+numpad7 (review_top)
Line 1939: kb:shift+numpad9 (review_bottom)
These use plain kb:; layout-specific alternatives use kb(laptop): in the same source.
The new fix does not invoke those actions; it safely owns the documented unsupported gestures.

Orca ORCA_42_0:
https://raw.githubusercontent.com/GNOME/orca/ORCA_42_0/src/orca/desktop_keyboardmap.py
Lines 45-46: KP_Divide, ORCA_MODIFIER_MASK, NO_MODIFIER_MASK, leftClickReviewItemHandler.
Lines 48-49: KP_Multiply, ORCA_MODIFIER_MASK, NO_MODIFIER_MASK, rightClickReviewItemHandler.
The comment at lines 40-43 explains that Shift is intentionally ignored so modified clicks work.
Verified matching bindings in installed Orca42 source at
/usr/lib/python3/dist-packages/orca/desktop_keyboardmap.py lines 45-53.
A Windows laptop NVDA layout can control Linux with Orca desktop layout; the client layout
is not an Orca mouse-binding safeguard.

Other read-only audit results
Focused existing tests passed for consumed Insert/Caps deferral, F2 pass-next, Num/Scroll repeat,
current selection in both layouts, physical keypad identities, dedicated-key boundaries,
failed presses/releases, synthetic fallback cleanup, controller reset/handoff/reconnect,
marker cleanup and privacy. No other demonstrated input regression found by this agent.

Remaining live-only risk
Unit tests use original payload fixtures and fake backend ownership, not real Windows scanner
identity or an end-to-end NVDA Remote+Orca session. NumLock/Windows keypad payloads, actual
Orca mouse behavior, accessibility selection semantics, speech/braille and reconnect timing
still require live testing. Root/X-server agent owns Xvfb and Python-version results.
```

### Transport and DVC

```text
Transport, lifecycle, braille and DVC regression validation
Repository: /home/miriam/linux-rdaccess
Starting commit: e2f0b40cffe8d4b8b4898769a67edb6c0e1de6b4
Branch maintained by parent: fix/defer-insert-nvda-modifier
No Git mutations, commits, branch changes or PR actions by this agent.

Inspection
Reviewed remote_access.py generated controller ownership/reset hooks, deferred
Insert/Caps replay, forwarded payload ownership, swapped ownership, bypass
ownership and synthetic braille/structural-list cleanup; legacy TCP transport
malformed-frame/select/socket failure cleanup, send-failure shutdown and native
reconnector startup; DVC Receiver, speech, braille and A11Y poll/drop/handshake.
No additional demonstrated keyboard ownership/state regression found in these
reviewed paths. Existing tests retain release ownership after failed releases,
do not acquire release ownership after rejected/raised presses, drop stale
queued generations on handoff, and clear deferred/swapped state on reset.

Confirmed fixes
1. braille_link.NvdaBrailleLink.poll processed drained messages after failed
   handshake or reply write dropped _channel. A coalesced protocol frame then
   attempted send_json(None), raising AttributeError and risking removal of
   the recurring GLib polling callback. Four guard lines stop the batch after
   channel loss. Two tests validate handshake-drop and reply-drop boundaries,
   no stale cell updates, retry deadline and successful replacement handshake.
2. a11y_link.NvdaA11yLink.poll processed a coalesced XON and action before its
   handshake; an action callback's failed send_focus dropped _channel, then
   the pending handshake tried send_json(None). Two guard lines stop the batch
   after an action drops the channel. One test validates no further callbacks,
   no None-channel handshake, retry deadline, successful replacement XON and
   replay of the cached current focus.
Speech DVC has no equivalent confirmed flaw: it drains metadata without
callbacks or writes before handshaking, and handshake failure returns.

Changed files (uncommitted for parent review)
braille_link.py: 4 guard lines
tests/test_braille_link.py: 2 regressions, 54 lines
a11y_link.py: 2 guard lines
tests/test_a11y_link.py: 1 regression, 44 lines
git diff --check: passed after both fixes.
No mappings, existing assertions, compatibility markers, or patch work changed.

Run 1: initial focused transport/lifecycle command, Python 3.10.12
python3 -m unittest -v tests.test_transport_cleanup tests.test_customization_reconnect tests.test_compat_lifecycle tests.test_state_hardening tests.test_braille_link tests.test_braille_bridge tests.test_receiver tests.test_dvc_channel tests.test_patch_hardening
Result: 113 tests, 0 failures/errors/skips, 2.925 s, OK.
Log: transport-audit.log

Run 2: braille affected command after first fix, Python 3.10.12
python3 -m unittest -v tests.test_braille_link tests.test_braille_bridge tests.test_receiver tests.test_dvc_channel
Result: 34 tests, 0 failures/errors/skips, 0.032 s, OK.
Log: braille-disconnect-regressions.log

Negative control 1
Executed HEAD:braille_link.py in a separate namespace, temporarily patched the
test module's NvdaBrailleLink reference, and ran only the 2 new regressions.
Result: 2 tests, 2 AttributeError errors as expected; proves both tests detect
the original flaw. No working file was reverted or modified for this check.
Log: braille-disconnect-before-fix.log

Run 3: expanded focused command after braille fix, Python 3.10.12
python3 -m unittest -v tests.test_transport_cleanup tests.test_customization_reconnect tests.test_compat_lifecycle tests.test_state_hardening tests.test_braille_link tests.test_braille_bridge tests.test_receiver tests.test_dvc_channel tests.test_patch_hardening tests.test_speech_link tests.test_a11y_link
Result: 162 tests, 0 failures/errors/skips, 2.626 s, OK.
Log: transport-audit-after-fix.log

Run 4: affected DVC/bridge command after both fixes, Python 3.10.12
python3 -m unittest -v tests.test_braille_link tests.test_braille_bridge tests.test_a11y_link tests.test_bridge tests.test_speech_link tests.test_receiver tests.test_dvc_channel
Result: 92 tests, 0 failures/errors/skips, 0.303 s, OK.
Log: dvc-disconnect-regressions.log

Negative control 2
Executed HEAD:a11y_link.py in a separate namespace, temporarily patched the
test module's NvdaA11yLink reference, and ran its new regression.
Result: 1 test, 1 AttributeError error as expected; proves regression catches
the original flaw. No working file was reverted or modified for this check.
Log: a11y-disconnect-before-fix.log

Run 5: attempted same affected DVC/bridge command, Python 3.12.13
/tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m unittest -v tests.test_braille_link tests.test_braille_bridge tests.test_a11y_link tests.test_bridge tests.test_speech_link tests.test_receiver tests.test_dvc_channel
Result: explicit unittest module loading stopped with module-level SkipTest:
Atspi or liblouis not available: No module named 'gi'. No test count generated.
Environment limitation; standalone Python 3.12 lacks distro GI/liblouis.
Log: dvc-disconnect-regressions-py312.log

Run 6: available DVC modules, Python 3.12.13
/tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m unittest -v tests.test_braille_link tests.test_a11y_link tests.test_speech_link tests.test_receiver tests.test_dvc_channel
Result: 72 tests, 0 failures/errors/skips, 0.027 s, OK.
Log: dvc-disconnect-regressions-py312-compatible.log

Run 7: bridge discovery records expected environment skips, Python 3.12.13
/tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m unittest discover -s tests -t . -p 'test_*bridge.py' -v
Result: 2 discovered module skip placeholders, 0 failures/errors, 2 skips,
0.000 s. test_braille_bridge and test_bridge both require unavailable GI.
Log: dvc-bridges-py312.log

Runs 8 and 9: CI semantic fixtures/contracts after both fixes
bash /tmp/linux-rdaccess-validation/run-ci-contract.sh /usr/bin/python3 /tmp/linux-rdaccess-validation/transport-contract-py310
bash /tmp/linux-rdaccess-validation/run-ci-contract.sh /tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 /tmp/linux-rdaccess-validation/transport-contract-py312
Both scripts reproduce six fixture generators from remote-a11y-tests.yml,
rdAccess/tests/remote_a11y_contract.py, action request encoding/decoding and
heartbeat contract assertions using parent's consumer checkout.
Both versions: 7 semantic contract tests, 0 failures/errors/skips, 0.005 s,
plus action round-trip and heartbeat assertions passed. Exit status 0.
Logs: transport-contract-py310.log; transport-contract-py312.log

Run 10: final expanded transport/lifecycle command, Python 3.10.12
python3 -m unittest -v tests.test_transport_cleanup tests.test_customization_reconnect tests.test_compat_lifecycle tests.test_state_hardening tests.test_braille_link tests.test_braille_bridge tests.test_receiver tests.test_dvc_channel tests.test_patch_hardening tests.test_speech_link tests.test_a11y_link
Result: 163 tests, 0 failures/errors/skips, 3.015 s, OK.
Log: transport-audit-final.log

Remaining live risks
Faults are exercised through existing fake-channel/controller fixtures. These
checks do not prove live rdAccess DVC/reconnect, Windows NVDA Remote, Orca42
speech/braille or desktop compatibility. Parent handles Xvfb and full suites.
```

### X-server validation

```text
X-server validation command record
Repository: /home/miriam/linux-rdaccess
Initial tested commit: e2f0b40cffe8d4b8b4898769a67edb6c0e1de6b4
No branch switches, fetches, merges, commits, or code edits by X-server test agent.
No host :0 input was used. Every integration run used xvfb-run -a.

Environment
python3: /usr/bin/python3, Python 3.10.12
python3.12: /tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12, Python 3.12.13
libX11: libX11.so.6; Debian package 2:1.7.5-1ubuntu0.3
libXtst: libXtst.so.6; Debian package 2:1.2.3-1build4
Xvfb: /usr/bin/Xvfb; Debian package 2:21.1.4-2ubuntu1.7~22.04.16
xauth: 1:1.1-1build2
xdotool: 1:3.20160805.1-4
Orca: 42.0-1ubuntu2
python3-gi: 3.42.1-0ubuntu1
gir1.2-atspi-2.0 / at-spi2-core: 2.44.0-3
python3-pyatspi: 2.38.2-1
No packages installed by this agent. Python 3.12 provisioned separately by parent.

Run 1: initial sandboxed CI X-server suite
Command:
mkdir -p /tmp/linux-rdaccess-validation && xvfb-run -a python3 -m unittest -v tests.test_xtest_injection tests.test_live_x11 > /tmp/linux-rdaccess-validation/xserver-ci-python310.log 2>&1
Outcome: 18 tests in 0.015s; 2 failures, 1 error, 5 skips; exit 1.
Reason: sandbox blocked XOpenDisplay/socket access. Real XTest cases skipped, live diagnostic failures all reported unavailable display/injection.
Confirmed environment-only by passing same command outside sandbox in Run 2.

Run 2: CI X-server suite, Python 3.10, require_escalated
Command:
xvfb-run -a python3 -m unittest -v tests.test_xtest_injection tests.test_live_x11 > /tmp/linux-rdaccess-validation/xserver-ci-python310-unsandboxed.log 2>&1
Outcome: 18 tests in 0.404s, OK; 0 failures/errors/skips; exit 0.

Run 3: expanded X-server suite, Python 3.10, require_escalated
Command:
xvfb-run -a python3 -m unittest -v tests.test_xtest_injection tests.test_live_x11 tests.test_lock_toggle_integration tests.test_compat_xtest tests.test_xkb_lock_state > /tmp/linux-rdaccess-validation/xserver-expanded-python310.log 2>&1
Outcome: 37 tests in 0.561s, OK; 0 failures/errors/skips; exit 0.

Run 4: initial full suite under Xvfb, Python 3.10, require_escalated
Command:
xvfb-run -a python3 -m unittest discover -s tests -t . -v > /tmp/linux-rdaccess-validation/xserver-full-python310.log 2>&1
Outcome: 844 tests in 22.971s, OK; 0 failures/errors/skips; exit 0.

Run 5: CI X-server suite, Python 3.12, require_escalated
Command:
xvfb-run -a /tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m unittest -v tests.test_xtest_injection tests.test_live_x11 > /tmp/linux-rdaccess-validation/xserver-ci-python312.log 2>&1
Outcome: 18 tests in 0.403s, OK; 0 failures/errors/skips; exit 0.

Run 6: expanded X-server suite, Python 3.12, require_escalated
Command:
xvfb-run -a /tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m unittest -v tests.test_xtest_injection tests.test_live_x11 tests.test_lock_toggle_integration tests.test_compat_xtest tests.test_xkb_lock_state > /tmp/linux-rdaccess-validation/xserver-expanded-python312.log 2>&1
Outcome: 37 tests in 0.576s, OK; 0 failures/errors/skips; exit 0.

Run 7: existing real-Orca42 landmark diagnostic, initial upstream path, require_escalated
Command:
xvfb-run -a env UPSTREAM_REMOTE_CONTROLLER=/home/miriam/.local/share/orca/orca-scripts/remote_controller.py dbus-run-session -- sh -c '/usr/libexec/at-spi-bus-launcher --launch-immediately & sleep 2; python3 tools/orca42_d_landmark_check.py' > /tmp/linux-rdaccess-validation/xserver-orca42-landmark-python310.log 2>&1
Outcome: exit 1 before running checks. The script copies a controller then patches it; installed controller already contains an older patch and temporary copy lacks its required upstream backup. Installed controller was untouched.
Correction: pass preserved unpatched upstream backup to existing script (Run 8).

Run 8: existing real-Orca42 landmark diagnostic, unpatched upstream backup, require_escalated
Command:
xvfb-run -a env UPSTREAM_REMOTE_CONTROLLER=/home/miriam/.local/share/orca/orca-scripts/remote_controller.py.linux-rdaccess-backup dbus-run-session -- sh -c '/usr/libexec/at-spi-bus-launcher --launch-immediately & sleep 2; python3 tools/orca42_d_landmark_check.py' > /tmp/linux-rdaccess-validation/xserver-orca42-landmark-upstream-python310.log 2>&1
Outcome: exit 0; all seven asserted event cases passed: remote D and Shift+D press/release -> next/previous landmark, focus-mode/local D -> live-region, Ctrl+D unconsumed. Hardware codes restored for all cases; no pending landmark claims. Printed three Orca+Z/Orca+Shift+Z/Orca+BackSpace keybinding checks matched expected behavior.
Uses real Orca 42 keybindings and KeyboardEvent matching, synthetic events, separate Xvfb and D-Bus/AT-SPI session. Does not launch a user desktop or speak through Windows NVDA Remote.

Coverage and limits
Real X-server integration modules discovered: tests.test_xtest_injection (5), tests.test_live_x11 (3 real XKB plus 10 diagnostic unit tests), tests.test_lock_toggle_integration (4). Expanded suite adds 11 mocked production ownership/fallback tests and 4 lock-state decode tests.
Latency test injects 200 complete Down keystrokes and asserts < 5.0 ms per keystroke; passes on both versions. Existing test does not print measured per-keystroke timing.
Real XTest tests verify Down, KP_Add, KP_Enter, KP_Up, Insert, Scroll_Lock press/release state, arrow/keypad independent releases, unknown-keysym fallback, retained failed release ownership/retry, held Shift refusal, Caps/Num real XKB indicators and release timing, repeat consumption, completed-gesture snapshot announcements, and Caps-as-NVDA command preserving real lock state.
Unit tests in full suite cover disconnect/reset/reconnect, deferred NVDA modifiers, failed synthetic modifiers, duplicate releases, malformed frames, scan-code identity and shortcut ownership. The real X-server modules do not themselves exercise every controller disconnect/reset path against physical server state.
Scroll_Lock real press/release is verified. Default Xvfb Scroll Lock toggle/indicator behavior and live desktop layout differences are not asserted by repository integration tests.
Xvfb has no real application desktop or Windows controller. Automated success does not establish end-to-end NVDA Remote/Orca speech, selection, braille, mouse behavior, or complete accessibility compatibility.
Real Orca42 script run uses Python 3.10; standalone Python 3.12 lacks the distro GI/Orca stack and Orca 42 imports removed imp, so not retried under 3.12.

Run 9: final full suite after v89/input, A11Y and braille fixes, Python 3.10, require_escalated
Command:
xvfb-run -a python3 -m unittest discover -s tests -t . -v > /tmp/linux-rdaccess-validation/xserver-final-full-python310.log 2>&1
Outcome: 849 tests in 27.669s, OK; 0 failures/errors/skips; exit 0.
Tested e2f0b40 plus final working-tree fixes in README.md, a11y_link.py, braille_link.py, remote_access.py, tests/test_a11y_link.py, tests/test_braille_link.py, tests/test_remote_access.py. Parent handles final commit identity.

Run 10: final full suite after v89/input, A11Y and braille fixes, Python 3.12, require_escalated
Command:
xvfb-run -a /tmp/linux-rdaccess-validation/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 -m unittest discover -s tests -t . -v > /tmp/linux-rdaccess-validation/xserver-final-full-python312.log 2>&1
Outcome: 831 tests in 27.622s, OK (skipped=2); 0 failures/errors; exit 0.
Expected skips: tests.test_braille_bridge (Atspi or liblouis not available: No module named 'gi'); tests.test_bridge (Atspi not available: No module named 'gi'). Module skips replace 20 underlying GI-dependent tests with 2 module-level skip records. The system Python 3.10 final run exercised those 20 tests.
Same final working-tree fixes as Run 9.

Run 11: final existing real-Orca42 landmark diagnostic after v89, Python 3.10, require_escalated
Command:
xvfb-run -a env UPSTREAM_REMOTE_CONTROLLER=/home/miriam/.local/share/orca/orca-scripts/remote_controller.py.linux-rdaccess-backup dbus-run-session -- sh -c '/usr/libexec/at-spi-bus-launcher --launch-immediately & sleep 2; python3 tools/orca42_d_landmark_check.py' > /tmp/linux-rdaccess-validation/xserver-final-orca42-landmark-python310.log 2>&1
Outcome: exit 0; all seven asserted event cases, hardware-code restoration and pending-claim cleanup passed. Three printed modifier keybinding checks matched expected behavior.

Additional precision: real-X tests ensure unknown keysyms request upstream fallback rather than injecting invalid keycodes; the real fallback stub deliberately raises AssertionError. Real xdotool fallback execution is not tested; fallback press/repeat/release ownership and error recovery are tested with mocked injection backends.
```

### CI contract runner

```sh
#!/usr/bin/env bash
set -euo pipefail
lrd_python="$1"
lrd_artifacts="$2"
lrd_consumer=/tmp/linux-rdaccess-validation/rdAccess
mkdir -p "$lrd_artifacts"
"$lrd_python" tools/generate_remote_a11y_fixture.py > "$lrd_artifacts/linux-a11y-fixture.json"
"$lrd_python" tools/generate_remote_a11y_role_matrix.py > "$lrd_artifacts/linux-a11y-role-matrix.json"
"$lrd_python" tools/generate_remote_a11y_state_matrix.py > "$lrd_artifacts/linux-a11y-state-matrix.json"
"$lrd_python" tools/generate_remote_a11y_navigation_fixture.py > "$lrd_artifacts/linux-a11y-navigation.json"
"$lrd_python" tools/generate_remote_a11y_action_fixture.py > "$lrd_artifacts/linux-a11y-action.json"
"$lrd_python" tools/generate_remote_a11y_text_fixture.py > "$lrd_artifacts/linux-a11y-text.json"
"$lrd_python" "$lrd_consumer/tests/remote_a11y_contract.py" "$lrd_artifacts/linux-a11y-fixture.json" "$lrd_artifacts/linux-a11y-role-matrix.json" "$lrd_artifacts/linux-a11y-state-matrix.json" "$lrd_artifacts/linux-a11y-navigation.json" "$lrd_artifacts/linux-a11y-action.json" "$lrd_artifacts/linux-a11y-text.json"
PYTHONPATH="$lrd_consumer/addon" "$lrd_python" - <<'PY' > "$lrd_artifacts/rdaccess-action.json"
from lib.a11y import encodeActionRequest
import sys
sys.stdout.buffer.write(encodeActionRequest("remote-button", 1))
PY
"$lrd_python" tools/decode_remote_a11y_action.py < "$lrd_artifacts/rdaccess-action.json" > "$lrd_artifacts/decoded-action.json"
"$lrd_python" - "$lrd_artifacts/decoded-action.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    decoded = json.load(f)
assert decoded == {"object_id": "remote-button", "action_index": 1}
print("rdAccess action request accepted by Linux")
PY
PYTHONPATH="$lrd_consumer/addon" "$lrd_python" - <<'PY' > "$lrd_artifacts/rdaccess-pong.json"
from lib.a11y import decodeMessage, encodePong, PingMessage
import sys
msg = decodeMessage({"type": "a11y_ping", "nonce": 23})
assert isinstance(msg, PingMessage)
sys.stdout.buffer.write(encodePong(msg.nonce))
PY
"$lrd_python" - "$lrd_artifacts/rdaccess-pong.json" <<'PY'
import json, sys
from a11y_link import decode_pong
with open(sys.argv[1], encoding="utf-8") as f:
    message = json.load(f)
assert decode_pong(message) == 23
print("A11Y heartbeat contract accepted")
PY
```
