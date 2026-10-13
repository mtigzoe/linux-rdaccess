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

No Desktop Commander, desktop input, user settings changes, running-controller
installation or Orca/NVDA restart was performed. Linux tests and source reads
ran over SSH in an isolated temporary checkout.

## Remaining live work

The fix is **automated-tested**, not yet installed in the user's running Orca.
Applying it requires updating the Linux checkout/controller and restarting
Orca, which temporarily interrupts the remote session and requires the user's
approval under the original live-test instructions. The controller's original
backup is present. No relay credentials or saved settings need changing.

After approved installation, test a single known-text typing gesture in the
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
