# AI-assisted remote live accessibility testing

This guide supplements [AI_WORKFLOW.md](AI_WORKFLOW.md), [XA11Y_LIVE_TESTING.md](XA11Y_LIVE_TESTING.md), and the [issue #61 live procedure](../docs/testing/issue61-live-acceptance.md). It applies to Codex, Claude, ChatGPT and other authorized agents assisting with Windows NVDA → NVDA Remote Access → linux-rdaccess → Orca → Linux AT-SPI. This document **does not grant persistent remote access, permission to type, or permission to modify a computer**. Access is limited to already configured tools and explicit user authorization for the current activity.

## Division of responsibilities

- **Agent:** Check connection, integration, version and session status using read-only tools; observe Linux focus/caret/AT-SPI events; correlate timestamps and reports; capture redacted results; maintain an evidence draft or PR. Explain the next single gesture and wait for a user report.
- **User:** Decide when testing begins and stops; make each physical Windows NVDA and b.note gesture unless separately authorizing an agent-driven action; report the physical braille cells and position. The agent must not infer physical output from software logs.
- **Speech:** Distinguish observed Windows NVDA audible speech, any instrumented Windows-side speech evidence, local Linux Orca speech, and unsupported inference. If no reliable Windows-side observation exists, record **UNVERIFIED**.

## Access and safety gates

1. Obtain explicit approval for the **specific session and scope**. A general request to help with testing does not authorize installing software, remote key injection, control handoff, disconnect, restart, file mutation on the Linux host, or changes to production settings.
2. Prefer existing Desktop Commander on Windows plus authorized SSH to Cyber for light, **read-only** diagnostics. The Cyber Desktop Commander agent may be offline even when SSH is available. Do not treat SSH access as permission to interact with the active desktop.
3. Confirm the target Linux graphical session before interpreting observations. SSH defaults may differ from the active XFCE `DISPLAY=:0` and session D-Bus; inspect rather than alter environment. Existing tools and guides take precedence over guessed commands.
4. Do not use direct Linux key injection, xa11y actions, AT-SPI setters or scripted focus changes as evidence that Windows NVDA keyboard routing worked. Such actions bypass the path being accepted. Do not send mouse input or run unrequested applications.
5. Observe only target fixture/application metadata: role, focused state, caret offset, minimal element label, session generation, timestamp, and error status. Never record private editable contents, credentials, relay addresses, channel keys, tokens, unrelated accessibility trees or entire desktops.
6. Never change, restart or interfere with an ongoing Chromium/Electron build (#79), swap, cgroups, CPU allocation, Docker, XFCE, Orca, NVDA, relay configuration, braille drivers, or add-ons without separate explicit approval. Do not silently relax safety limits.
7. Any agent-driven control action must comply with the existing consent mechanism, including its five-minute scope. Never bypass it; read-only observation does not confer control permission. Stop immediately if the user asks.
8. Before each physical gesture, capture **baseline state** without changing it: connection attached/disconnected, local/remote control, active integration and available versions, Linux application and focus, caret where relevant, and observed prior events. If the required fixture is not focused, say so and ask the user; do not focus it yourself.
9. One physical gesture at a time, with its own observation interval. Do not prompt a duplicate gesture while the previous outcome is unknown. For intentional race tests requiring a timed sequence, treat the sequence as one explicitly identified trial and record constituent key timing.
10. Any unexpected focus, stale output, stuck modifier, reconnection problem, conflicting input source or unexplained hardware behavior requires stopping and recording before further tests. Follow the issue #61 recovery/stop conditions; do not improvise fixes during a live session.

## Suggested workflow

1. **Read existing instructions and status.** Start with [issue #61 procedure](../docs/testing/issue61-live-acceptance.md) and its [results template](../docs/testing/issue61-live-acceptance-results-template.txt). For keyboard, speech and braille also review issues #57, #58, #59 and #72, but keep their acceptance outcomes separate. Use existing diagnostics under `diagnostics/` and `tools/diagnostics/` rather than creating a redundant test framework.
2. **Read-only preflight:** inspect available Remote Access/bridge connection diagnostics and currently installed integration; record legacy-versus-standalone path and the exact evidence supporting each version claim. Verified file hashes prove files on disk, **not necessarily the exact controller loaded in memory**. A negotiated semantic-braille capability does **not** establish physical b.note output. Never claim companion .4 coverage when .2 remains installed.
3. **Baseline observation:** use existing Linux diagnostics or metadata-only AT-SPI observation over an authorized SSH session, ensuring the correct display/bus without starting a second Orca, changing focus, or invoking diagnostic flags that inject keys or activate windows. Limit observation windows and resource overhead; check whether #79 activity makes the host too busy.
4. **Guided user action:** name the case/step and give exactly one action. Wait for the user's report of Windows NVDA speech, b.note text/cells, and unexpected behavior; don't claim audible output when only Linux logs exist.
5. **Correlate evidence:** compare the pre/post connection and focus/caret metadata with the user's observations. Explicitly label **Linux AT-SPI observation**, **Windows NVDA evidence**, and **physical b.note report**. A Linux focus change only confirms Linux behavior, not Windows NVDA speech or braille.
6. **Record:** populate a per-session copy of the text template with exact gesture, expected and observed values, session/integration versions, time, reproducibility, unexpected input, and `PASS`, `FAIL`, `INCONCLUSIVE`, or `NOT RUN`. Race attempts should say `no failure observed in N attempts`, not prove absence of a race. Only report a PASS for what was actually observed.
7. **Report and stop:** summarize findings in a draft PR or issue comment as explicitly approved. Avoid putting identifying or secret diagnostics in public GitHub evidence. Do not merge, close acceptance issues, deploy changes, or start the next test without permission.

## Current issue boundaries

- **#57:** Windows NVDA keyboard and modifier behavior requires real gesture evidence; Linux-only synthetic injection is not acceptance.
- **#59 and #72:** hardware routing/panning and temporary-message tests require the user's b.note observations. Semantic negotiation or software-generated braille is insufficient.
- **#61:** handoff, reconnect, stale input/speech/braille, modifier recovery and Orca restart require the specific live procedure. Some failure-injection cases are explicitly NOT RUN unless a separate safe method is approved.
- **#58:** interrupt/Say All speech cannot be marked audible PASS solely from Linux event or braille data.
- **#79:** independent resource-sensitive Chromium/Electron work; must not be disrupted by live testing.

This file is guidance for **authorized assistance**, not a new service, executable automation, access grant, or proof of successful accessibility acceptance.
