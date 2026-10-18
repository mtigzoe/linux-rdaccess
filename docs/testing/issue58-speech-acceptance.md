# Issue #58 — NVDA speech automated coverage and live acceptance

Status: **coverage inventory only; no live NVDA acceptance claimed**.

Issue: https://github.com/mtigzoe/linux-rdaccess/issues/58

## Verified code and existing automated tests

Review of current main found the following implementation contracts:

- `linux_rdaccess_core/connection/remote_access.py` method `_linux_rdaccess_stop_nvda_speech` sends an immediate `cancel` protocol message to the connected slave transport, rather than waiting for another utterance.
- `_linux_rdaccess_stop_local_speech` increments the speech epoch on request, coalesces duplicate queued local stops, and schedules speech-dispatcher cancellation on Orca's main thread.
- The legacy-customization Say All wrapper tracks run identity, connection/session state, speech epoch and native callback progress so expired END/CANCEL progress should not restore previous focus.
- `tests/unit/accessibility/test_speech_lifecycle.py` covers Ctrl interruption, repeats, disconnect cleanup, name-only Ctrl identification, explicit VK priority, Orca 42 server discovery and customization backup/idempotence.
- `tests/unit/accessibility/test_browser_command_context.py` exercises mapped Say All commands and keyboard command routing.

These establish testable *software behavior*, not the correctness of audible Windows NVDA output. Do not interpret mocks, synthetic queues, or protocol messages as live speech playback.

## Automated follow-up investigations

Run or extend tests in isolated CI/loopback environments for:

1. A Ctrl stop received while an earlier local-stop callback is pending and connection generation changes.
2. A stale END/CANCEL from a prior Say All run arriving after a new Say All or focus/session change; ensure no old caret/focus restoration.
3. Network send failure during immediate NVDA `cancel`, followed by reconnect and a fresh Ctrl interruption; ensure failures remain observable and no old transport owns a later command.
4. Rapid Ctrl repeats and release boundaries, including queued local stops.
5. Start/stop of Say All during app/focus changes, verifying native progress callbacks are handled only for their owning run.

Before implementing a production fix, reproduce an actual failing assertion on unchanged main and check for equivalent existing tests. Do not alter the speech pathway purely to satisfy a mocked assumption.

## Live acceptance still required

With the user's explicit consent for a controlled session, test from Windows NVDA through Remote Access to Linux Mint/Orca 42.0, recording:

| Scenario | Actual action and focused object | Expected Windows NVDA speech | Observed speech / result |
| --- | --- | --- | --- |
| Focus/name/role/state | Focus a GTK control | Semantic announcement or documented forwarding behavior | Not tested |
| Title/current line | Invoke mapped commands | Relevant title/current line, correct interruption | Not tested |
| Ctrl interruption | Start long utterance, press/release Ctrl | Prompt silence without stale continuation | Not tested |
| Say All cancellation | Start Say All, stop during a sentence | No resumed old speech/caret jump | Not tested |
| Focus/app switch | Switch windows during Say All | Old session cannot restore caret/focus | Not tested |
| Disconnect/reconnect | Break session during speech, reconnect | No old END/CANCEL affecting new session | Not tested |
| Notification | Trigger a safe application notification | Correct ordering and presentation path | Not tested |

For each test capture exact key sequence, application/control, expected vs. heard output, Orca-local-vs-Windows presenter path, session state, and reproducibility. Do not silently substitute braille or local Orca output for Windows NVDA speech. Keep #58 open until this acceptance is done.

## Safety

Do not access the user's active desktop, restart Orca/NVDA, inject keyboard events, change braille devices/settings or interfere with the issue #79 Chromium/Electron build on Cyber. CI and isolated non-GUI unit work can proceed independently.
