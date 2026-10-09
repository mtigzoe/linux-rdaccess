# Live Linux Mint accessibility testing with xa11y

This guide supplements [AI_WORKFLOW.md](AI_WORKFLOW.md) and [NVDA_LINUX_BEHAVIOR.md](NVDA_LINUX_BEHAVIOR.md). It applies to Codex, Claude, Copilot, and other agents testing `linux-rdaccess`.

## Purpose and scope

Use [xa11y](https://github.com/xa11y/xa11y) (note the spelling: **xa11y**, not x11y), backed by Linux AT-SPI2, to observe and selectively exercise the **real, running Linux Mint XFCE desktop**. The agent can inspect accessible names, roles, states, focused objects, and text/caret behavior, and can record evidence from real applications.

This is **live Linux accessibility testing**, not automatically an end-to-end NVDA compatibility test. The intended end-to-end path is:

Windows NVDA → NVDA Remote Access → linux-rdaccess → Orca / Orca integration → AT-SPI → Linux applications.

An AT-SPI tree or an xa11y action cannot by itself prove what Windows NVDA announced, whether an NVDA keyboard gesture traversed the bridge, or what a physical braille display showed. Correlate Linux observations with Windows-side NVDA speech, input, and braille evidence where available. Mark other checks **NOT TESTED** or **BLOCKED**, never PASS.

## Establish the correct live session

1. Read the workflow, current architecture, diagnostics, and existing smoke/live-test utilities. Reuse pyatspi/Orca instrumentation; do not create a duplicate framework without demonstrating a gap.
2. Run in the **existing XFCE desktop session** (typically X11 `DISPLAY=:0` on the development host), not an unrelated SSH, Xvfb, xrdp, or temporary desktop session. Confirm `DISPLAY`, `XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`, session ownership, and AT-SPI accessibility-bus access. An SSH terminal may lack the graphical session environment.
3. Confirm Orca and the existing NVDA Remote connection state **without restarting, reconfiguring, or disconnecting them**. Do not steal keyboard focus, send key sequences, click controls, type text, or launch/quit user applications during initial discovery.
4. Capture only minimal diagnostic information: application, accessible object role/name/state, focus/caret events, monotonic timestamps, and relevant bridge observations. Avoid logging passwords, secret keys, private text fields, or unrelated user data.

## Install and connect xa11y (opt-in)

Use a Python virtual environment rather than altering system Python:

```sh
python3 -m venv ~/.venvs/xa11y
~/.venvs/xa11y/bin/python -m pip install xa11y
~/.venvs/xa11y/bin/xa11y apps
```

AT-SPI2 must be running and accessible in the graphical session. Validate the CLI version and current syntax against [xa11y CLI documentation](https://xa11y.dev/reference/cli/) before using commands; do not assume undocumented flags.

For an agent running **on Linux Mint and in the correct session environment**, the xa11y MCP stdio server is:

```sh
~/.venvs/xa11y/bin/xa11y mcp
```

For Codex CLI, one possible registration is:

```sh
codex mcp add xa11y -- /home/miriam/.venvs/xa11y/bin/xa11y mcp
codex mcp list
```

Adjust the absolute path to the actual installation. The server inherits environment from its launching client; connecting VS Code through Remote-SSH does not guarantee its subprocess has access to the logged-in desktop bus. Verify access before declaring a test runnable. Do **not** add xa11y to production dependencies solely for this workflow.

Some apps may expose an incomplete tree without accessibility configuration: Electron/Chromium applications including VS Code may need `--force-renderer-accessibility`; Firefox may need `MOZ_ACCESSIBILITY_ATK2=1`. Assess the existing running application first; do not restart it to set flags without permission. See [xa11y Linux platform notes](https://xa11y.dev/reference/platform-details/).

## Evidence-first test procedure

1. **Observe only:** list applications and inspect the accessibility tree of a specific target; verify focused object, roles, labels, states, and element identity. Compare against existing `pyatspi` probes.
2. **Establish expected behavior:** record what Orca/AT-SPI should expose and what an NVDA user should hear, read in braille, or navigate. Separate application accessibility from bridge behavior.
3. **Exercise one controlled interaction** only in an explicitly approved live-testing window, avoiding disruptive actions and private application content. AT-SPI actions can test the application but may bypass NVDA Remote input mapping.
4. **For keyboard translation**, send the actual key sequence through Windows NVDA Remote, not `xa11y.press()` or a direct AT-SPI action; collect evidence from both ends.
5. **For speech and braille**, collect Windows NVDA observations using existing probes or approved instrumentation, plus physical-device confirmation when required. Distinguish received Orca messages from NVDA-formatted output.
6. **Diagnose:** compare timestamps and object identities across AT-SPI, Orca, bridge, and Windows NVDA logs; account for focus transitions, stale objects, reconnects, speech cancellation, braille routing/panning, and latency.
7. **Report precisely:** PASS / FAIL / BLOCKED / NOT TESTED for each *layer*, with app/version, session, input path, reproduction steps, observed vs expected behavior, logs, and test limitations. No PASS based on mocks, Xvfb, or AT-SPI-only observations for an end-to-end claim.
8. **Fix only reproduced defects:** create a regression that fails on unchanged baseline, make the narrowest fix, rerun relevant tests, and open a PR. Follow the no-CI-polling/no-merge policy.

## Suggested application matrix

| Application | Linux AT-SPI checks | End-to-end NVDA Remote acceptance |
| --- | --- | --- |
| XFCE Settings | labels, focused controls, dialogs, tab order | NVDA focus and control announcements |
| Clock/calendar | date and control roles, navigation focus | date and time spoken/read correctly |
| Thunar | file list selection, focus restoration | keyboard navigation, roles, braille routing |
| Mousepad/Xed | text, caret offsets, selection and whitespace | NVDA caret and editing announcements |
| Firefox | headings, links, document/browse semantics | navigation and NVDA+F7 compatibility |
| VS Code | editor tree, caret, suggestions, notifications | keyboard shortcuts, caret, braille, speech |
| Reconnect | fresh focus identities, event ordering | restored announcements, no stale braille |

Also test Caps Lock / Num Lock state, NVDA menu and speech interrupt shortcuts, braille pan/routing, and latency only through the relevant genuine input/output paths.

## Safety boundaries

- Do not modify the active desktop, Orca config, running apps, input devices, or remote connection without explicit live-test approval.
- Never assume simulated accessibility actions are equivalent to NVDA keyboard gestures.
- Do not perform destructive UI operations or expose credentials in test artifacts.
- If direct Linux session access is unavailable, document the blocker and run isolated automated checks separately, with clearly different labels.
- Preserve the existing code review rules in [AI_WORKFLOW.md](AI_WORKFLOW.md).

Upstream reference: [xa11y documentation](https://xa11y.dev/), [MCP server](https://xa11y.dev/guides/mcp/), and [CLI reference](https://xa11y.dev/reference/cli/).
