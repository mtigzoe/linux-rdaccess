# Linux Remote Access Companion for Windows NVDA

This directory owns the Linux-specific Windows integration. It builds a separate
`linuxRdAccess` NVDA add-on. It runs inside **Windows NVDA**, alongside NVDA Remote
Access; the Linux bridge and AI launcher remain in `linux_rdaccess_core/`.
The companion does not require the rdAccess source repository at build or runtime.

Included components:

- Native NVDA semantic braille for Linux focus, text, caret, routing and panning.
- Remote Access transport extension negotiation, temporary braille messages and
  cleanup across transport/control changes.
- An explicit five-minute consent dialog and same-user authenticated local test
  service supporting only `status`, `connect` using saved settings, and `cancel`.
- Metadata-only test status, preserving `physical_braille: unverified`.

NVDA Remote Access continues to own speech, keyboard control and relay settings.
RDP/DVC speech and braille drivers, DLL registration, and general RDAccess
settings remain in rdAccess. Existing Linux root wrappers and commands remain
stable. NVDA's required `addon/globalPlugins/` layout is an exception to the
Linux implementation layout: these modules execute in NVDA, not the Linux CLI.

## Build

From the repository root, using Python 3.13:

```powershell
uv run --no-project --python 3.13 python nvda-addon/build.py
```

The standard-library builder writes
`nvda-addon/dist/linuxRdAccess-20261013.0.2.nvda-addon`. It is reproducible and
includes Python source, documentation, attribution and the full upstream
license. `buildVars.py` is the source of add-on metadata; `--version` can override
the three-component numeric development version.

The four wire modules in
`linux_rdaccess_core/connection/nvda_test_client/` are the authoritative IPC
source for both the launcher and companion. The build packages those files
verbatim into the add-on. Do not create another copy in `addon/`.
The existing discovery filename and protocol remain compatible with the launcher
and previously reviewed RDAccess test endpoints.

## Install and migrate

Review the package and obtain explicit authorization before installing into a
running NVDA session or restarting NVDA during agent-assisted work.

1. Check whether the installed RDAccess build already provides **Authorize Linux
   test session** and Linux semantic braille. Development builds used for
   rdAccess PRs #10, #12 and #13 include this integration.
2. Disable that development add-on through NVDA's add-on manager before enabling
   the companion, or use a RDAccess build without the Linux integration.
   Disabling RDAccess also disables its RDP/Citrix features until it is re-enabled.
   Removing the legacy integration from rdAccess is a separate follow-up; this PR
   does not alter that repository or automatically uninstall an add-on.
3. Install the companion normally and restart NVDA after authorization.
   It deliberately remains inactive when a running RDAccess plugin owns the
   Linux integration. It waits until NVDA has initialized all plugins before
   checking, so add-on load order cannot create duplicate initial handlers.
4. Reconnect NVDA Remote Access normally if needed. Relay credentials stay in
   NVDA's UI. Existing settings are not migrated or changed by this add-on.
5. Authorize a **new** five-minute Linux test session in NVDA Tools. Consent is
   never carried across installation or restart. Follow
   [the authorized workflow](../docs/windows-test-session-stage2.md).

The existing [start-all launcher](../linux_rdaccess_test_session.py), saved SSH
configuration and Linux Orca session can be reused. No install step restarts
Orca or modifies the Linux desktop. Ordinary accessibility does not require AI
test consent; consent controls the local testing endpoint only.

## Develop and test

The standalone test package stubs NVDA runtime leaves and uses the real
`extensionPoints` and focus-context functions from the sibling `../nvda/source`
checkout. `NVDA_SOURCE_DIR` can point to another checkout. No rdAccess checkout,
running NVDA, relay credentials or Linux desktop is needed.

Run on Windows with Python 3.13, separately from the Linux tests:

```powershell
cd nvda-addon
uv run --no-project --python 3.13 --with configobj==5.0.9 python -m unittest discover -s tests -t .
```

The suite includes real Windows DPAPI/ACL/overlapped pipe tests using isolated
temporary endpoints. Those tests do not operate the active NVDA session.
CI builds and uploads the package and runs these tests on Windows. The normal
Linux test discovery does not import this separate test environment.

## Acceptance status

Build **20261013.0.2** is installed and active in Windows NVDA 2026.2;
its 13 installed Python files match the tested build.
Authenticated status, semantic negotiation and bounded Firefox Tab delivery
have been observed. One physical Firefox pan showed Linux content, but a later
left-pan report on build .1 with a Eurobraille b.note still showed a Windows
VS Code label. After reinstalling build .2, the user confirmed Linux content
after physical left pan in both Firefox and the Linux terminal. This is a
limited physical PASS; repeated/boundary panning, routing and complete
end-to-end acceptance remain incomplete.

Build **20261013.0.2** corrects two reproduced BrailleExtender interactions:
module-qualified focus-context lookup could add Windows ancestry to Linux
braille, and BrailleExtender's own pan scripts bypassed local semantic recovery.
These corrections are **Automated-tested**, and the user reinstalled the new
package. Physical left-pan observations showed Linux content; repeat control handoff,
speech, panning, routing, revocation, expiry and preservation of pre-existing
connections. Use the
[acceptance matrix](../docs/nvda-linux-compatibility-matrix.md); viewer output
alone is not physical-display proof.

Semantic focus uses NVDA formatting for braille. Speech currently forwards
Orca's generated wording, including role labels such as “push button”; it does
not yet provide NVDA-formatted semantic speech. Role wording and the reported
Tab/Shift+Tab announcement difference remain open under issue #58.

The 20261013.0.1 build also rejects action and caret requests retained from an
older semantic snapshot, session, or control activation, and refreshes ancestry
when the same focused object moves to another dialog or its context changes.
These corrections are automated-tested; see the
[issue audit and validation evidence](../docs/compatibility-audit-2026-10-13-companion.md).
An authenticated `nvda-status` response can come from the legacy RDAccess
integration: it does not prove that this companion is active. Check NVDA's log
for `Initialized Linux Remote Access Companion` or its inactive-conflict warning
before attributing live results to this package.

## License

This companion and extracted tests are **GPL-2.0-or-later**, independently of the
Linux project's Apache-2.0 code. Original RDAccess attribution and license notices
are preserved. See [NOTICE.md](NOTICE.md) for source revisions and extraction
details, and [COPYING.txt](COPYING.txt) for the full license.
