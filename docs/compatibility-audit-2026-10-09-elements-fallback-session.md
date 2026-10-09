# Elements List fallback session audit — 2026-10-09

## Confirmed defect

The Elements List category opener captures its controller generation before
asking the adapter for Orca's native list API. Native list callbacks receive a
lifetime predicate. When that API is unavailable, the keyboard fallback did not
check the predicate again: it sent Alt+Shift+letter even if control had changed
during lookup or while it waited for the input lock.

The shortcut's key ownership was already serialized. The missing check was
between the earlier session validation and the later locked injection. Merely
checking before acquiring the lock would leave the waiting-for-lock case open.

Before the fix, six unit assertions failed across control handoff, last-master
departure, disconnect, role change and two deterministic threaded interleavings.
A separate private Xvfb regression observed these actual XTest transitions after
handoff: Shift down, Alt down, M down, M up, Alt up, Shift up. An old request could
therefore deliver a complete shortcut to Linux after losing its session.

## Fix

Acquire the existing input lock, refresh/check the captured generation, and
inject the fallback only while it is still current. The check and injection
share the lock used by remote input and lifecycle resets. The native API and
its GUI stay outside this added critical section so control handoff remains
available while native lookup or a list dialog is active.

The generated controller advances from v108 to v109. Existing v108 installs
upgrade using their original upstream backup. No protocol changes are needed.

## Focused validation

| Coverage | Result |
| --- | --- |
| Keyboard/browse contract runner, including 10 structural-list ownership tests | 47 tests passed |
| Elements focus, native list lifetime, direct commands, input ownership and controller upgrades | 67 tests passed |
| NVDA Remote TCP loopback, including master departure during list lookup | 26 tests passed |
| Real XTest injection and display safety on disposable private Xvfb | 11 tests passed |
| Installed CLI checks in private temporary homes | 4 tests passed |
| Selected legacy Elements List tests | 5 tests passed |

These are 160 distinct focused tests with no outstanding failures or skips.
The new unit tests also verify that unrelated input in the current session
keeps the fallback working and that a handoff completes while native lookup
is paused. Initial post-fix assertions assumed an empty ownership dictionary
already existed; they were corrected to accept an absent dictionary when no
key was ever injected. The final Xvfb rerun passed after one automatic approval
timeout was retried.

A disposable upgrade check generated genuine v108 output using the pre-change
module from commit `10caf1c`, then upgraded it with the new module. The current
patch validator, original backup contents, mode 0600, idempotence, generated
and changed Python compilation, Python 3.10 grammar and whitespace checks
passed.

## Limits

Full repository discovery, live Windows NVDA, audible speech, physical braille
and Linux application acceptance were not run. Xvfb validates key injection
and held-key behavior without touching the user's desktop; it does not establish
that a real application's Elements List opens or receives focus correctly.
Loopback uses real transport framing with a simulated Orca runtime.

The guard covers controller/transport generations at fallback injection. It
does not recall X events already injected while their session was current.
Existing installations need the normal connect/update flow and an Orca restart
to load the new controller. No real user configuration was modified. GitHub
Actions were not monitored or awaited, and the PR was not merged.
