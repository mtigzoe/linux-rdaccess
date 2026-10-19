# Prepared accessibility upgrade and rollback: 2026-10-18

Status: **prepared only; not installed or activated**. Miriam authorized
read-only connection checks, private rollback snapshots and isolated preparation.
No desktop input, installation, restart, disconnection or accessibility setting
change was authorized or performed. K57-01 remains unattempted. PR #146 stays
draft; issues #57, #59 and #61 remain open.

Pinned latest fetched main: `6d24df2179f7484f4a01a66a708afc24dde1173e`.
Target controller: **v123**. Target companion: **20261014.0.4**.
This four-file candidate supersedes earlier controller-only staging outputs.
See [the session record](live-acceptance-2026-10-18.md) for historical findings.

## Current state observed

The fresh status attempt initially returned authorization required/expired.
A subsequent metadata-only check found a valid existing consent descriptor;
the authenticated status-only request then succeeded with:

- Result connected; transport connected; Linux bridge attached.
- Remote keyboard control **false** (Windows local control).
- Semantic braille negotiated; temporary-message support true.
- Physical braille unverified.

This is a point-in-time observation, not a claim that a five-minute grant stays
active throughout preparation. No consent was renewed, no descriptor was
altered, and no connect/cancel/route operation was requested. Fresh consent will
be needed for later protected checks after activation.

Installed Linux controller/runtime remains v121 and companion remains
20261014.0.2 on disk. Exact loaded pure-Python versions remain unverified.
Current NVDA startup metadata supports companion initialization, not exact
loaded-byte attestation. No live acceptance is inferred from package hashes.

The repeated lightweight issue #79 checks found no active known build process:
historical PID 629572 absent; documented build scope not-found/inactive/dead;
no matching builder/compiler/linker/controller in the bounded process/cgroup
inspection, including container scopes. Unrelated Authentik was left alone.
Available memory was 11,924 MiB, swap unused, CPU approximately 99% idle, and
no blocked tasks or swap traffic were observed. Build completion and artifact
integrity are unknown; build source trees, artifacts and logs were not read.
An unusually named replacement is not exhaustively excluded. Recheck immediately
before any approved activation; if build activity appears, stop and reassess.

Existing XFCE session `:0` responded. Four X client windows were present, none
with Mousepad class; AT-SPI exposed zero Mousepad applications. No editor text,
document title or filename was read. **No safe Mousepad target was found.**
Opening a new unsaved Mousepad instance and moving focus require separate
agreement; they were not performed by this preparation.

## Verified private rollback snapshots

Archives, manifests, saved settings and restored rehearsal copies stay in
private local storage restricted to the current Windows account and SYSTEM.
No raw configuration, connection credential, personal document or log contents
are committed to this repository. Logs and crash dumps are not rollback targets;
ephemeral five-minute authorization is not restored or reused.

| Snapshot | Coverage | Verification |
| --- | --- | --- |
| Linux | Installed runtime and launcher; remote configuration; autostart entry; Orca scripts and original backups; customizations and existing customization backups; Orca user/app settings | 97 regular files, 114 metadata entries, no missing roots or symlinks; stable source hashes/metadata before and after capture; archive integrity and isolated content restore |
| Windows | Complete saved NVDA user profile including installed add-ons, profiles and settings; Windows linux-rdaccess controller settings; original ACL exports | 3,836 files, 532,309,549 bytes; stable source hashes during capture; archive CRC and isolated restore hashes; 4,587 saved SDDL records validated using Windows APIs |
| Windows companion rollback | Reconstructed installable package from the captured actual companion .2 files, manifest, license and docs | Version 20261014.0.2; 20 archive entries; CRC and every entry's hash matched captured files |

The Windows snapshot excludes one transient log; saved installation/configuration
state is retained. Unsaved in-memory NVDA preferences are not attested. Original
Windows ACL metadata was saved and parsed, but was not replayed onto the live
profile or private rehearsal children. Never restore the full profile over
running NVDA.

The complete Linux archive was additionally restored into a new private local
WSL Ubuntu directory, independent of Cyber. On Linux Python **3.10.12**, all 97
file hashes and recorded Linux modes, uid/gid and nanosecond timestamps matched.
The four-file candidate was applied there and the complete snapshot restored
again; original hashes and metadata matched after rollback. This is actual
Linux filesystem rehearsal, not a claim about the active Orca process.

| Artifact | SHA-256 |
| --- | --- |
| Linux rollback archive | `3c6bb639f55d6bb05c222364398537404b6bf626792240989136176b6f26795f` |
| Windows saved-state archive | `47bdc0f0b0f4f938eb6e37a6a9e1fa8be6825f061b2b68766e270400d29a47f4` |
| Captured companion .2 rollback package | `91ac4d44caeb496f4511b76972518629eb3eb4c649353abaac2b6b1fabb26496` |

Original `.linux-rdaccess-backup` files are upstream regeneration sources,
not substitutes for these working-state snapshots. The private manifests
retain original paths, bytes, ownership, modes and timestamps for restoration.

## Prepared Linux candidate

Only these home-relative files differ. Preserve ownership uid/gid 1000/1000
and the recorded modes; verify every original hash immediately before applying.
Abort on drift and recapture/review instead of overwriting newer state.

| Target under the Linux user's home | Mode | Purpose |
| --- | --- | --- |
| `.local/share/linux-rdaccess/linux_rdaccess_core/accessibility/atspi_nvda_braille_bridge.py` | 0664 | Align installed standalone AT-SPI/DVC bridge with merged focus-resync fix; does not prove this path is loaded |
| `.local/share/linux-rdaccess/linux_rdaccess_core/connection/remote_access.py` | 0664 | Current generator/patch implementation, preventing a later connect from regenerating an older controller |
| `.local/share/orca/orca-scripts/remote_controller.py` | 0600 | v121 to v123: command lifetime and rejected Caps capture ownership |
| `.local/share/orca/orca-scripts/transport.py` | 0600 | Current transport/output-lifetime patch |

Actual customization already satisfies the character-speech repair and all
current customization predicates, so it is not replaced. Saved configuration,
Orca preferences, autostart, launcher, standalone helpers, local-machine code
and all original backups retain their bytes in the candidate. Exact pinned Git
blob bytes were used, avoiding Windows checkout line-ending conversions.

Prepared delta SHA-256:
`2a256fe835bbbb6c305a65cae95f268a79de6667a95c23aa8b2aa6c7245adb00`.
Its private manifest contains original/staged hashes and metadata for exactly
four targets. Its embedded manifest is metadata, not an additional live target;
do not extract this archive directly over the live home directory.

All changed sources compile on Windows Python 3.13.13 and local Linux Python
3.10.12; Python 3.10 grammar also passed. Eight production validators passed:
controller, transport, local machine, event API, speech sequence, Say All,
reconnect and braille cells. Production patchers were idempotent on the staged
files on both platforms. These are isolated checks; no full runtime suite,
Python 3.12 execution or physical acceptance is claimed for this preparation.

Do not use full `connect`, `install` or `connect --no-restart` as this narrow
apply operation. They can rewrite settings or copy additional files.

## Windows candidate and dependencies

Prepared `linuxRdAccess-20261014.0.4.nvda-addon` SHA-256:
`6282ecf7a19c9df51feb9d71c48ef94319b79b3639387dd581ab46c6a5ced1a5`.

Two separate builds produced identical archives. All 16 Python modules match
exact pinned Git blobs, compile, and parse with Python 3.10 grammar. CRC,
unique member names and safe relative paths passed. Fifteen modules equal the
installed companion; only `remoteAccessSemanticBraille.py` differs, adding
queued ordinary document-route ownership protection. Installed October 14 .2
already contains one-shot message routing; this upgrade does not grant consent.

| Dependency | Installed/required |
| --- | --- |
| Windows NVDA | Installed 2026.2; candidate minimum 2026.1.0, last tested 2026.2.0 |
| Remote Access | Existing connected NVDA Remote transport; no relay setting changes prepared |
| Linux Python | Interpreter package python3.10 3.10.12-1~22.04.18; python3 meta-package 3.10.6-1~22.04.1 |
| Orca | 42.0-1ubuntu2 |
| GI / pyatspi | python3-gi 3.42.1-0ubuntu1; python3-pyatspi 2.38.2-1 |
| Liblouis | python3-louis and liblouis20 3.20.0-2ubuntu0.2 |
| xdotool | 1:3.20160805.1-4; no input injection tested |

The bridge declares no PyPI-only runtime dependencies. Packaging uses Python's
standard library. configobj 5.0.9 and Ruff 0.16.4 are development requirements,
not software to install into running NVDA. No dependency installation is
prepared or required by these source changes. Existing physical display driver,
tables and settings are retained; their live correctness remains unverified.

## Exact approval boundaries and recovery

These steps are a proposal for later approval, not actions performed here.

1. **Linux file application:** recheck build activity and the four original
   hashes; stage all four replacement files privately, verify hashes/modes,
   then atomically replace only the four reviewed targets. The group is not
   transactional. Validate the full set before restarting. Keep independent
   SSH recovery available and Windows local control established. File changes
   can affect later imports even before a restart, so application itself needs
   permission.
2. **One Orca restart on Cyber:** separately authorize a session-aware
   `orca --replace` in the confirmed existing XFCE environment. The existing
   `cli.restart_orca()` performs that replacement without rewriting saved
   connection settings. Do not invoke `connect` to obtain the restart. Linux
   control, output and the Remote connection may be interrupted. Check the new
   process, deployed hashes and recovered connection before proceeding.
3. **Windows install and one NVDA restart:** separately authorize installation
   of the verified .4 archive using NVDA's normal add-on workflow, followed by
   one NVDA restart. Windows speech/braille and Remote Access may be unavailable
   during it. Do not copy one module into running NVDA. Establish Miriam's
   accessible recovery method before this operation; it is not yet confirmed.
4. **Recovery if approved activation fails:** stop further changes. Linux
   rollback restores the four actual pre-update files and metadata from the
   verified snapshot via independent SSH, then needs an approved Orca restart.
   If wider state was unexpectedly changed, use the complete snapshot after
   reviewing drift. Windows rollback installs the captured .2 archive through
   the normal workflow and needs an approved NVDA restart. Full saved-profile
   restoration, if needed, requires NVDA stopped and separate approval. Do not
   silently retry restarts, disconnect/reconnect or alter settings.
5. **Live-test setup after recovery/activation is verified:** obtain fresh
   five-minute diagnostic authorization only as needed, separately agree any
   Remote handoff/reconnect, and establish a public unsaved Mousepad target.
   Opening/focusing that app needs permission because none was found. Then
   offer K57-01, Insert+T, as one human action and wait for Miriam's report.

No step authorizes a build action, system reboot, dependency change, add-on
conflict migration, driver change, merge or issue closure. No test-case PASS
is produced by preparing or restoring these artifacts.
