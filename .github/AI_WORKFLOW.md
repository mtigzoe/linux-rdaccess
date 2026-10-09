# AI Development Workflow

This policy applies to Codex, Claude, and GitHub Copilot when working on linux-rdaccess.

## Goal

Find, reproduce, and fix genuine NVDA–Orca compatibility defects, including keyboard input, focus, speech, braille, AT-SPI, and Linux application accessibility.

## Upstream Orca reference

When investigating NVDA–Orca behavior, consult [Orca source references](ORCA_SOURCE_REFERENCES.md) and verify against the installed Orca version before changing bridge behavior.

## Expected remote NVDA user behavior

Use [NVDA on Linux behavior contract](NVDA_LINUX_BEHAVIOR.md) to distinguish user expectations from implemented, automated-tested, and live-tested behavior.

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
