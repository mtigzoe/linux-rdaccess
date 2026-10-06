# Follow-up NVDA / Orca compatibility audit — October 4, 2026

Branch: `feature/nvda-orca-input-compat`; starting local and fetched remote SHA:
`7fdeefd869a89639f7ebf9839cc7983cfab5eca4`. The tree was clean before work.
Fetch and comparison found no newer commits, including a second check before
committing. No history was rewritten or installed Orca files modified during
the audit. PR #14 must remain open and unmerged.

Architecture: Windows NVDA → NVDA Remote → linux-rdaccess → Orca → AT-SPI →
Linux applications. Target: Mint 21.3 XFCE/X11, Orca 42.x. The remote patch
advances once from v29 to **v30**; the local patch once from v6 to **v7**.

## Confirmed failures, root causes and fixes

| Failure | Root cause | Exact correction and regression coverage |
| --- | --- | --- |
| Failed presses acquired releases; failed releases were forgotten; reset could send duplicate or incompatible releases | Logical physical-down state was mistaken for successfully injected state. Legacy `send_key()` returned `None` both on success and failure. Name-only keys also shared a `None` identity and could not be sorted with numeric VKs. | Record successful forwarded payloads separately; suppress unowned releases; retain failed releases for reset retry; preserve key names, scan codes and extended identity. Patch the verified backend's return paths to expose boolean results. Lifecycle tests cover failed ordinary/deferred-Caps presses, failed releases, late releases and independent named keys; XTest tests cover backend return values. |
| Handoff missed an in-flight press | The network backend could finish its press after the main thread's reset had already scanned held keys. | Serialize remote key processing, synthetic list gestures, reset and control transitions with a reentrant input lock. A two-thread regression suspends backend injection while attempting handoff, then verifies exactly one matching release. |
| Role changes and replacement transports did not expire pending commands without another key | Queue dispatch checked a stored generation without refreshing transport/control identity; the identity omitted transport role and instance. | Include both values and synchronize ownership before dispatch. Role-transition regression changes role with a title request queued and sends no further key. Existing disconnect/handoff queue tests remain green. |
| Clipboard writes survived handoff | The local GTK scheduler had no owning controller generation. | Schedule the controller's complete incoming-clipboard operation through the same guarded main loop. A clipboard/handoff regression verifies no stale write occurs. |
| Elements selection ran after handoff inside the dialog | `Gtk.Dialog.run()` processes a nested main loop after the outer queue guard has passed. | Recheck generation before selected-category delegation and chooser-unavailable fallback. A simulated nested-loop handoff produces no list action. |
| List fallback could release held keys, leave a letter held, or type without the requested modifiers | Synthetic presses/releases were untracked; cleanup covered modifiers but not a failed letter release; a backend's `False` result was ignored. Generic non-extended Shift/Alt map to the same Linux keys as their left-side VKs. | Borrow already-held left modifiers and their verified generic aliases, decline synthesis for an already-held target letter, abort on failed injection, and retry letter cleanup before releasing owned modifiers. Regressions cover all these paths. No new gesture mapping was added. |
| An adapter declining a command stopped verified fallback; absent APIs were silent | Module import was treated as success regardless of the adapter's boolean result. | Try the existing verified Orca fallback after `False` or a missing adapter method. Return failure and a fixed diagnostic if neither API is available. Do not replay input after an exception or after an invoked native handler, whose legitimate result can be `None`. Regressions cover declined and unavailable APIs. |
| Failed pass-next activation left the receive latch armed | The queued Orca call had no failure result for the latch to inspect. | Clear the latch when bypass activation returns `False`; regression verifies failed activation. Prior successful bypass/repeat/modifier tests remain green. |
| Malformed braille authorized routing or raised during classification | Falsey explicit script paths were treated as absent, metadata arrays were assumed iterable, and float legacy indexes could compare equal to integer modern cells. | Validate shapes before use, require three nonempty script-path strings, and require integer non-boolean routing values with exact agreement. Tests cover falsey paths, malformed arrays, negative dots and float/int conflicts. |
| Braille traces retained character-identifying metadata | Raw identifiers, source/model and unknown script paths were included in trace records even when the action was unknown or typed input. | Persist only canonical supported actions/script names; redact typed, invalid and unknown input. Regression uses private text in every metadata field and verifies its absence. Trace remains disabled by default. |
| Rotated traces and existing backups kept broad permissions | Rotation moved the old inode before protecting it; an upgrade retained older ordinary-write backup permissions. | Protect traces before rotation; use mode-0600 atomic writes for patched sources and backups; tighten existing backup permissions before use. Rotation and both previous-version upgrade regressions check permissions. |
| Application/input text escaped through exception tracebacks | Shim and legacy backend `log.exception()` persisted exception messages; uncaught key errors reached the upstream callback manager's traceback logger. | Retain fixed diagnostics without tracebacks, contain remote key exceptions at the callback boundary, and suppress source-bearing syntax-error chains. Queue, backend-speech and remote-key privacy regressions exercise private exception text. |
| The channel key was logged before channel join | The transport constructor separately logged `channel`, so the previous join-handler fix covered only one path. | Replace the verified constructor log with endpoint-only logging when applying connection settings; preserve a private backup and compile before publication. A constructor regression executes the patched log with a private channel and checks idempotence. |
| XTest and fallback split a repeated gesture | After a failed XTest press, a later repeat or release retried XTest instead of remaining with fallback. | Keep fallback ownership until release; a fresh gesture may retry XTest. Regression verifies one failed XTest attempt across press/repeat/release. |
| A flush exception duplicated a lock/text event through fallback | A successful fake event was already queued before `XFlush` raised, but the catch path reported failure. | Return success once the event was accepted, retaining release identity; do not replay it. Regression verifies one press and release without fallback. This does not prove delivery after a real server failure. |
| An initial display-open failure permanently disabled XTest | The failure latch never reconsidered session credentials. | Retry only when DISPLAY/XAUTHORITY change and no live display was acquired; no polling/retry loop. Regression verifies suppression in unchanged environment and one retry after a change. |
| Configuration edits changed a comment or the wrong effective assignment | Regex matched a commented role first, rewrote only the first duplicate, or changed unrelated targets in a chained assignment. Duplicate speech preferences had the same problem. | Edit actual Python value spans using AST UTF-8 offsets; require unique supported assignments and reject chained fields. Regressions cover role comments, duplicate fields/preferences and chained values. Legal Unicode, quotes, backslashes, replacement syntax, multiline values, comments and CRLF input also pass. |
| Invalid customization Python was published | The updater did not compile the complete candidate before writing. | Parse and compile before backup/publication; reject malformed source without changing it. Existing interrupted-publication/private-file tests remain green. Disable uses the same value editor and private atomic writer. |
| Local Orca stayed muted after disconnect | The old hook permanently replaced local speech functions with no-ops based on startup role. | Preserve the original functions and check connected slave state on every call. Tests verify disconnected speech/character output and idempotent upgrade of the genuine old preference block. |
| Diagnostic readiness disagreed with legal Python or ignored later assignments | Its regex could not parse comments, escaped strings or parentheses and selected the first duplicate. | Parse constant Python values without executing the file; treat invalid/ambiguous settings as unready and reduce the key to a boolean. Two diagnostic regressions cover legal commented/escaped input, duplicates and malformed Python. |
| A marker comment falsely reported a complete patch | Patcher and doctor checked only marker substrings. | Require complete generated helpers/hooks, expected key-forwarding replacement and valid Python; reject incomplete current patches. Tests exercise marker-only files and doctor's incomplete/current distinction. All prior upgrade paths remain covered. |
| Reinstalling through the installed CLI raised `SameFileError` | Source and installation directory were the same. | Skip copies whose resolved source and destination are identical. An installed-directory regression verifies the wrapper is still created. |

## Primary source verification and scope

Reviewed actual [Orca 42 default handlers](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/scripts/default.py),
[keyboard bypass](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/input_event.py),
[structural navigation](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/structural_navigation.py),
[native list GUI](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/orca_gui_navlist.py),
and web/braille code. Required `inputEvent`, owning script/navigation objects,
enabled-object list bindings and valid `None` returns remain respected.
An empty list, disabled navigation or intentional cancellation does not justify
replaying a different gesture. Originating-script/focus restoration remains a
desktop question. `orca_adapter.py` was reviewed and left unchanged.

Compared [built-in NVDA Remote serialization](https://github.com/nvaccess/nvda/blob/master/source/_remoteClient/session.py),
[NVDA commands](https://github.com/nvaccess/nvda/blob/master/source/globalCommands.py)
and the [Remote add-on serializer](https://github.com/NVDARemote/NVDARemote/blob/master/addon/globalPlugins/remoteClient/nvda_patcher.py)
against the [legacy controller](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/remote_controller.py),
[local backends/key maps](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/local_machine.py)
and [transport](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/transport.py).
No additional source-proven key-name mapping was found. The remaining Find,
refresh, table, review, braille line, container and F6 gestures stay unchanged.
No Wayland support is established by this audit.

All sixteen requested audit areas were reviewed. Further changes require desktop
evidence or broader protocol/backend ownership changes, as listed below.

## Files, regressions and validation

Production: `remote_access.py`, `linux_rdaccess.py`, `nvda_remote_check.py`.
Tests: new `tests/test_compat_lifecycle.py`, `tests/test_compat_xtest.py`,
`tests/test_configuration_updates.py`; updated `tests/test_remote_access.py`,
`tests/test_linux_rdaccess.py`, `tests/test_nvda_remote_check.py`.
Documentation: `README.md` and this report. The earlier audit remains historical.

Added **43 test methods**. Bug regressions failed before their corresponding
fixes; legal-input/idempotence/upgrade tests additionally protect the new behavior.
The upgrade test also reproduced the old backup-permissions failure before its
correction. Test fixtures now model a real transport's connected flag and use
a complete generated patch when expecting doctor to report “current.”

- Focused: **241 passed**, covering the three new modules plus remote access,
  installed CLI/doctor, Orca adapter and endpoint diagnostics.
- X-server integration: **4 passed** under a separate Xvfb server.
- Full suite: **413 passed, no skips**, under Xvfb.
- `python3 -m compileall -q .` and `git diff --check`: passed.
- Actual upstream smoke: used the starting commit's patcher to generate genuine
  v29/v6 files, then upgraded to v30/v7. Verified compilation, full validators,
  unchanged backup contents, private files/backups, idempotence and real local
  backend boolean results. Work occurred entirely in temporary directories.
- Final SHA, fetched remote equality, GitHub Actions run/result, clean tree and
  open/unmerged PR verification are supplied in the completion message; they
  cannot be embedded in the commit that determines its own SHA.

## Remaining source-level limits and live checks

1. Multiple controllers share held-key state because this integration does not
   keep per-origin input ownership. A controller departure releases shared
   state. Protocol changes are needed before claiming independent controllers.
2. A backend that continues failing cannot guarantee a physical release. Failed
   releases remain owned for retry. XTest can safely recover an initial open
   failure; a live stale Xlib connection or fatal X I/O error is different.
   A release falling back after a held-key layout change still needs desktop
   verification. No lock synchronization or generalized backend failover was added.
3. Input serialization may make a handoff wait for a slow fallback backend;
   this avoids completing handoff with an in-flight owned press. The normal
   XTest path remains fast; the integration latency check passes.
4. Existing old-patch upgrades restore the original one-time backup. Keep manual
   modifications to installed patched legacy files separately before upgrading;
   their unknown semantics cannot be safely merged by a generic patcher. A missing
   backup or incomplete current patch fails visibly rather than claiming current.
5. A complete but wrong SSH display/DBus environment and multiple XFCE sessions
   have no deterministic source-only selection rule. Session selection remains
   unchanged. The D-landmark hook's event-origin timing and modal focus/script
   selection also need real Orca events.
6. Constructor/channel-join and exception logging are fixed in the verified
   legacy files. Arbitrary customized third-party logging is outside those
   known source anchors. Avoid giving existing keys on a shell command line;
   the normal setup can generate/save them and status remains redacted.

Run the following from the target XFCE session with Windows NVDA controlling
Mint 21.3/Orca 42 and a disposable document/test channel:

1. Update the repository branch, run `python3 linux_rdaccess.py install`, then
   `linux-rdaccess connect` and `linux-rdaccess doctor`. Confirm controller v30
   and local v7 are current. Verify local speech resumes when the relay disconnects.
2. Repeat ordinary text and arrow/keypad navigation with Insert and CapsLock
   as NVDA modifiers. Test standalone CapsLock, repeats, CapsLock+Shift,
   CapsLock+Insert, translated and unhandled chords, and both release orders.
   Hold Ctrl/Shift/Alt/Win/Insert while disconnecting or handing control over;
   reconnect and verify no stuck key, duplicate release or unexpected lock toggle.
3. Press NVDA+F2 followed rapidly by an ordinary key and by NVDA+Space; repeat
   with CapsLock and F2 repeat/release. Verify one bypassed command, then normal
   translation. Queue title, Say All, Where Am I and clipboard operations while
   Orca is busy; hand off and verify old-session actions do not execute.
4. Open NVDA+F7, select each available category, cancel with Escape, and test
   empty/disabled navigation. Handoff while the chooser is open, then select a
   category: no old-session list should open. Verify native result activation
   and focus restoration in Firefox and Mousepad/Xed. Test fallback with held
   modifiers and ensure normal typing afterward.
5. Pan, route first/last visible cells and move braille to focus in browse and
   editable content. Test legacy/modern single-cell gestures and contracted
   braille alignment. Formatting, multi-cell and typed-braille gestures must
   not route. If enabling trace on disposable input, inspect both log files:
   permissions 0600 and canonical commands/redaction only.
6. Compare endpoint layouts and Num Lock on/off; hold keypad and dedicated
   navigation keys together and release independently. Exercise display/session
   changes and X server restart separately, without assuming fatal Xlib failure
   is recoverable inside the current process.
7. Compare native Ctrl+F/F3/Shift+F3 with NVDA Find gestures, F6/Shift+F6 in
   Firefox and VS Code, Ctrl+Alt+Arrow in tables/editable grids, and review,
   braille-line and container commands. NVDA+F5 must not be assumed to mean
   browser reload. These are evidence-gathering checks, not new mappings.
8. Test SSH launches against each graphical session, including stale processes
   and plausible but wrong inherited DISPLAY/DBus values. Record selected
   session, focus, speech and braille behavior before proposing selection changes.
