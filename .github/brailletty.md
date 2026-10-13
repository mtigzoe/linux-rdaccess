# BRLTTY / BrlAPI reference for AI contributors

> Research reference only. BRLTTY is **not** required by the current linux-rdaccess NVDA Remote + Orca architecture. Do not install, start, stop, or reconfigure braille services on a user's active machines without approval.

## Upstream references

- BRLTTY source: https://github.com/brltty/brltty
- Project website and manuals: https://brltty.app/
- BrlAPI reference: https://brltty.app/doc/Manual-BrlAPI/English/BrlAPI-2.html
- NVDA source: https://github.com/nvaccess/nvda (inspect `source/brailleDisplayDrivers/brltty.py` at the relevant NVDA revision, if present)
- Project-specific semantic bridge: `nvda-addon/addon/globalPlugins/linuxRdAccess/remoteAccessSemanticBraille.py`
- Companion accessible objects: `nvda-addon/addon/globalPlugins/linuxRdAccess/remoteA11yObject.py`
- Routing observer: `linux_rdaccess_core/routing_observer.py`
- Physical test instructions: `docs/routing-tests-without-desktop-commander.md`

BRLTTY is a braille screen-reader/driver system used especially on Linux. **BrlAPI** allows external applications or screen readers to interact with a BRLTTY-managed braille display. NVDA has supported a BRLTTY braille display driver; actual availability, support and key mappings depend on NVDA version, installed BRLTTY/BrlAPI components, platform and device. Verify the exact versions before claiming compatibility.

## Current linux-rdaccess architecture

```text
Linux applications
  ↕ Orca / AT-SPI
Linux accessibility bridge
  ↕ NVDA Remote Access protocol / relay
Windows linuxRdAccess companion (semantic focus, text and caret)
  ↕ NVDA native braille handling + chosen display driver
Windows-connected physical braille display
```

BRLTTY is **not** the remote transport, an Orca-to-NVDA bridge, or a replacement for AT-SPI. It could be used as an **optional braille display backend** in a supported environment, or studied as a reference for display gestures, routing and offset handling. Do not add it to the production dependency chain merely because it can drive displays.

## What to investigate

| Topic | Research question / test |
| --- | --- |
| Driver ownership | Which process owns the physical display on Windows and on Linux? Avoid two drivers opening it simultaneously. |
| Routing commands | Does the display send the expected routing cell, and does that become an NVDA routing gesture? |
| Braille panning | Does the displayed window offset change without losing Linux focus context or showing stale Windows content? |
| Cursor versus editing caret | Does a physical cursor move only locally, or is a remote caret request sent and applied by Linux AT-SPI? |
| Text offsets | Do Unicode character offsets, braille cells, contractions, line wrapping and cursor positions map correctly? |
| Refresh and generation | Does a focus snapshot invalidate cached TextInfo before routing, or can a stale object silently discard the request? |
| Temporary messages | After a transient message, does the normal Linux braille region recover? |
| Connection lifecycle | Are routing commands dropped after loss of remote control, disconnect, stale session or transport replacement? |
| Display-specific gestures | Are supported gesture tables and keyboard mappings correct for the specific display and selected driver? |

A previously observed Mousepad interaction moved the user's physical braille cursor while the Linux caret did not move. This is **not proof that the BRLTTY driver is defective**: diagnose each layer separately (device/driver → NVDA gesture → TextInfo routing → companion protocol → Linux AT-SPI readback). A fix to refresh pending semantic braille before routing was included in companion build `20261013.0.3`; real physical routing/caret acceptance must still be confirmed independently.

## Investigation rules for Codex, Claude and other AI agents

1. Inspect a **pinned upstream commit/version** and record the exact files/API documentation used. Do not guess BRLTTY command semantics or NVDA driver behavior from names alone.
2. Determine whether the current user setup actually uses BRLTTY. A Windows-connected Eurobraille b.note running under another NVDA driver is not automatically BRLTTY-backed.
3. Compare standard NVDA braille gesture behavior with the companion's routing and caret callbacks. Prefer supported NVDA APIs and local focused regressions.
4. Capture **bounded, sanitized, read-only** metadata where feasible: connection/control generation, focus identity, requested numeric offset, Linux caret offset and timing. Do not collect private text, passwords or entire accessibility trees.
5. Confirm keyboard, semantic braille, speech and physical display independently. **Only the user can confirm physical braille output**; simulated driver events are not physical acceptance.
6. Check behavior with BRLTTY absent by default. Optional BRLTTY coexistence experiments require explicit permission and a safe rollback procedure.
7. Do not start `brltty`, bind BrlAPI, switch NVDA display drivers, take over a USB/Bluetooth device, change Orca braille configuration, restart NVDA/Orca, or disable another add-on without the user's explicit authorization.
8. Keep the existing five-minute NVDA test-session IPC limited to authorized status, connection and cancellation; it does not authorize arbitrary desktop control.
9. Track findings against the relevant open accessibility issues, especially braille routing/panning and reconnect, without claiming complete acceptance from unit tests.

## Licensing, integration and attribution

Review upstream BRLTTY's current source and per-file notices before copying any implementation. BRLTTY includes copyleft-licensed components (often LGPL/GPL depending on component), so **do not assume a single repository-wide license applies to every file**. The linux-rdaccess repository contains Apache-licensed Linux components and a GPL-2.0-or-later Windows NVDA companion. Direct copying requires a deliberate license compatibility and attribution review; prefer original implementations informed by published API behavior.

Document the pinned source revision, affected file, copyright/license and modifications if any code is reused. An optional integration must include graceful absence handling, dependency documentation, isolated tests and a clear reason to add the dependency.

## Related project documentation

- `.github/brailleentender.md`: BrailleExtender reference (different add-on; not BRLTTY).
- `nvda-addon/README.md`: Windows companion build/installation and acceptance limits.
- `docs/ai-acceptance-testing.md`: layered acceptance evidence.
- `docs/routing-tests-without-desktop-commander.md`: user-operated physical routing and read-only Linux AT-SPI observation.

**Status:** Research reference only. No BRLTTY installation, driver selection, runtime change, or physical braille verification is implied by this document.
