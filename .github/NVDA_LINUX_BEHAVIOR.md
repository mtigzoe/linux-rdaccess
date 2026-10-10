# Expected NVDA behavior when controlling Linux Mint

This is the **user-facing compatibility contract** for Windows NVDA controlling a Linux Mint XFCE desktop through linux-rdaccess. Read it alongside [AI workflow](AI_WORKFLOW.md) and [Orca source references](ORCA_SOURCE_REFERENCES.md).

## Architecture and objective

Windows NVDA + NVDA Remote Access → linux-rdaccess transport/controller → Orca runtime and adapters → AT-SPI → Linux applications.

**Goal:** A Windows NVDA user should be able to operate Linux applications with familiar NVDA keyboard conventions and understandable Windows-side speech and braille, without needing to learn Orca shortcuts merely to accomplish equivalent tasks. This is a design goal, **not a claim of full compatibility**.

Orca remains the Linux accessibility engine. Preserve Orca semantics and local accessibility while translating remote NVDA intent. Prefer semantic Orca APIs to fragile simulated key sequences. Local Orca output and Windows NVDA output may differ; report differences instead of claiming they are identical.

## Current development priority

**Next priority:** End-to-end validation of **Orca → Windows NVDA speech and braille**, while preserving NVDA keyboard compatibility.

Verify actual speech and braille presentation on the Windows NVDA side, including accessible names, roles, states, focus/caret synchronization, speech cancellation, braille panning and routing. Distinguish forwarding Orca-generated text/events from genuine NVDA-style semantic presentation. Add automated regressions where possible and separately document live NVDA and physical braille acceptance. Do not claim end-to-end success based only on mocked, loopback, or Xvfb tests.

## Behavioral expectations

### Control, keyboard and command ownership
- NVDA Remote's control handoff (e.g. Insert+Alt+Tab) must reliably distinguish local and remote control.
- Familiar NVDA commands should map to the corresponding Linux accessibility action in desktop and laptop layouts, including Insert/CapsLock modifiers, input help, pass-next, browse/focus mode, heading/link/form navigation, and Elements List when supported.
- Preserve native keyboard input during Orca's shortcut-capture mode and describe commands (without executing them) during input help.
- A press, repeat and release belong to the same remote session and action. Prevent stuck modifiers, cross-session injections, duplicate shortcuts and stale deferred actions.
- Switching focus, disconnecting or transferring control must invalidate obsolete callbacks and key ownership without disrupting valid current input.

### Speech and Say All
- Focus, selection, status and navigation feedback should be announced on the **Windows NVDA side** in the correct order, without unwanted duplicate local speech.
- NVDA stop/cancel and relevant braille navigation should interrupt applicable speech and Say All. Queued callbacks must not resume an old utterance.
- Preserve native Orca caret placement where appropriate (e.g. cancel/home); explicit braille routing must not be undone by an earlier Say All caret callback.
- Describe commands in input-help mode without executing them; respect localized native handler descriptions when available.

### Braille
- Aim for a coherent Windows NVDA braille experience: correct focus text, controls/roles, panning, routing, cursor tracking, and return-to-focus.
- Do **not** assume Orca's text/role wording (e.g. “Push button”) matches NVDA's phrasing. Decide which component produces final braille and verify the actual displayed text before declaring parity.
- Braille commands should respect focus/session/display validity. After a control handoff or disconnect, queued routing or panning must not affect the new session.
- Some native braille operations should interrupt speech (e.g. return-to-focus and routing), while ordinary panning should not unless evidence shows otherwise.
- Distinguish simulated braille tests from physical braille display validation.
- Temporary Orca braille messages ("Focus mode", Caps Lock, shortcut announcements) should be available on Windows NVDA braille while semantic braille is active, shown with NVDA's own braille message so NVDA keeps control of focus, caret, routing and panning presentation. Raw Orca cells must not be forwarded for this. Status: **Implemented (code-reviewed)** and **Automated-tested** with loopback and fake NVDA handlers on both sides; **Known issue / not verified** with live Windows NVDA and a physical braille display (see issue #59).

### Browse mode and Linux apps
- In Firefox, test headings (including levels), links, forms, tables, landmarks, quick navigation, Elements List, browse/focus switching, and reading versus editing.
- In XFCE Settings, Clock/Calendar, Thunar, terminal, Mousepad and VS Code, test Tab/Shift+Tab focus, keyboard activation, accessible names/roles/states, caret and selection reporting, menus/dialogs and navigation.
- Preserve application-native and Orca-native behavior where a command has no faithful NVDA analogue. Unsupported behavior must be documented rather than silently faked.

### Connection transitions and safety
- Reconnection, role changes, last-master departure and remote-control handoffs must expire stale operations.
- Never inject keyboard events into a different focus/window/session based on an old request.
- Keep private connection keys and user content out of logs and tests.
- Avoid modifying the active desktop for automated Xvfb or loopback tests.

## Status and evidence labels

Every compatibility claim and issue should use one of these labels:

- **Expected:** desired NVDA user behavior; not yet proof of implementation.
- **Implemented (code-reviewed):** code path exists and was reviewed; not necessarily observed live.
- **Automated-tested:** regression passed using mocks, Xvfb, or protocol loopback; specify environment and test.
- **Live-tested:** observed with real Windows NVDA controlling Linux Mint; specify NVDA/Orca versions and app.
- **Physical-braille-tested:** observed on an actual connected braille device; identify device and output.
- **Known issue / not verified:** missing, inconsistent, or untested behavior.

Do not turn an automated-tested statement into a live-tested claim. Recent bridge changes have been covered by automated CI, but there has not been comprehensive live NVDA, audible speech and physical braille acceptance for every behavior described here.

## Suggested manual acceptance matrix

For each app/gesture record: NVDA action; expected announcement/braille; observed speech and braille; actual focus/caret; pass/fail; Windows NVDA and Remote Access versions; Linux distro, Orca and bridge versions; device (if any); reproducible steps.

1. Control handoff; type, navigate, return to Windows; check no stale or stuck keys.
2. XFCE Settings and Clock/Calendar: focus movement, labels, role/state, activation.
3. Thunar: navigate file list and return with Shift+Tab; compare reported focus.
4. Mousepad and terminal: caret movements, selection, editing, speech interruption.
5. Firefox: headings/forms/tables/Elements List, focus-mode entry/exit, shortcut capture and input help.
6. VS Code: editor caret, tabs, tree view, menus and responsiveness.
7. Braille: panning, routing, home/return-to-focus, roles and speech interaction.
8. Disconnect/reconnect during queued speech, key presses, Elements List, or routing.

## Instructions to coding agents

Before fixing a behavior, inspect the bridge's `linux_rdaccess_core/` code, relevant tests, and installed Orca source (see [reference guide](ORCA_SOURCE_REFERENCES.md)). Establish an actual defect with a regression that fails against the old code; fix minimally; verify command ownership, session/focus lifetime, and upgrades; then document test evidence and remaining live-validation limitations. Keep root Python compatibility wrappers unchanged unless explicitly tasked otherwise. Follow [AI workflow](AI_WORKFLOW.md): open a PR, do not monitor GitHub Actions and do not merge.
