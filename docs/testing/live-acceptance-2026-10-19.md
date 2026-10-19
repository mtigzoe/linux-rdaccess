# Readiness recheck: 2026-10-19

Related issues: #57, #59, #61. PR #146 remains draft.
No acceptance test has run; K57-01 remains UNVERIFIED with zero attempts.

## Authorization and current status

Miriam reported activating the five-minute test grant. Descriptor validation
succeeded, but the restricted execution context received Windows access-denied
error 5 when opening the protected local pipe. The same status-only command
succeeded with the reviewed execution access needed for that pipe; the NVDA
consent checks were retained. No consent file was changed or renewed.

Authenticated status reported connected transport, bridge attached, semantic
braille negotiated, temporary messages supported, and remote_control_active
false (Windows local keyboard control). Physical braille remains unverified.
This is point-in-time evidence, not permission to install or restart software.

## Source and desktop recheck

Latest fetched main remains 6d24df2179f7484f4a01a66a708afc24dde1173e.
At 10:14:53 EDT, all four Linux targets matched original rollback hashes,
modes and ownership; none matched the prepared update. Controller/runtime disk
markers remain v121. Orca PID 1867 was active; exact loaded revision remains
unverified. No Mousepad or selected build/compiler process, or issue #79 user
service unit, was found. Load was 0.16 / 0.08 / 0.07 on 16 logical CPUs.
These observations do not establish build completion.

Installed companion's 16 Python modules and manifest match the captured .2
rollback package. Prepared .4 has the expected hash, CRC and manifest, with
20 entries and 16 modules. No active application or settings were changed.

## Rollback refresh

The saved profile recheck found content changes only in addonsState.json and
addonStore/_cachedCompatibleAddons.json. Current nvda.ini and guiState.ini
contents were unchanged despite new timestamps.

A private incremental snapshot captured these two changed files. All 3,836
saved-state files were checked, source contents remained stable during capture,
and the base plus incremental restore matched current hashes. No files were
removed. The original base archive is retained. Current ACL exports contained
4,587 records validated with Windows APIs; no ACL was replayed onto the live
profile. The protected rollback index records the base-plus-overlay recovery
order. No live profile write occurred.

Incremental archive SHA-256:
23a799ef4adaafb105cf6a1d77af05a86a6b02fdb1dd049b1af8f306d0c29076

## Next approval boundary

The existing [four-file plan](live-acceptance-upgrade-2026-10-18.md) remains
applicable. Installation is not authorized by a five-minute endpoint grant.
The next proposed action is replacement of only those four Linux files,
with original hashes rechecked immediately beforehand and automatic restoration
of those same captured files if file validation fails. This action excludes
Orca restart, NVDA installation/restart, handoff/reconnect and desktop input.

File replacement could affect a later import in running Orca. Independent SSH
and the verified rollback data are available. Any restart needed for recovery
still requires separate approval. Windows activation also awaits an agreed
accessible recovery method. Mousepad setup and K57-01 follow only after approved
activation and readiness verification.

No PASS or FAIL was recorded. #57, #59 and #61 remain open.
