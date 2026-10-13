# BrailleExtender reference for AI contributors

> Reference only — not a dependency or an approved wholesale code import.
> Filename `brailleentender.md` is retained as requested; the upstream project's name is **BrailleExtender**.

## Upstream project

- Repository: https://github.com/AAClause/BrailleExtender
- Project: **BrailleExtender**, a Windows NVDA add-on intended to enhance braille support.
- Upstream default branch: `master`
- GitHub repository license: **GPL-2.0**. Verify notices and the exact license of any specific source file before reuse.
- Treat upstream code and behavior as external reference material, not authoritative documentation of `linux-rdaccess`.

## Why it may help this project

The standalone Windows NVDA companion in `nvda-addon/addon/globalPlugins/linuxRdAccess/` uses NVDA's native braille system to present semantic accessibility content forwarded from Linux Mint through Orca/AT-SPI and NVDA Remote Access.

BrailleExtender is worth **comparing** for implementation patterns and test ideas in these areas:

| Area to study | linux-rdaccess question |
| --- | --- |
| Routing and caret tracking | Does a routing key target the current Linux object and text offset, and reject stale objects? |
| Panning and scrolling | Does panning preserve Linux context without surfacing the Windows app's label? |
| Braille focus/context refresh | Are changed names, ancestors, dialogs, and focus transitions reflected without stale regions? |
| Display-specific gestures | Are routing, pan, and other display keys forwarded or interpreted by the correct owner? |
| Cursor position and Unicode | Do character offsets, Unicode text, and cursor placement remain consistent? |
| Temporary messages | Does normal Linux braille content return correctly after a temporary message expires? |
| Speech and braille interaction | Could global hooks disrupt NVDA speech cancellation or Remote Access behavior? |
| Multiple add-ons | Can BrailleExtender coexist with the companion without double hooks or conflicting output? |

These are **research candidates**, not claims that BrailleExtender already solves the corresponding Linux-specific problems.

## Architecture and boundaries

```text
Linux Mint apps
    ↕ Orca / AT-SPI
Linux accessibility bridge
    ↕ NVDA Remote Access relay
Windows linuxRdAccess companion
    ↕ NVDA native braille and accessibility APIs
Physical braille display
```

- Keep **NVDA native braille** responsible for the physical display.
- Keep **NVDA Remote Access** responsible for the remote transport and existing speech/keyboard-control behavior.
- Keep **linuxRdAccess** responsible for Linux-specific semantic braille, focus context, session generation and stale-event rejection.
- Do not embed BrailleExtender as another transport layer, fork its entire add-on into the companion, or require users to install it.
- Treat optional BrailleExtender installation as a **separate compatibility test**, not a prerequisite.
- Do not broaden the five-minute consent endpoint into unrestricted desktop control.

## Source locations to compare

Local companion implementation:

- `nvda-addon/addon/globalPlugins/linuxRdAccess/remoteAccessSemanticBraille.py`
- `nvda-addon/addon/globalPlugins/linuxRdAccess/remoteA11yObject.py`
- `nvda-addon/addon/globalPlugins/linuxRdAccess/a11y.py`
- `nvda-addon/tests/test_remoteAccessSemanticBraille.py`
- `nvda-addon/tests/test_semanticBrailleContext.py`

Upstream entry point for browsing: https://github.com/AAClause/BrailleExtender/tree/master/addon/globalPlugins

Read the upstream implementation and documentation before naming a particular upstream function, hook or behavior. Do not assume its APIs or compatibility with the currently installed NVDA release are unchanged.

## Safe AI investigation workflow

1. Begin with read-only source comparison on a **pinned upstream commit**; record the upstream revision and which files were actually reviewed.
2. Identify one concrete, reproducible problem in `linux-rdaccess`, or a demonstrable regression-coverage gap. Avoid speculative rewrites.
3. Distinguish NVDA native behavior, BrailleExtender enhancements, linuxRdAccess companion behavior, NVDA Remote transport and Orca/AT-SPI behavior.
4. Prefer a small independent correction using supported NVDA APIs over copying upstream source.
5. Add a failing focused regression, implement the correction, and test with and without optional BrailleExtender enabled **only with user authorization**.
6. Verify add-on load order, duplicate hooks, temporary-message restoration, focus context, routing/caret, stale events, panning, disconnect/reconnect and explicit consent boundaries.
7. Keep physical display observations separate from simulated tests. Never call physical routing or panning PASS without the user's direct confirmation.
8. Report any compatibility limits and keep existing live-acceptance issues open until their specific acceptance criteria are satisfied.

## Licensing and attribution

BrailleExtender's GitHub repository declares **GPL-2.0**. This project has Apache-2.0 Linux-side code and a GPL-2.0-or-later Windows NVDA companion. These labels **do not by themselves authorize copying files** across the license boundary. Before adapting upstream code, confirm its exact file-level license, compatibility with the destination, and obligations for copyright, notices, attribution and redistribution. Consult maintainers or legal advice where needed. Never strip upstream copyright notices.

For simple algorithms or behavior ideas, write original code and cite the upstream inspiration in the relevant PR or design note. If directly reusing code, explicitly document source URL, pinned commit, file path, copyright, license and modifications.

## Existing acceptance limitations

At the time this note was created for PR #78, two braille defects (stale retained-object actions and stale same-ID focus ancestry) were reported fixed with regression tests. The user's Firefox physical braille panning observation is a **limited PASS only**; it does not establish routing, caret tracking, temporary-message recovery or reconnect success.

Related open live-acceptance / IPC issues: #57, #58, #59, #60, #61, #72 and #76. Do not close these based solely on unit tests or BrailleExtender comparisons.

## Scope for PR #78

This is documentation for AI-assisted research. It **does not install BrailleExtender, change runtime behavior, authorize desktop interaction, resolve open issues, or approve merging PR #78**.
