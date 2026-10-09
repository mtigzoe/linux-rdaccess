# Upstream Orca source references for NVDA compatibility

Use this guide when developing, reviewing, and testing `linux-rdaccess`. It is reference material for Codex, Claude, and GitHub Copilot, **not** a directive to copy or replace Orca.

## Version and provenance

- [GNOME Orca upstream repository](https://github.com/GNOME/orca)
- [Orca 42.3 source tree (`ORCA_42_3`)](https://github.com/GNOME/orca/tree/ORCA_42_3/src/orca)
- [Default script](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/scripts/default.py)
- [Keyboard event processing](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/input_event.py)
- [Braille implementation](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/braille.py)
- [Orca runtime and event dispatch](https://raw.githubusercontent.com/GNOME/orca/ORCA_42_3/src/orca/orca.py)
- [Web scripts](https://github.com/GNOME/orca/tree/ORCA_42_3/src/orca/scripts/web)

`ORCA_42_3` is an upstream reference snapshot, **not evidence that the installed system runs Orca 42.3**. The Linux Mint test machine has reported Orca 42.0. First determine the actual installed version and distribution patches (for example `orca --version`, package metadata and the installed Python files), then compare relevant method bodies/behaviors. The web links above are references; verify branch/file availability and implementation at investigation time. Never assume 42.0 and 42.3 are identical.

## Which source to inspect

| Behavior | Start with |
| --- | --- |
| General commands, Say All, focus, braille-home / flat review | `scripts/default.py` |
| Keyboard dispatch, modifier handling, native learn mode, shortcut capture | `input_event.py`, `orca.py` |
| Braille keys, routing, panning and focus return | `braille.py`, `orca.py`, `scripts/default.py` |
| Browser browse/focus and structural navigation | `scripts/web/`, default script and structural-navigation classes |
| Speech cancellation, callbacks, caret placement | Default script, speech-related modules, `orca.py` |
| AT-SPI state and active script transitions | `orca.py`, script manager and relevant application script |

Also inspect the corresponding bridge implementation in `linux_rdaccess_core/`, existing integration/unit tests and `.github/workflows/nvda-orca-compatibility.yml` before modifying anything.

## Rules for compatibility changes

1. Find concrete behavioral evidence: a live reproduction, native source/installed-runtime divergence, or a deterministic failing test. Avoid speculative fixes.
2. Identify the specific Orca API/handler and NVDA-origin action. Prefer native script or Orca runtime APIs over synthetic keyboard shortcuts where possible.
3. Verify the native behavior on **the installed Orca version**; upstream 42.3 is a comparison reference, not the sole authority.
4. Preserve Orca behavior such as native caret positioning, focus ownership, command cancellation, key-up handling, input help, and shortcut capture. Keep NVDA-style commands for remote users without breaking local Orca users.
5. Add regression coverage that fails on the prior bridge implementation and passes on the fix. Include lifetime, session handoff, queued callback, focus change and held-key edge cases when relevant.
6. Use pinned upstream method excerpts only where needed for behavioral contracts; identify upstream source/version and licensing, avoid wholesale copying. Tests using mocks/Xvfb/loopback do **not** establish live NVDA, actual Orca GUI, audible speech, or physical braille acceptance.
7. Check install/upgrade behavior, controller marker/version, isolated configuration, and necessary Orca restart. Keep root Python compatibility wrappers unchanged unless explicitly tasked with migration.
8. Record links, installed-version findings, defect, test results, skipped/unrun coverage and limitations in the PR. Follow [AI development workflow](AI_WORKFLOW.md): push a PR; **do not poll GitHub Actions or merge**.

## Suggested acceptance targets

Validate against real Linux applications when live testing is available: XFCE Settings and Clock/Calendar, Thunar, terminal, Mousepad, Firefox, and VS Code. Prioritize NVDA speech, braille routing/panning, Elements List, browse/focus mode, keyboard layouts, modifier transitions and reconnection. Report separately which tests were automated versus truly live.
