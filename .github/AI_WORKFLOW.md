# AI Development Workflow

This policy applies to Codex, Claude, and GitHub Copilot when working on linux-rdaccess.

## Goal

Find, reproduce, and fix genuine NVDA–Orca compatibility defects, including keyboard input, focus, speech, braille, AT-SPI, and Linux application accessibility.

## Upstream Orca reference

When investigating NVDA–Orca behavior, consult [Orca source references](ORCA_SOURCE_REFERENCES.md) and verify against the installed Orca version before changing bridge behavior.

## Expected remote NVDA user behavior

Use [NVDA on Linux behavior contract](NVDA_LINUX_BEHAVIOR.md) to distinguish user expectations from implemented, automated-tested, and live-tested behavior.

## Root Python compatibility wrappers

Follow [Python compatibility wrappers and repository layout](PYTHON_WRAPPERS.md). Keep legacy root wrapper import and CLI paths stable; put new implementation under `linux_rdaccess_core/`. Do not move root wrappers into a `wrappers/` directory as an incidental cleanup.

## Current development priority

**Next priority:** End-to-end validation of **Orca → Windows NVDA speech and braille**, while preserving NVDA keyboard compatibility.

Verify actual speech and braille presentation on the Windows NVDA side, including accessible names, roles, states, focus/caret synchronization, speech cancellation, braille panning and routing. Distinguish forwarding Orca-generated text/events from genuine NVDA-style semantic presentation. Add automated regressions where possible and separately document live NVDA and physical braille acceptance. Do not claim end-to-end success based only on mocked, loopback, or Xvfb tests.

## Evidence-based accessibility acceptance

Automate as much of the verification as practical, but distinguish **software-observed events** from **human-confirmed speech and tactile output**. The detailed requirements and status labels are in [NVDA on Linux behavior contract](NVDA_LINUX_BEHAVIOR.md).

- **Automated:** exercise keyboard translations, focus/caret changes, accessible roles/names, transport, speech event requests, braille buffers, and stale-session defenses. A passing test proves only the behavior and observation point it actually tested.
- **Live, instrumented:** where authorized, use actual Windows NVDA and Linux Orca/AT-SPI with timestamped, correlated observations. Speech Viewer or speech hooks show emitted speech data, not necessarily audible speech quality. Braille buffers and simulated routing/panning do not prove physical display behavior.
- **Human acceptance:** require selected real-world checks of audible output (including cancellation, timing and usability) and physical braille (tactile cells, routing buttons, panning) for initial end-to-end release acceptance and for changes impacting those behaviors. Do not demand a full manual matrix for every unrelated code change.
- **Explicit outcomes:** record PASS, FAIL, BLOCKED, NOT_RUN, or NEEDS_HUMAN_VERIFICATION per test and per layer. If a claim requires physical or audible confirmation and none occurred, **never report PASS** for that claim. Keep automated successes separately identified.
- **Evidence:** record application/version, NVDA/companion/Orca/bridge versions, display model when applicable, command/input path, expected and observed behavior, relevant timestamps/logs, and limitations. Protect private text and credentials.
- **Defect attribution:** compare the app with native Orca, inspect AT-SPI, then investigate mapping, transport and Windows companion. An Orca failure alone does not prove an application defect; label the cause undetermined until demonstrated.

## Live Linux Mint testing with xa11y

For live testing on the active XFCE session, follow [xa11y and AT-SPI live-testing guidance](XA11Y_LIVE_TESTING.md). Use xa11y for Linux accessibility-tree observation and targeted actions, but require separate Windows NVDA Remote input, speech, and braille evidence for end-to-end compatibility claims. Preserve the active desktop and remote connection; do not substitute AT-SPI actions for real NVDA keyboard gestures.

## Efficient development

1. Inspect the relevant code and existing tests before changing anything.
2. Reproduce or establish clear evidence for each bug; do not make speculative changes.
3. Keep changes small and add targeted regression coverage.
4. Run focused local tests for changed behavior. Broaden testing when warranted by risk or a failure, but avoid repeating unchanged successful suites.
5. Report any failing, skipped, or unrun tests accurately. Never claim live NVDA, Orca, or physical braille validation without performing it.
6. Commit and push work to a feature or fix branch; open a pull request against `main`.
7. **Do not monitor, poll, repeatedly fetch, or wait for GitHub Actions/CI.** CI may start automatically; leave it running.
8. After opening or updating the PR, report the PR URL, summary, tests, and remaining risks, then stop. Do not merge.

## Review and merge

ChatGPT handles independent PR review, GitHub Actions verification, follow-up investigation when necessary, and merging after approval. Never bypass branch protection or required checks. A user can explicitly request a different process for a specific task.
