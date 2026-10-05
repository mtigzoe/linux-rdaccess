# Compatibility and correctness hardening audit — 2026-10-04

Starting local and fetched remote HEAD:
`3160f53615a89c4cad79e8c763bd8ee31ffa9217`. The working tree was clean,
the branch was `feature/nvda-orca-input-compat`, and there were no newer remote
commits to reconcile. PR #14 is to remain open and unmerged. This round makes
no new NVDA gesture mappings.

Target: Windows NVDA → NVDA Remote → Linux Orca 42.x → AT-SPI → applications
on Linux Mint 21.3 XFCE/X11. The local execution environment was verified as
Mint 21.3 with Python **3.10.12**. NVDA is the Windows controller.

Installed content changed, so versions were bumped once: controller **v31**,
local-machine **v8**. `orca_adapter.py` is unchanged; adapter status now compares
the installed file with the adapter bundled beside the running CLI.

## Confirmed findings and regressions

| Bug / root cause | Correction and regression evidence |
| --- | --- |
| Debug mode re-enabled raw legacy `_dbg` output despite the README's timing-only claim | Both generated modules return unconditionally from `_dbg`. Updated tests call it with a secret while `LINUX_RDACCESS_DEBUG=1` and verify that no debug file is created. These assertions failed before the fix. |
| Other logging paths copied private data | Legacy dynamic logger arguments, customization speech fallback, traceback printing, callback-manager tracebacks, RDP raw-byte hex dumps, unknown message dictionaries, dropped speech, AT-SPI announcements, and backend exception strings could expose text or channel metadata. They now emit fixed descriptions or counts. Generated-patch, configuration, link and bridge regressions reproduced those leaks. Dry-run output and diagnostic application labels are redacted; actual NVDA speech/braille payloads still reach their outputs. |
| Timing records used ordinary append permissions; logger failures leaked descriptors | Timing files now start at mode 0600 and existing files are tightened before writing. Timing, braille tracing and the atomic writer close descriptors if stream creation fails; tracing also closes the stream when `fchmod` fails. Regressions reproduced mode 0644 and leaked descriptors before correction. |
| Client departure could interleave reset and state invalidation/removal with a key callback | The entire departure transition now holds the existing reentrant input lock. A deterministic threaded test pauses just after reset and verifies that incoming input waits through removal. The threading evidence below establishes why this overlap is possible. |
| Repeat/release metadata could change the identity of an already injected key | `_lrd_forwarded` now supplies the original owned payload for repeats and releases. A test changes key name and scan code while preserving VK/extended identity and requires the original down/down/up payload throughout. Failed repeat/release and reset ownership protections from v30 remain covered. |
| Local result rewriting confused bare/explicit/nested returns and unverified backend flows | AST analysis proves positive backend branches and their returns. Explicit `None`, nested returns, inline conditions/comments, verified OR conditions and CRLF work. Stored results, success fallthrough, decorators, nonboolean results, unsupported control flow and unknown helpers fail instead of inventing success/failure semantics. Regressions exercise all these shapes. |
| XTest ownership became stale or was lost after partial failure | The complete `send_key` operation now keeps helper ownership transactional through the final upstream backend result. Failed initial fallback reservations are cleared; failed fallback releases retain their backend reservation; failed XTest/fallback releases retain the original held keycode for retry. A rejected repeat of an already held XTest press is consumed without crossing into fallback. Four regressions failed before these fixes, including a layout-code change during release retry. A real X-server regression verifies the key remains held after a rejected release and clears on retry. |
| GLib source-registration failures left pending speech or pass-next state and could drop typing | Scheduling returns an explicit status, handles registration exceptions and source ID zero, and rolls back the two pending flags. Tests reproduce an exception and a rejected source. Generation/session guards still expire queued work after handoff. |
| Re-executing the speech preference hook saved its previous wrapper and recursed | Closure wrappers retain the actual original function and are recognized on re-execution. Tests reproduce recursion before correction, verify stable function identity, upgrade the genuine v30 preference block, and exercise reconnect, role changes, replacement/missing transport and restored local output. |
| Configuration edits accepted an ineffective target or rejected an annotated role | Annotated top-level role assignments work. Conditional overrides, deferred/nested constructors and indirect constructor factories are rejected. The verified GUI `transport.reconnect` API remains untouched. Existing Unicode byte offsets, comments, adjacent/multiline literals, semicolons and CRLF tests remain green. Actual upstream smoke testing caught and corrected an overly broad initial reconnect check. |
| Valid-looking source fragments could be disconnected from execution while doctor reported current | Validators check unique classes/method bindings, complete helper ASTs, exact module hook tails, disabled debug entry points, actual key/braille method integration and hook placement. Tests reject renamed key handlers, early local returns, later module overrides, and direct/conditional class assignments overriding an otherwise valid helper. Current corrupt/incomplete patches are rejected without replacing their contents. |
| Installation/doctor could leave or overlook runtime skew | Installation preflights all four runtime source members before copying any. A missing adapter formerly left some installed members replaced; its regression now preserves them. Doctor reports missing/stale adapters relative to the running CLI, rather than reporting only controller/local patch status. No artificial adapter version was added. |

New failing-before-fix reproductions were run before their corresponding fixes.
Additional coverage verifies legal variants, historical upgrades and braille
type boundaries. The full suite gained **49 test methods**, from 413 to 462.
One existing bridge fixture now retains both simulated controls so Python's
reuse of an ephemeral object's identity cannot make its assertion intermittent.

## Source evidence and scope of the sixteen priority areas

The legacy [callback manager](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/callback_manager.py)
invokes callbacks synchronously. The usual key/departure sequence is therefore
serial on one receive thread. However, [transport reconnect](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/transport.py)
closes/disconnects and starts another connector without joining the old receive
connector. The queue thread joined during disconnect is the sender. Buffered
callbacks can overlap another receiver during reconnect; the additional departure
lock addresses that specific gap. This does not establish independent ownership
for multiple simultaneous controllers.

Orca 42 [customization loading](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/settings_manager.py)
loads the customization module and has a retry path, making hook re-execution a
relevant lifetime case. The preference wrapper protects its own original output
callables; it does not claim to repair arbitrary upstream monkeypatch stacking.

All main-loop callers were reviewed: speech stop, Say All, presentation and
structural-navigation toggles, bypass, Where Am I, title/status, Elements List,
braille panning/routing/home, and clipboard. Pending flags are reset on session
change and scheduling failure. Consumed F2 repeat/release ownership precedes the
bypass check. Native Orca bypass is a separate shared flag: [Orca 42 input processing](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/input_event.py)
clears it and restores grabs. This round does not blindly clear a native flag
whose origin and restoration responsibilities are unknown.

XTest preserves held keycodes across layout changes, prevents fallback-owned
repeat/release from switching to XTest, and retains v7's protection against
replay after a successful event followed by an `XFlush` exception. An initial
open failure retries after DISPLAY/XAUTHORITY change. A live display stays pinned
to its original connection. No replacement connection or production
`XCloseDisplay` path was added: [Xlib's specification](https://www.x.org/releases/X11R7.6/doc/libX11/specs/libX11/libX11.html)
treats fatal display I/O as process-ending, and closing also performs a final
synchronization. Python exception handling does not establish safe recovery
from a dead server.

Atomic private publication uses unpredictable `mkstemp` files in the destination
directory, mode 0600 from creation, and `os.replace`. Write/replace failures
remove the temporary file; stream-creation failure also closes its descriptor.
The writer replaces a destination symlink rather than writing through it.
The customization updater's existing chmod can tighten a symlink target before
replacement. New files belong to the invoking user and use private mode, rather
than retaining an arbitrary old owner/mode. `save_config` creates its parent;
legacy patching requires an existing source directory. These are atomic file
updates, not a transaction across every installed file, and no fsync durability
guarantee is made.

Python 3.10 is tested directly here and added to CI alongside 3.12. A grammar
regression covers repository CLI, runtime adapter, producer and diagnostic
sources, and generated upgrades are parsed with the 3.10 grammar. Union types,
`unlink(missing_ok=True)`, dataclasses and AST end positions are available on
the actual target interpreter. This audit does not promise Python 3.9 support.

Historical fixtures were generated with real patchers at `7fdeefd` (v29/v6)
and the starting SHA (v30/v7), not made by renaming current version comments.
Tests upgrade all four, retain their original backups, tighten broad backup
permissions, reject missing/corrupt backups, and verify current idempotence.
Malformed backup diagnostics raise a fixed `ValueError`, so the updater's repair
warning handles them without exposing Python's raw syntax-error source line.
Old upgrades restore the one-time backup; unknown manual changes to old patched
files cannot be merged automatically. Current helper tampering is rejected.

Braille boundary tests cover bool/float/huge/negative indices, empty and nested
arrays, bytes, malformed script metadata, `dots=0`, nonzero/invalid dots and
`space=2`. Ambiguous packets cannot authorize routing or persist private
metadata. Valid one-cell list/tuple routing still works. JSON peers cannot
supply Python string subclasses; no broader subclass semantics were invented.

## Validation

- Focused command: `python3 -m unittest tests.test_remote_access tests.test_orca_adapter tests.test_linux_rdaccess tests.test_compat_lifecycle tests.test_compat_xtest tests.test_configuration_updates tests.test_patch_hardening tests.test_state_hardening tests.test_genuine_upgrades tests.test_logging_privacy` — **278 passed**.
- X-server command: `xvfb-run -a python3 -m unittest -v tests.test_xtest_injection` — **5 passed**. This includes actual held/released state, keypad identity, unknown fallback, failure retry and latency.
- Full command: `xvfb-run -a python3 -m unittest discover -s tests -t . -v` — **462 passed, no skips**.
- `python3 -m compileall -q .`, `git diff --check`, and staged diff checks passed.
- The first Python 3.10 CI job passed its Linux tests but accidentally compiled the separately checked-out Windows rdAccess consumer, whose Python 3.12 syntax is not a Linux target. CI compilation now excludes that consumer checkout; semantic contract checks still run on both matrix entries.
- Temporary copies of the actual legacy customization and all four legacy modules were updated twice; compilation, controller/local current validators and idempotence passed. The real desktop installation was untouched.
- Production changes are committed at `dbb809c` and `d00f6eb6d8fba6dbb2a4226bc125fd92b2cc1a16`. The final documentation/CI commit's SHA, fetched remote equality, exact-SHA Actions result, clean tree and PR state are supplied in the completion message because a commit cannot contain its own SHA.

## Remaining risks and exact live checks

1. Multiple controllers still share input ownership. Old buffered callbacks do not
   carry a receiver-generation identity, so a late old-receiver callback is not
   universally distinguishable from current input. Test two Windows controllers,
   hold Ctrl/Alt/Shift on each, disconnect/reconnect one, and verify no unrelated
   release or lingering key. Per-origin protocol ownership is broader work.
2. Persistent backend failures cannot guarantee physical release. A fallback
   release after an XTest press and a layout change may resolve a different code;
   retry metadata alone cannot prove that an upstream backend released the
   original key. Test a held key across an XKB layout change, induce XTest refusal,
   and inspect actual key state after fallback and handoff. Lock keys need the
   same down/repeat/up test to detect duplicate toggles.
3. A dead live Xlib connection, same-credential server restart, or DISPLAY change
   with live `_dpy` has no safe in-process recovery guarantee. Test these only in
   an isolated Orca/X session and expect restart requirements; this is not a
   claimed recovery feature. The retained connection lives for the Orca process.
4. Desktop bypass behavior requires rapid F2, queued activation then handoff,
   modifier-only intervening input, CapsLock-based commands, ordinary text, two
   quick F2 gestures, and an already active native Orca bypass. Verify grabs and
   focus return correctly; local latch tests cannot prove shared native ownership.
5. Verify connected-slave mute, disconnect restoration, reconnect mute, master
   speech and role/transport replacement with real Speech Dispatcher output.
   Test each queued Orca operation while switching XFCE focus or opening a nested
   Elements List dialog. GTK application-script semantics require live evidence.
6. Test real hardware braille pan, routing and move-to-focus, malformed packets,
   typed braille and trace rotation. Inspect enabled diagnostics for synthetic
   test secrets; existing historical raw debug logs are not erased by this update.
7. Installation is not an atomic multi-file bundle transaction. A disk failure
   midway through copying or updating several files can leave skew; rerun from
   the repository and check doctor before restarting Orca. Doctor's adapter
   comparison is relative to its running CLI, not a network check for the latest
   repository. Older CLI instances cannot discover a newer repo automatically.
8. Unknown upstream layouts and corrupt current patches require repair from a
   reviewed original/backup. The validators are structural checks, not complete
   proofs of arbitrary Python behavior. Upstream/Orca/Xlib's own diagnostics and
   pre-existing logs are outside a universal process-wide privacy guarantee.
9. Leave NVDA+F5, Find/F3, table Ctrl+Alt+Arrow, review character/word/line,
   braille previous/next line, containers and F6 unchanged. Verify any proposed
   translation with Windows NVDA and Orca/XFCE/Firefox/Chromium plus primary-source
   gesture semantics before implementation. No Wayland compatibility is claimed.

PR #14 must remain **open and unmerged**.
