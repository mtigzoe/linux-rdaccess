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

1. Review companion candidate **20261014.0.2**. Obtain explicit authorization
   before installing it or restarting NVDA. The previous .1 installation and
   previous test grants do not authorize this installation or new input scope.
   No Linux runtime installation or Orca restart is required.
2. Prepare the existing public Mousepad editor, finish navigation and verify its
   focus/caret. Use the normal existing Remote Access connection and active
   Linux control. The previously approved Windows setup keys can be handled by
   the agent. Do not type, pan or route during the recording.
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

5. Wait for `linux_observer: ready` and `recorder: armed` before creating a new
   Linux temporary message. The agent can use the already approved NVDA+1 setup
   gesture. The script watches for a **new**, Linux-owned message for up to
   30 seconds and routes its first cell automatically. The user does not press
   any routing key. The observer runs for 45 seconds; no indefinite-message
   setting or timed human response is needed.
6. Read the final numeric Windows/Linux report, then use the approved normal
   shortcut to return to local control. A `queued` response is only acceptance
   into the guarded queue, not successful dismissal. The coordinator reports
   a software `pass` only with logical dismissal, no observed remote caret/action
   attempt, unchanged Linux caret/focus and complete diagnostic windows.
   Missing/dropped evidence is inconclusive. Movement away and back is a failure.
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
fix for a reproduced production routing defect. The new build has not been
installed or run against the live Windows–Linux session. Keep #57/#72's remaining
acceptance criteria and independent #59 physical routing open.

Validation on 2026-10-14 (groups overlap):

- Windows Python 3.13.13 companion suite: **346 passed**, zero failures/errors/skips.
  NVDA reference `1406f9f8a04eb50f7317af87aba3a9d439c2a772`; native methods run in
  an isolated fake-display/transport harness, with real Windows kernel pipe,
  DPAPI, DACL and cancellation tests.
- The eight scripted message-route tests also passed against NVDA 2026.2
  reference `f62c980589d1ac30babf68ad48177e9ad29a2e84`, zero failures/errors/skips.
- Coordinator/launcher tests: **29 passed** on Windows Python 3.13.13 and
  separately **29 passed** on WSL Ubuntu 22.04.5/Python 3.10.12, zero
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
It is not installed; running NVDA and the active Linux desktop were not changed
for these tests. Installation/restart and the new routing permission remain
separate user decisions. CI results are not polled or awaited.
