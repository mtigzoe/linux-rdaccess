# Codex testing guidance

Use the root [AGENTS.md](../../AGENTS.md) as the Codex entry point and follow the [shared AI workflow](../../.github/AI_WORKFLOW.md).

For live XFCE and NVDA–Orca testing, follow [xa11y live testing](../../.github/XA11Y_LIVE_TESTING.md). Keep the active desktop and remote connection undisturbed unless explicitly authorized. Distinguish isolated AT-SPI checks from end-to-end Windows NVDA speech, keyboard, and braille validation.

Only fix evidenced defects; run focused regression tests and report skipped or unrun tests accurately. Do not poll CI or merge PRs autonomously.
