# Receive-side shortcut capture compatibility audit — 2026-10-09

Status: **Automated-tested**. Python 3.10.12, installed Orca 42.0
(`42.0-1ubuntu2`). This audit does not establish live Windows NVDA, audible
speech, native GUI interaction, or physical braille acceptance.

## Confirmed defects

1. While Orca's shortcut editor sets `orca_state.capturingKeys`, receive-side
   translation consumes NVDA commands before their physical keys reach Orca.
   For example, Insert+T and CapsLock+T produce no injected chord. The queued
   command guard suppresses title presentation, but the shortcut editor still
   receives nothing. The same loss affects input help, pass-next, Elements List,
   other direct commands, and unsupported NVDA+Q.
2. NVDA+1 uses a separate queued input-help callback without a capture guard.
   If shortcut capture starts after receipt and before callback dispatch, the
   callback still invokes `toggleInputHelp` inside capture.

Ten new regression methods fail against the genuine controller from `main`
commit `b418179` (v116): 55 assertion failures, zero errors and zero skips.
They pass with the fix. Failure totals include parameterized subtests, rather
than representing 55 separate defects.

## Native behavior and provenance

Inspected installed `/usr/lib/python3/dist-packages/orca/input_event.py` and
`orca_gui_prefs.py`, and compared relevant method ASTs with pinned upstream:

- [Orca ORCA_42_3 keyboard event processing](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/input_event.py)
- [Orca ORCA_42_3 preferences and shortcut capture](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/orca_gui_prefs.py)

Installed and pinned methods match for `KeyboardEvent.shouldConsume`,
`KeyboardEvent._process`, and `OrcaSetupGUI._processKeyCaptured`, `editingKey`,
`editedKey`, and `editingCanceledKey`. Native dispatch yields keys to capture
before binding lookup. The preferences editor records a configured Orca
modifier followed by the captured key; its editing callbacks enter and leave
capture explicitly.

The regression executes the installed `_processKeyCaptured` method against
the bridge's recorded physical presses and checks the resulting modifier/key
binding. Its GTK/GDK dependencies and injected key delivery are fixtures.
No upstream source is copied into the repository by this change.

## Fix and ownership

The receiver forwards physical capture input before command translation,
flushing deferred NVDA modifiers for a new non-modifier key. This also handles
a modifier still held after an earlier translated command. Previously consumed
commands retain their own repeats and releases. Captured presses retain raw
repeat/release ownership after capture ends, including a rejected release,
until successful release or session reset. A rejected deferred Insert cannot
deliver an unmodified command. Handoff and disconnect reset capture ownership.

NVDA+1 checks capture again at main-loop dispatch. A command received before
capture is suppressed rather than retroactively injecting a physical chord.
Existing pass-next ownership and speech cancellation remain in their established
order. The controller marker advances to v117 and recognizes v116 for upgrade.

Two existing native-dispatch fixtures now model their intended transitions:
receipt of a queued browse claim precedes capture entry, and a captured key is
released before a fresh post-capture command starts.

## Validation

All four existing GitHub Actions compatibility inventories ran locally:

| Group | Tests | Result |
| --- | ---: | --- |
| Keyboard and browse | 87 | PASS |
| Braille | 112 | PASS |
| Speech and focus | 10 | PASS |
| Remote protocol, including two new TCP regressions | 43 | PASS |
| Modifier deferral, validation, direct commands, layouts, trace, patch integrity, historical upgrades, installed runtime | 128 | PASS |
| Focused legacy patch/install checks | 44 | PASS |

Total: **424 distinct tests**, zero failures, errors, or skips. New unit tests
cover direct commands in desktop/laptop layouts with Insert/CapsLock, native
capture interpretation, capture entry/exit, held keys, backend rejection and
exceptions, failed release retry, queued input-help, handoff and disconnect.
TCP tests exercise actual relay decoding and deferred main-loop callbacks
using disposable loopback connections and fixture key injection.

A private install generated genuine v116 output using the previous patcher,
then upgraded it to v117 with the current installer. Original controller,
local-machine and configuration backups survive; files retain mode `0600`;
copied adapter/model modules match the checkout; repeated updates are
idempotent; generated files compile with Python 3.10 grammar. Executing that
installed controller confirms capture delivery, held-key release and a fresh
title command after capture ends. All 12 tracked root Python wrappers remain
byte-for-byte identical to `b418179`.

## Remaining acceptance

No graphical display is available (`DISPLAY` and `WAYLAND_DISPLAY` unset).
Windows NVDA/Remote, the actual Orca preferences dialog, audible speech,
physical braille, and live Linux application acceptance remain untested.
After updating the generated controller, restart Orca to load v117. Manually
check assigning shortcuts with Insert/CapsLock and Shift/Ctrl in the native
preferences dialog, held keys when editing ends, input-help transitions, and
disconnect/reconnection. GitHub Actions were not monitored and the PR must
remain unmerged.
