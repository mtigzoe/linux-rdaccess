# Scripted NVDA message routing with SSH observation

This command removes the need for a human routing press during **software**
checks of #72. Linux SSH alone cannot press a Windows NVDA braille button.
The Windows Python coordinator observes Linux over SSH and calls a narrowly
scoped Windows companion operation through its authenticated local pipe.
No Windows SSH server or network listener is added.

The command enters the companion's ownership-guarded message-routing queue,
then NVDA's native message route/dismissal code. It bypasses the physical
button, driver mapping and global `inputCore` gesture deciders. It cannot
reproduce every physical-driver or other-add-on interception path, certify
device output, explain the historical 6→9 movement by itself, or close #59/#72.

## Review and setup

1. Review the forward-ported companion candidate **20261014.0.4** (preserves .3 safeguards; not installed). Obtain explicit authorization
   before installing it or restarting NVDA. The previous .1 installation and
   previous test grants do not authorize this installation or new input scope.
   No Linux runtime installation or Orca restart is required.
2. Prepare the existing public Mousepad editor, finish navigation and verify its
   focus/caret. Use the normal existing Remote Access connection, then return
   to local Windows control before granting consent or starting the recorder.
   The agent can handle the previously approved setup keys after arming.
   Do not type, pan or route during the recording.
3. Manually authorize a fresh five-minute session in NVDA Tools and select the
   new **Allow one simulated routing press on a Linux message (records numeric
   diagnostics)** checkbox. It is unchecked by default. This permission also
   enables the two numeric ledgers. Status/diagnostic consent alone is read-only
   and cannot authorize a simulated press. No consent renewal is automated.
4. Start the coordinator from Windows, with the absolute path of the reviewed
   existing `observe_routing.py` on Linux:

   ```powershell
   python diagnostics/nvda/simulate_message_routing.py --execute --ssh-host cyber --observer-path /path/to/linux-rdaccess/diagnostics/atspi/observe_routing.py
   ```

5. Wait in local Windows control for `linux_observer: ready` and `recorder: armed`.
   Then the agent can use the approved handoff and NVDA+1 setup gestures to
   create a new Linux temporary message immediately. The script watches for a
   **new**, Linux-owned message with active Linux control for up to
   30 seconds and routes its first cell automatically. The user does not press
   any routing key. The observer runs for 45 seconds; no indefinite-message
   setting or timed human response is needed.
6. Read the final numeric Windows/Linux report, then use the approved normal
   shortcut to return to local control. A `queued` response is only acceptance
   into the guarded queue, not successful dismissal. The coordinator reports
   a software `pass` only with logical dismissal, no observed remote caret/action
   attempt, unchanged Linux caret/focus and complete diagnostic windows.
   Both Windows ledgers are read again after the Linux observer finishes; the
   early queue snapshots are retained separately as `*_after_dispatch`.
   A Windows final timestamp must cover the Linux observation. Missing/dropped
   evidence is inconclusive. Movement away and back is a failure.
   Physical braille remains `unverified` regardless of software outcome.

The one-shot permission is consumed before the first attempt, including refusal
or an ambiguous failure. There is no automatic retry. If a message expires or is
replaced after queueing, the guard discards the route rather than applying it to
the replacement or main document. Expiry, revocation, lock, secure desktop,
profile changes and shutdown also prevent pending scripted routes. Capture,
NVDA input help, custom message regions and legacy remote-client paths are
refused. Only stock NVDA text-message regions are eligible for simulation.

For a message already visible, the lower-level Windows command is:

```powershell
python linux_rdaccess_test_session.py nvda-route-message
```

It has the same independent one-shot permission and no cell-index argument.
It does not create a message, change focus, connect Remote Access, alter settings
or send keyboard/text input. Its version 4 wire schema is documented in the
[test-session workflow](windows-test-session-stage2.md#optional-one-shot-simulated-message-route-2026101402).

## Validation scope

The companion suite exercises authentication, same-user Windows named pipes,
DPAPI, GUI dispatch, default-denied/one-shot permissions, revocation and native
message lifetime contracts in isolated endpoints/harnesses. Source-backed
tests execute selected NVDA 2026.2 message methods with fake display/transport
providers. Coordinator tests simulate status/trace replies and verify one
request at most, no reuse of old messages, unknown-on-timeout behavior and
private-field filtering. These tests do not run the installed NVDA process.

This is test automation requested for the investigation, not a newly claimed
fix for a reproduced production routing defect. Keep #57/#72's remaining
acceptance criteria and independent #59 physical routing open.

Validation on 2026-10-14 (groups overlap):

- Windows Python 3.13.13 companion suite: **346 passed**, zero failures/errors/skips.
  NVDA reference `1406f9f8a04eb50f7317af87aba3a9d439c2a772`; native methods run in
  an isolated fake-display/transport harness, with real Windows kernel pipe,
  DPAPI, DACL and cancellation tests.
- The eight scripted message-route tests also passed against NVDA 2026.2
  reference `f62c980589d1ac30babf68ad48177e9ad29a2e84`, zero failures/errors/skips.
- Coordinator/launcher tests: **35 passed** on Windows Python 3.13.13 and
  separately **35 passed** on WSL Ubuntu 22.04.5/Python 3.10.12, zero
  failures/errors/skips. These use simulated SSH/IPC evidence; no live route.
- Companion Ruff lint/format, shared wire-module lint, package reproducibility,
  packaged standalone imports/AST parsing and diff checks passed.

Exact commands (run the companion commands from `nvda-addon`; the local env
files contain only `NVDA_SOURCE_DIR` pointing to the pinned reference checkouts):

```text
uv run --no-project --python 3.13 --with configobj --env-file ../tmp/braille-routing-outcomes/ci.env python -B -m unittest discover -s tests -t .
uv run --no-project --python 3.13 --with configobj --env-file ../tmp/braille-routing-outcomes/test.env python -B -m unittest -q tests.test_scriptedMessageRouting

# Repository root, run once with Windows Python and once with WSL Python 3.10:
python -B -m unittest -q tests.unit.test_routing_automation tests.unit.test_windows_test_session
uv run --no-project --with ruff ruff check nvda-addon
uv run --no-project --with ruff ruff format --check nvda-addon
uv run --no-project --with ruff ruff check --config nvda-addon/ruff.toml linux_rdaccess_core/connection/nvda_test_client/localTestTransport.py
python nvda-addon/build.py
git diff --check
```

Review artifact: `nvda-addon/dist/linuxRdAccess-20261014.0.2.nvda-addon`, SHA-256
`7bfc7d84dc802fa26c0a7b344df684b3257c3e25e80e9644dac3482c98513d93`.
The user subsequently reported installing this package and restarting NVDA.
All **17** installed code/manifest files match the reviewed archive. This is
an on-disk comparison, not attestation of every loaded module. Installation and
the one-shot routing grant remain separate decisions. CI is not polled or awaited.

## First live preparation attempt

Fresh status showed authorization active, transport connected, the bridge
attached and semantic/message support negotiated. The agent used the approved
Computer Use handoff at **22:37:43.623–22:37:43.929 UTC**, and status changed from
local to Linux control. The Linux observer became ready at caret **0**.

The coordinator stopped **before arming** because the ledgers had already
filled. Immediate numeric reads showed trace drops **18** and outcome drops
**3**. Retained entries include caret/routing activity; their input origin is
not attributed to the coordinator. It never reached its version 4 route request,
and the agent never sent NVDA+1. No message-dismissal or caret-preservation PASS
is claimed from this attempt.

Computer Use rejected a return-to-local shortcut and its one refreshed retry
because it detected concurrent user input. Follow-up status still showed Linux
control active. The user was asked for one manual handoff; no further automated
input was sent. The Python coordinator now arms while Windows remains local,
then waits for a new message with Linux control active. Preflight refusals are
also reported as `not_sent`, rather than the previous conservative `unknown`.
This is a local Python workflow change; no new add-on or restart is required.

## Scripted route and recorder timing correction

The next grant armed successfully while Windows was local. Approved setup
shortcuts enabled Linux control and created a new message. At
**22:49:08.984 UTC**, the coordinator made exactly one version 4, cell-0
request. The companion accepted it and recorded `route_guarded` followed by
Linux-owned `message_dismissed`. Its immediate snapshots had no drops or
caret/action attempts. The 45-second Linux observer reported caret **27 → 27**,
no caret events, no focus change and zero dropped events.

The old coordinator emitted `pass`, but a subsequent Windows read showed
additional caret/routing activity and **25 trace drops**. Outcomes include a
same-offset caret attempt after the early snapshot; the activity's source has
not been established. The whole trial is therefore **inconclusive**. The
immediate guarded dismissal is evidence of that software operation, not a
clean full-window or physical acceptance result. The Windows test surface
also changed from 0 to 2 characters during handoff, with source unestablished;
no `type_text` action was used and its contents were left intact.

This revealed a confirmed recorder defect: Windows outcomes were read only
about 0.3 seconds after queueing, before the Linux observer finished. Three
regressions reproduced false PASS results for early snapshots, later caret
attempts and later overflow. The coordinator now reads both Windows ledgers
after the observer completes, preserves early snapshots separately, and
requires final Windows evidence to cover the Linux interval. The fix passed
the 35 focused tests on each platform; it has not yet had a new live trial.
No new companion installation or restart is needed.

Computer Use blocked the return-to-local shortcut and one refreshed retry
because it detected input. Status remained Linux-active, so a manual handoff
was requested and automated input stopped. Sanitized numeric evidence is in
[`scripted-message-routing-live-evidence-2026-10-14.json`](scripted-message-routing-live-evidence-2026-10-14.json).
The simulation bypasses the physical driver/global gesture deciders; #57/#72
remain NOT READY, and the historical 6→9 movement and #59 remain unresolved.
