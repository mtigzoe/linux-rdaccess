# NVDA on Linux compatibility matrix

This matrix separates automated evidence from live NVDA/Orca acceptance testing.

Status values:

- **Automated pass** — covered by deterministic repository tests.
- **Live pass** — confirmed with Windows NVDA controlling the real Linux desktop.
- **Partial** — core semantics work but an interaction differs from NVDA expectations.
- **Fail** — confirmed compatibility defect.
- **Live pending** — automated prerequisites pass, but real application/device validation is still required.
- **N/A** — the pattern does not apply.

## Pre-live control-pattern coverage

| Pattern | Automated evidence | Live target | Status |
| --- | --- | --- | --- |
| Push button | name, role, focus, action contract | XFCE Settings, dialogs | Automated pass / Live pending |
| Check box | checked state, focus, action contract | XFCE Settings | Automated pass / Live pending |
| Radio button | checked/selected state | Settings dialogs | Automated pass / Live pending |
| Combo box | focus, value, action semantics | XFCE Settings | Automated pass / Live pending |
| Slider | numeric/human-readable value | Sound/display settings | Automated pass / Live pending |
| Single-line entry | text, caret, selection | GTK dialogs, Settings | Automated pass / Live pending |
| Multiline text | text, newlines, caret | Mousepad, Xed | Automated pass / Live pending |
| List/tree item | active descendant, selection, actions | Thunar, Settings lists | Automated pass / Live pending |
| Table/grid cell | focus/selection semantics | Update Manager, browser tables | Automated pass / Live pending |
| Tabs | selected page-tab semantics | Settings, VS Code | Automated pass / Live pending |
| Menu/menu item | focus/action semantics | XFCE panel/app menus | Automated pass / Live pending |
| Dialog | ancestor context and focus return | GTK Open/Save, confirmations | Automated pass / Live pending |
| Progress bar | value semantics | Update Manager | Automated pass / Live pending |
| Calendar/date cell | focus/selected cell semantics | XFCE clock/calendar | Automated pass / Live pending |
| Dynamic status | focused name-change behavior | notifications/status areas | Automated pass / Live pending |
| Duplicate labels | object identity prevents false dedupe | dialogs with repeated buttons/fields | Automated pass / Live pending |

## Deterministic fixtures

### GTK control gallery

Run:

```bash
python3 tests/apps/accessibility_smoke_app.py
```

CI can inspect the same declared matrix without GTK:

```bash
python3 tests/apps/accessibility_smoke_app.py --list-controls
```

The gallery includes:

- application menu
- push button
- check box
- radio buttons
- combo box
- slider
- entry
- multiline editor
- list/tree view
- notebook tabs
- progress bar
- calendar
- modal dialog
- dynamic status label

### Firefox control-pattern fixture

Open:

```text
tests/fixtures/browser-control-patterns.html
```

It includes:

- headings and landmarks
- links
- text entry and textarea
- check box and radio buttons
- select/combo box
- range slider
- button
- ARIA tabs
- ARIA tree
- ARIA grid
- progress and live status
- modal dialog
- dynamic accessible-object replacement/removal
- heading levels 7–9

The dynamic section exists specifically to reproduce stale accessible-object lifetime defects such as an Orca native list retaining a target after DOM replacement.

## Live application matrix

| Area | Applications / target | Acceptance focus | Status |
| --- | --- | --- | --- |
| Desktop | XFCE desktop/panel/menu | focus, arrows, activation, menus | Live pending |
| Settings | XFCE Settings Manager | labels, checkboxes, combos, sliders, tabs | Live pending |
| Clock | XFCE panel clock/calendar | focus, activation, date navigation, Escape restoration | Live pending |
| Files | Thunar | list/tree selection, rename, menus, dialogs | Live pending |
| Terminal | XFCE Terminal | typing, cursor/output, shortcuts | Live pending |
| Text editing | Mousepad, Xed | caret, selection, Find, dialogs | Live pending |
| Browser | Firefox | browse/focus, forms, tables, F7, dynamic DOM | Live pending |
| Electron | VS Code | editor, Explorer, terminal, tabs, command palette | Live pending |
| GTK dialogs | Open/Save and confirmations | labels, file list, buttons, focus restoration | Live pending |
| System apps | Update Manager, Software Manager | tables, progress, dialogs | Live pending |
| Notifications | XFCE notifications | announcement without focus theft | Live pending |
| Braille | 40/80-cell displays | pan, route, focus/cursor tracking | Live pending |
| Speech | all targets | interruption, no duplicate/stale speech | Live pending |
| Keyboard | desktop/laptop layouts | modifier ownership, pass-through, lock keys | Live pending |
| Reconnect | all targets | no stuck keys/stale speech/focus/braille | Live pending |

## Release evidence rule

Do not describe an item as fully compatible solely because unit tests pass. Automated tests establish the bridge contract; live results establish application/device compatibility.

A strong NVDA-compatible Linux desktop claim should require:

1. no critical keyboard, focus, speech, or braille failures;
2. desktop, Settings, files, browser, terminal, and GTK-dialog core patterns live-pass;
3. Firefox browse/focus/forms/tables/F7 live-pass;
4. supported NVDA Desktop and Laptop command matrices live-pass;
5. representative 40-cell and 80-cell braille pan/routing live-pass;
6. reconnect tests show no stale accessibility state;
7. unsupported NVDA commands are documented and fail safely;
8. every confirmed compatibility defect receives an automated regression test where practical.
