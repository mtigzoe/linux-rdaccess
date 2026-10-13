# AI-assisted acceptance testing — Stage 3 foundation

Stage 3 tracks live accessibility evidence for issues #57, #58, #59, #60,
#61, and #72. This initial implementation is **offline and read-only**:
it does not operate NVDA, connect to the relay, drive a desktop, inject
keys, or read physical braille.

From Windows PowerShell in a local checkout:

```powershell
python .\linux_rdaccess_acceptance.py template > acceptance.json
python .\linux_rdaccess_acceptance.py summary --file acceptance.json
```

The template lists exact human-observed acceptance checks. Initially every
`status` is `unverified`. After authorizing and personally performing a
live test, edit its `status` to `pass`, `fail`, or `blocked` and add a
short `observed` note. `pass` and `fail` require evidence text.
The summary reports totals and never infers live success from passing
unit tests, SSH status, or connected NVDA processes.

**Privacy:** do not enter passwords, relay channel keys, sensitive braille
content, or private documents in `observed`. Keep your local
`acceptance.json` private and do not commit it.

Stages are independent: Stage 1 (PR #75) reports SSH readiness; Stage 2
(issue #76 and Windows rdAccess PR #10 foundation) must eventually provide
opt-in authenticated local NVDA connection/status IPC. Stage 3's current
reporting module does not depend on incomplete Stage 2 or bypass its
authorization requirements.

A future Stage 3 implementation may use a **separately authorized**
desktop-control interface to drive isolated test fixtures and record objective
XKB/AT-SPI states. NVDA speech and physical braille always require
appropriate observation before a check can pass.

For a single controlled interaction, use `session-template` and
`session-summary --file report.json` to separate keyboard delivery, Linux
focus/caret, Windows NVDA speech events, semantic braille events and
user-confirmed physical braille. These commands preserve the existing
`template` / `summary` matrix and do not infer success across layers. See
[routing acceptance without Desktop Commander](routing-tests-without-desktop-commander.md)
for the read-only SSH observer and physical routing procedure.
