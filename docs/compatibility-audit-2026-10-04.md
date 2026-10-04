# NVDA / Orca compatibility audit — October 4, 2026

Branch: `feature/nvda-orca-input-compat`. Starting SHA:
`96396439fbfcdfcb8bea918bf7987aa623c8ddcf`, verified after fetch and fast-forward
pull with a clean working tree. PR #14 remains open; no merge or replacement PR.

The architecture remains Windows NVDA → NVDA Remote → linux-rdaccess → Orca →
AT-SPI → Linux applications. The input compatibility patch advances once from
v28 to **v29**, and the local-machine patch once from v5 to **v6**.

## Confirmed bugs and corrections

| Bug | Root cause | Correction |
| --- | --- | --- |
| Adapter-free commands silently failed on Orca 42 | Say All, title, status and presentation-mode handlers require `inputEvent`; the fallback passed no argument. Existing fakes incorrectly made it optional. | Supply `None`, matching the adapter, and use required arguments in the shared Orca fakes. |
| Pass-next-command lost to translated gestures | Direct calls bypass Orca's keyboard bypass flag; network input can also precede the queued F2 callback. | Arm a receive-side latch, honor Orca's flag, and keep repeats/releases of consumed F2 owned by the shim. |
| Other braille cell commands performed routing | An unknown explicit script path fell back to routing merely because position data existed. | Infer routing only when script metadata is absent. Formatting, selection and custom commands are left unsupported. |
| Conflicting or multi-cell messages performed single-cell routing | A legacy `routingIndex` overrode modern `cellIndexes` without validation. | Require exactly one valid modern cell and agreement with any non-null legacy index. |
| Controller departure left Linux keys held | The relay can remain connected after a Windows controller leaves; transport-disconnect hooks never run. | Release forwarded keys when a known master leaves, using its cached role before upstream removes it. Other peers' departures preserve held keys. |
| Old queued commands ran after handoff | GLib callbacks outlived held-key reset and could act on new focus or cancel new speech. | Give queued work a session generation; reset expires it and rearms speech cancellation. Braille and keyboard input share initialization. |
| Keypad navigation collided with dedicated navigation | Legacy `_resolve_key` ignored `extended=False` for shared navigation VKs. | Resolve explicit non-extended forms to keypad names before choosing the injection backend; preserve explicit key names and missing-flag behavior. |
| Channel joins logged the connection key | Upstream's ordinary info log printed the channel, which is the NVDA Remote key. | Replace the known log statement with a fixed message. |
| Braille keyboard script metadata exposed characters | A `kb:<gesture>` script name can contain characters without dot/space fields. | Redact keyboard-emulation and braille-dot scripts before recording metadata or dispatching routing. |
| Secret files were briefly readable by other users | Files and backups were written with default permissions, then chmodded. | Write through mode-0600 temporary files and atomically publish; remove temporary files on failure. |
| Backslashes changed connection keys | `re.sub` interpreted JSON-escaped replacement text again. | Use a callable replacement, preserving the literal configured key. |

## Source verification

Actual [Orca 42 default script](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/scripts/default.py),
[web script](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/scripts/web/script.py),
[structural navigation](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/structural_navigation.py),
[braille routing](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/braille.py)
and [keyboard events](https://github.com/GNOME/orca/blob/ORCA_42_0/src/orca/input_event.py)
were inspected. AST inspection confirmed argument signatures and owning objects:

- Script handlers: `sayAll`, `togglePresentationMode`, `bypassNextCommand`,
  `whereAmIBasic`, `presentTitle`, `presentStatusBar`, `panBrailleLeft`,
  `panBrailleRight`, `processRoutingKey`, and `goBrailleHome`.
- Navigation manager: `toggleStructuralNavigation(script, inputEvent)`.
- Enabled navigation object: `showList(script, inputEvent)`.
- Routing uses the zero-based BrlAPI argument plus Orca's viewport offset.
  `goBrailleHome` exits flat review when needed.

Current [built-in NVDA Remote serialization](https://github.com/nvaccess/nvda/blob/master/source/_remoteClient/session.py),
[NVDA braille commands](https://github.com/nvaccess/nvda/blob/master/source/globalCommands.py),
the [NVDA Remote add-on serializer](https://github.com/NVDARemote/NVDARemote/blob/master/addon/globalPlugins/remoteClient/nvda_patcher.py),
and actual legacy [controller](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/remote_controller.py)
and [local-machine](https://github.com/serrebidev/orca-remote/blob/master/orca-scripts/local_machine.py)
source were also inspected. Modern single-cell gestures can contain both position
fields; multi-cell presses have no safe legacy single-index equivalent. Explicit
formatting/selection scripts must retain their meaning. The keypad distinction
matches [Microsoft's extended-key contract](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input).

## Files and validation

Changed: `remote_access.py`, `tests/test_remote_access.py`,
`tests/test_xtest_injection.py`, `README.md`, and this report.
`orca_adapter.py` was audited without changes.

Added 19 test methods: required Orca signatures, receive-side and external bypass,
controller/other-peer departure, stale and initial-session callbacks, explicit
braille script semantics, conflicting routing data, keyboard metadata redaction,
keypad resolution, independent X-server releases, private writes, failed publication,
literal key escapes, channel-log privacy, and v28/v5 upgrade regressions.
Bug regressions were run against the unfixed code and failed before correction.
The initial-session callback test additionally protects the new generation logic.

- Baseline: **351 tests passed**, three X-server tests skipped.
- Final focused suite: **173 passed** (`tests.test_remote_access`, `tests.test_orca_adapter`).
- X-server integration: **4 passed** under Xvfb.
- Final full suite: **370 passed, no skips**, under Xvfb.
- `python3 -m compileall -q .` and `git diff --check`: passed.
- Smoke checks on actual upstream files: generated genuine v28/v5 patches with
  the starting commit's patcher, upgraded to v29/v6, compiled, verified backup
  preservation and idempotence, and executed controller-departure and keypad
  resolution checks. No installed Orca files were modified.
- GitHub Actions passed on the starting SHA. The final-head CI result and exact
  final SHA are reported in the completion message.

## Remaining risks and exact live checks

Use Windows NVDA controlling Mint 21.3 XFCE/X11 with Orca 42. Reapply the repository's
connection setup to install v29/v6, then use `linux-rdaccess doctor` to verify them.
Use disposable documents and a test channel. Leave gesture/debug tracing disabled
while entering real secrets. Xvfb verifies injection, not human speech/braille usability.

1. With Insert, then CapsLock as NVDA modifier, test NVDA+Space in Firefox document
   text, a text field, contenteditable, and browser chrome; test NVDA+Shift+Space
   and D/Shift+D. Verify typing remains normal in editable controls. Orca 42's
   manual presentation toggle has focus-sensitive behavior when passed `None`;
   any need for a real event requires live validation.
2. From browse content, press NVDA+F2 then NVDA+Space quickly. Confirm the next
   chord reaches the application once; repeat/release F2 must cause no stray key.
   Repeat using CapsLock. Test native Orca bypass as well.
3. Hold Ctrl, Shift, Alt or Insert while disconnecting the Windows controller
   from the relay, leaving Linux connected. Reconnect and type. Repeat with
   pending CapsLock, translated title/Say All, and D held. Verify no stuck key
   or unexpected Caps Lock change. Multiple simultaneous controllers have no
   per-key ownership in the existing protocol handling; departure releases the
   shared forwarded state.
4. Queue several commands while Orca is busy, then hand control over. Confirm
   old title/Say All/Elements List requests do not run in the new session, and
   fresh Ctrl/arrow input still stops speech.
5. With Num Lock off, hold keypad Down and dedicated Down together; release each
   independently. Repeat with Insert/End/Delete, and compare Num Lock on/off on
   both endpoints. Different endpoint lock states and actual layout changes still
   need desktop testing; no lock synchronization was added.
6. In Firefox and Mousepad/Xed, pan braille, route first/last visible cells and
   move to focus. Test legacy indices and modern single-cell payloads. Formatting
   or multi-cell selection gestures must not move the caret. Check editable and
   browse caret tracking and contracted braille alignment.
7. Test NVDA+F7 categories, Escape, empty lists, disabled structural navigation,
   and activating a result. The chooser changes focus while `Gtk.Dialog.run()`
   processes Orca events; the native list GUI also reads `activeScript`. Correct
   originating-script/focus restoration needs live validation before altering it.
8. Compare native Ctrl+F and F3/Shift+F3 with NVDA+Ctrl+F and NVDA+F3 variants;
   verify F6/Shift+F6 and VS Code's editor, terminal, Quick Open, Command Palette,
   suggestions and diff shortcuts. No speculative Find or application mappings
   were added.
9. Compare NVDA-style Ctrl+Alt+Arrow table navigation with Orca 42's native
   Shift+Alt+Arrow in tables and editable grids, including headers, spans and
   boundaries. No new table mapping was added without an editable-grid gate.
10. Check previous/next braille line, keyboard chords and review reading as
    separate unsupported cases. Orca 42 exposes panning with line-boundary
    behavior, not a matching generic previous/next-line API. Braille typing,
    modifier latches and special keyboard scripts remain unimplemented. NVDA+F5
    [unloads/reloads NVDA's virtual buffer](https://github.com/nvaccess/nvda/blob/master/source/virtualBuffers/__init__.py);
    it is not mapped to browser reload. Verify any future equivalent against
    dynamic content/live regions and confirm review does not leave braille in
    flat review.

X server restart/reconnect and failed XTest release across a layout change remain
live failure-recovery cases. Existing XTest failure cleanup was preserved. The
low-latency injection path remains X11-specific; this audit establishes no
Wayland support.
