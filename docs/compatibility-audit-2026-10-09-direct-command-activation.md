# Queued direct keyboard activation audit — 2026-10-09

Status: **Automated-tested**. Installed Orca 42.0 (`42.0-1ubuntu2`), Python
3.10.12; focused command tests also run on Python 3.12.13. No live Windows
NVDA, audible speech, native GUI interaction, or physical braille acceptance
is claimed.

## Confirmed defect

Direct NVDA keyboard commands capture their active script for input-help
descriptions, but ordinary execution resolves the active script again when
the main-loop callback runs. Window activation is unchecked. If activation
changes between receipt and dispatch, an old gesture can start Say All in
another script or announce the title of a replacement window. The existing
Say All lifetime guard starts when speech begins, so it cannot reject a
keyboard request already retargeted before speech starts.

NVDA+1 has a separate queued callback which also lacks this activation check.
Input-help descriptions can survive a window change when the script instance
is unchanged. These are manifestations of the same missing receipt lifetime.

Nine new defect regression methods fail against genuine `main` controller
`9bb7e8c` (v117), with 50 assertion failures, zero errors and zero skips.
The failure count includes parameterized subtests. Two additional positive
control methods preserve valid same-activation behavior.

## Native source comparison

Inspected installed Orca source and compared relevant ASTs with pinned upstream:

- [Keyboard event dispatch, ORCA_42_3](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/input_event.py)
- [Default script commands, ORCA_42_3](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py)

Installed and pinned methods match for `KeyboardEvent.__init__` and `_consume`,
and `Script.sayAll`, `presentTitle`, `presentStatusBar`, and `whereAmIBasic`.
Native keyboard events capture their script, window and focused object on
receipt; `_consume` invokes the captured script. The bridge's direct adapter
dispatch instead reads the current active script. This fix applies the
repository's asynchronous activation-lifetime contract to direct commands.
No upstream source is copied into the repository.

## Fix

Snapshot script and window references at command receipt. At main-loop dispatch,
reject a different script instance or an unequal window, and reject unreadable
state or failed window comparisons. State access at receipt does not query
AT-SPI providers. Comparison happens during dispatch. The existing generation
guard continues to handle handoff, disconnect and reconnection.

Equivalent window proxies remain valid. Focus movement within the same script
and window remains valid. Expired translated presses still own their repeats
and releases, while fresh presses in the current activation execute normally.
Input-help description and shortcut-capture behavior retain their existing
guards. Route NVDA+1 through the same command helper, with an explicit toggle
path so exiting help remains possible. Normal pass-next retains its existing
receive-side ownership and separate lifecycle checks.

Advance the generated controller to v118 and recognize v117 for upgrade.
Correct the existing laptop focus-accelerator fixture to include Shift in its
NVDA+Ctrl+Shift+Period chord; the new positive control verifies that this case
actually invokes its command.

## Validation

All existing compatibility matrix inventories pass locally:

| Group | Tests | Result |
| --- | ---: | --- |
| Keyboard and browse | 96 | PASS |
| Braille | 112 | PASS |
| Speech and focus | 10 | PASS |
| Remote protocol | 45 | PASS |
| Focused input, patch integrity, historical upgrades and installed runtime | 128 | PASS |
| Focused legacy patch/install checks | 44 | PASS |

Total: **435 distinct tests** on Python 3.10.12, zero failures, errors or skips.
The direct-command class also passes all **28 tests on Python 3.12.13**.
Regression coverage includes script/window transitions, help entry/exit,
localized descriptions, equal script instances, equivalent window proxies,
same-window focus movement, held Insert/CapsLock, failed reads/comparisons,
snake-case state APIs and fresh commands after expiry. Existing matrix tests
cover handoff, reconnection, input help and shortcut capture.

Two new TCP regressions use actual relay decoding, the command adapter and
the bridge's speech-forwarding hook with fixture native script handlers. Old
commands must emit no speech packet after activation changes; fresh commands
emit the current document/window's speech. This is protocol verification,
not audible output on an installed Windows NVDA client.

A private upgrade uses the genuine v117 patcher before applying v118. Original
controller, local-machine and customization backups survive with mode `0600`;
copied adapter/model files match the checkout; repeated updates are idempotent;
generated files compile with Python 3.10 grammar. Execution of the installed
controller rejects stale script/window commands and allows fresh title and
input-help toggles. All 12 tracked root Python wrappers are unchanged from
`9bb7e8c`.

## Remaining acceptance

The full repository suite was not rerun; validation is focused on the affected
contracts and installation paths. `DISPLAY` and `WAYLAND_DISPLAY` are unset.
Live NVDA/Remote speech and braille, physical devices and native Linux
application interaction remain untested. Restart Orca after installing v118.
Manually check Say All, title/status/current-line reporting and NVDA+1 while
switching applications/windows and reconnecting. GitHub Actions were not
monitored; leave the PR unmerged.
