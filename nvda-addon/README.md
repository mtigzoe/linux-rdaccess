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
  service supporting `status`, `connect` using saved settings, `cancel`, and
  separately opted-in, read-only `braille_trace` diagnostics.
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
`nvda-addon/dist/linuxRdAccess-20261014.0.3.nvda-addon`. It is reproducible and
includes Python source, documentation, attribution and the full upstream
license. `buildVars.py` is the source of add-on metadata; `--version` can override
the three-component numeric development version.

The five wire/diagnostic modules in
`linux_rdaccess_core/connection/nvda_test_client/` are the authoritative IPC
source for both the launcher and companion. The build packages those files
verbatim into the add-on. Do not create another copy in `addon/`.
The existing discovery filename and protocol remain compatible with the launcher
and previously reviewed RDAccess test endpoints for version 1 operations.
The legacy diagnostic read uses an argument-free version 2 operation; older
endpoints reject it, and the launcher reports unavailable/unsupported after a
read-only status check.
Build **20261014.0.1** adds the argument-free version 3 `braille_outcomes` read,
available as `nvda-braille-outcomes`. Versions 1 and 2 are unchanged. The same
unchecked diagnostics checkbox enables two independent ledgers of at most
twelve records each; each ledger discloses its own drops and clears with consent.

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

Build **20261014.0.3** binds queued native document-routing presses to their
original semantic snapshot, control activation and braille handler. If focus,
text, control, session, handler or the visible message buffer changes before
execution, the old press is discarded. Fresh presses still use NVDA's native
script and gesture execution pipeline, including input help and capture.
This is automated-tested; it does not establish physical routing acceptance
or explain the historical 6→9 movement. See the
[queued routing audit](../docs/compatibility-audit-2026-10-14-queued-main-routing.md).
This review candidate is based on merged main; it does not include the separate,
unmerged PR #89 one-shot automation. It has not been installed or deployed.

Build **20261014.0.1** adds diagnostics only: stock out-of-buffer no-ops,
activation/caret attempts, send return/failure, message dismissal, discarded
message routes and unknown outcomes. It does not change routing policy.
The package is prepared for review, **not installed or physically accepted**.
Linux reason logging separately requires controller v121 and the updated adapter,
model and diagnostic helper. See the
[outcome audit and single-gesture test](../docs/compatibility-audit-2026-10-14-routing-outcomes.md).

Build **20261013.0.6** retained .5's guarded queued-message routing and added an
unchecked **Record numeric braille routing diagnostics (no text)** consent
option. It records at most twelve in-memory routing/message events and clears
them at the consent boundary. Read with `nvda-braille-trace`; this command cannot
enable collection or send input. The user installed .6; its fourteen packaged
Python files matched disk in the earlier follow-up. Its mixed navigation trace
does not establish isolated routing or message acceptance. See the
[follow-up audit](../docs/compatibility-audit-2026-10-13-caret-trace.md).

The user installed **20261013.0.5**; all thirteen packaged Python files matched
the installed files. A user-confirmed, isolated input-help entry retained Linux
caret 20. Two later tests included extra navigation and cannot isolate routing.
A simplified two-press test reported visible-message dismissal and recorded
20 to 7 after the prompt. Its cause, and the original .4 movement from 6 to 9,
remain unconfirmed. Keep #59 and #72 open.

Build **20261013.0.4** repairs Linux focus underneath a displayed Linux status
message and restores that focus on native message dismissal if Windows replaced
the main buffer while the message was visible. Recovery requires the current
remote session/control generation and does not take ownership of later Windows
messages. Retained same-ID regions must match the current snapshot object.
Disabled messages and speech-only mode stay under NVDA's native policy.
This correction is **automated-tested**. The user later confirmed message
appearance and timeout restoration in Mousepad; routing/caret acceptance remains
incomplete. The initial preparation is described in
the [message restoration audit](../docs/compatibility-audit-2026-10-13-message-restoration.md).

Build **20261013.0.3** refreshes NVDA's pending semantic braille update before
a queued local coordinate gesture. A same-ID snapshot could otherwise replace
the object while its cached reading TextInfo still belonged to the invalidated
snapshot, silently dropping a routing caret request. The new regression fails
before the fix and passes with it, including an isolated run of the installed
NVDA 2026.2 update bytecode. Old retained TextInfo remains invalid; local control,
stale sessions, disconnection and temporary-message buffers skip this refresh.
The .3 build is installed on disk and its 13 Python files match the package;
the running version at that check and physical routing retest were unverified. See
the [routing audit](../docs/compatibility-audit-2026-10-13-pending-braille-routing.md).

Build **20261013.0.2** was installed and active in Windows NVDA 2026.2;
its 13 installed Python files matched the tested build at that check.
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
