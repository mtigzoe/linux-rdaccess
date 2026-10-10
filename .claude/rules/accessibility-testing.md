# Accessibility testing rules for Claude

Follow [the shared AI development workflow](../../.github/AI_WORKFLOW.md) and [xa11y live-testing guidance](../../.github/XA11Y_LIVE_TESTING.md).

Inspect existing AT-SPI, Orca, X11, and NVDA speech/braille diagnostics before adding tools. Start with read-only observation of the live Linux desktop; do not change focus, inject keys, or restart Orca without authorization. Report isolated GUI or AT-SPI results separately from genuine Windows NVDA Remote acceptance tests. Reproduce defects before implementing fixes; do not merge PRs.
