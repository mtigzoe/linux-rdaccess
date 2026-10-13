# Ordinary typing with an empty Orca navigation model — 2026-10-13

Related: keyboard issue #57, speech issue #58, application acceptance #60,
and the Mousepad preparation for routing PR #81. Base: `main` **7c21b45**.

## Report and confirmed defect

The user reported that `a`, `m`, `n`, `i` and other keys did not work while
controlling Linux Mint, specifically being unable to type `m` in
`mousepad --disable-server`. Asked about speech, the user said NVDA did not
announce the keys. Missing text and missing key echo are distinct observations;
the exact live delivery of `i` has not been established.

Read-only inspection identified installed Orca **42.0-1ubuntu2**. Its base
`Script.getEnabledStructuralNavigationTypes()` returns an empty list, while
`getStructuralNavigation()` initializes the model from the global
`structuralNavigationEnabled` preference (default True). The base
`useStructuralNavigationModel()` returns only that enabled flag. The installed
terminal script inherits `default.Script` and supplies no structural-navigation
override. A non-navigation script can therefore have an enabled flag with an
empty `enabledObjects` dictionary.

The bridge treated that flag as proof of browse navigation and consumed remote
`a/f/m/n/o/w/7/8/9` presses as unsupported NVDA browse commands. There need not be
any structural handler for the application. The installed controller is **v119**
and contains this gate. The installed checkout is clean `main` **ac1dbdb**; its
core source exactly matches the pre-fix `7c21b45` file, SHA-256
`1c04bb0751c6d07fcd01036c6380d6e2bc2a3419da00a329d4dd518d016df06d`.
Installed Orca `script.py` SHA-256:
`798d9ca2e87a943882047cac268c1be144eeb862cd4601cdf34ebeb01ec08689`.

The fix requires an actual nonempty structural-object dictionary as well as
Orca's mode gate before consuming these browse letters. Remote provenance is
still claimed/expired before refusal, so a later local key cannot inherit it.
Input help stays ahead of this typing check; valid browser navigation, focus
mode, shortcut capture and held/released-key ownership retain their existing
paths. Advance the generated controller to **v120**, recognize v119 for upgrade,
and preserve the original upstream backup.

## Regression and validation

Three new methods cover ordinary typing in an empty navigation model, expiry
of the refused remote claim, and the actual installed Orca base gate. Typed
keys include plain/Shift presses, repeat and release, plus `i/p/s` as controls.

- Corrected Windows baseline: **19 expected failing checks** in two methods
  (nine guarded keys in plain/Shift forms plus claim expiry). `i/p/s` controls
  passed even before the correction. An initial harness assertion mistakenly
  treated Orca's `(False, reason)` tuple as a boolean; that was corrected before
  counting these baseline failures.
- Linux baseline using the unmodified pre-fix core and the installed Orca
  method: **three failing checks**, for `a`, `m` and `n`.
- Fixed Linux Mint/Python 3.10.12: **129 related tests passed**, covering browser
  command contexts, trace behavior and upgrades, including the installed-source
  gate check. A further **46 pass-next, structural-list ownership and remote-key
  validation tests passed**.
- Windows Python 3.10: browser context module **67 passed, 3 installed-Linux
  tests skipped**. The wider 129-test Windows run was not a PASS: it reported
  17 failures, 29 errors and 3 skips while exercising Linux trace/permission
  behavior on Windows. Those checks all passed on Linux; the production trace
  implementation was not changed to accommodate Windows.
- A genuine v119 controller generated before editing upgraded to v120 with
  the guard present, recognized-current status, unchanged backup hash and no
  change on the second patch run. The existing marker-upgrade tests also cover
  v119 migration. This upgrade probe used a disposable fixture, not the user's
  active controller.
- Scoped Ruff 0.16.4 critical checks, Python compilation and
  `git diff --check` passed. Existing source formatting was preserved.

Before deployment approval, no Desktop Commander, desktop input, user settings
changes, running-controller installation or Orca/NVDA restart was performed.
Linux tests and source reads ran over SSH in an isolated temporary checkout.

## Approved Linux installation and restart

The user explicitly approved applying the fix and restarting Orca. The agent
verified the clean Linux checkout, fetched the fix branch and required the
exact tested commit **dbc5fb740c3dc98b5ee3e6886098dd6efc784fbb** before selecting
`fix/non-web-letter-input`. The former `main` checkout at `ac1dbdb` is retained
as a branch, and the installed runtime's core matches the tested source.

The active controller upgraded from v119 to **v120** and passed the
recognized-current check. A separate private pre-update controller copy was
saved for rollback; the original upstream backup and its hash were preserved.
Saved customization and autostart hashes were unchanged across installation.
The actual saved connection file (`remote.json`) and customization hashes were
also unchanged across restart; the saved configuration remains ready.

The approved `orca --replace` ran on the existing display `:0`. A subsequent
process check found one live new Orca process, with the previous process gone
and an established socket to the configured relay port. The immediate launcher
check had briefly seen old and new processes together; only the later stable
check is evidence of replacement. A relay TCP socket is not proof of
authenticated Windows Remote Access or active keyboard control.

No Desktop Commander, agent desktop input, Windows NVDA restart or
relay-credential change was used.

## Limited human typing confirmation after restart

The user confirmed fresh five-minute authorization and reported being able
to enter `mousepad --disable-server`, the command whose `m` had previously
blocked preparation. This is a limited human-reported improvement in real
terminal typing on v120, including the formerly blocked `m`. It is not a
captured single-key delivery trace or confirmation of speech/key echo.

The authenticated readiness check reported active authorization, connected
transport, an attached bridge and negotiated semantic braille. At the time
of the Windows reply it reported local control, while the read-only Linux
AT-SPI snapshot still showed a focused terminal. Control at the exact typing
time and a numeric caret change were not captured. After the user was asked
to return to Linux control and press Enter once on that known command, a
subsequent read-only snapshot showed application `mousepad`, role `text`,
and editable/focused states. This verifies that Mousepad is now open and
its editor focused, without proving the input origin or Windows speech.
The user was then asked to prepare `alpha bravo charlie` in a new unsaved
document and leave the caret at the end before any routing gesture.

## Remaining live work

The fix is **automated-tested and installed with user approval**, with a
limited human confirmation that the previously blocked terminal command can
now be entered. Instrumented text insertion and speech acceptance still
require verification in the restarted session. The original controller
backup is present and saved connection settings were preserved.

Test a single known-text typing gesture in the
terminal or an unsaved editor with active remote control, fresh five-minute
consent for the authenticated status check, and separate user speech/braille
confirmation. Verify `m/a/n` text insertion, then use `i` as a control rather
than claiming it is fixed by this path. Recheck ordinary typing and browser
navigation separately. Continue Mousepad routing acceptance only after the
fixture can be prepared.

Saved Orca general alphabetic/numeric/punctuation echo and key echo are enabled;
the saved default profile enables character/word echo. Active runtime settings
and the exact source of absent speech were not captured. No echo setting was
changed, and issue #58 remains open. Keep #57 and #60 open for the remainder of
their live acceptance criteria. New CI is not polled or awaited; no merge or
issue closure is performed by the agent.
