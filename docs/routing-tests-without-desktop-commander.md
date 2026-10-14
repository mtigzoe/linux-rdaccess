# Routing acceptance without Desktop Commander

For physical acceptance, use the normal Windows NVDA Remote connection and the
physical display. The user operates the application and display while the
agent observes Linux through SSH. Desktop Commander, Windows UI automation,
keyboard injection, clipboard access, relay changes and an NVDA/Orca restart
are not required. The physical-test observer does not send input. The separate
[simulation commands](#simulate-one-linux-caret-route-over-ssh) below exercise
Linux caret behavior without establishing physical acceptance.

## Prepare one public test

1. Start/reconnect Windows NVDA normally if needed. Record the NVDA, companion,
   Orca and Linux revision, plus display model/driver/firmware when known.
2. If an agent will use the authenticated Windows status endpoint, authorize a
   fresh five-minute Linux test session in NVDA Tools. Verify authorization,
   connected transport, active remote control and negotiated semantic braille:
   `python linux_rdaccess_test_session.py nvda-status`.
   This status/connection consent does not grant unrestricted desktop input.
3. In Linux Mousepad, open a new unsaved document and type
   `alpha bravo charlie`. Leave the caret at the end. Do not use a private
   document or a shell prompt as the first caret-routing fixture.
4. Start the observer before the user presses the display key. From a Linux
   checkout, including over SSH:

   ```sh
   python3 diagnostics/atspi/observe_routing.py --application mousepad --duration 30
   ```

   The observer discovers the existing X11 session using the project's session
   helper. It reuses the existing focused-object probe, checks the requested
   application, and refuses a focus without a readable text caret. It does not
   activate windows, launch an application, change focus or move the caret.
5. Wait for the JSON `observer: ready` record. Ask the user to press just the
   physical routing key under the `b` in `bravo`, keeping the keyboard idle.
   In this known text, `b` has zero-based character offset **6**. Record the
   actual targeted cell and translation mode if a contraction makes the target
   ambiguous; do not reinterpret an ambiguous cell as a successful offset 6.
6. Compare initial/final caret, request-relative event times and focus
   continuity. Ask the user separately whether the b.note cursor/content now
   matches the intended Linux text. A Linux caret event alone cannot certify
   physical braille or Windows NVDA output.

The observer runs for 1–60 seconds, caps its recorded event list at 64, and
discloses dropped events. It retains only numeric caret offsets, elapsed times,
a requested application category, role and focus-continuity flags. It does not
serialize accessible names, editor text, event text, provider exception details
or bus/relay credentials. Password caret providers are not queried. Once focus
changes, later caret events are excluded even if the initial object returns.
Interrupting the process unregisters its listeners and timer.

If consent expires, stop agent input and status-dependent actions and obtain
fresh consent before another controlled test. The observer is read-only and
does not extend, replace or bypass NVDA consent. User-operated gestures must be
recorded as such; the observer does not establish their input origin.

## Repeat only after inspecting the result

Use `--application firefox` for an existing focused editor in the public
`tests/fixtures/firefox-acceptance.html` page. Have the user put the same known
text into its single-line editor before repeating the single routing gesture.
Do not open/reload the user's browser automatically.

`--application terminal` supports the existing GNOME/ XFCE terminal providers
when they expose a readable caret. Terminal accessibility text often includes
scrollback and prompt/output rather than an ordinary editable document. A
numeric terminal caret does not establish that arbitrary routing is supported;
test that separately and never send a route into an unknown shell command.

For temporary-message restoration, retain the original focus/caret and braille
window, have the user trigger one known Orca status message, then observe its
dismissal and ask whether the original Linux line/cursor returns. The Linux
observer does not capture message text or prove that NVDA displayed/dismissed
the message. Keep issue #72's separate pan, routing-dismissal, timeout,
local-control and reconnect checks open until directly observed.

## Record each layer separately

On Windows, the existing offline acceptance CLI now also offers a report for
one interaction:

```powershell
python .\linux_rdaccess_acceptance.py session-template > routing-session.json
python .\linux_rdaccess_acceptance.py session-summary --file routing-session.json
```

Keep the original `template` / `summary` commands and existing schema-1
acceptance matrix for the overall checklist. The new report is a different
`kind`, `single-interaction-layered-evidence`, and cannot be substituted for
that checklist. There is no automatic issue closure or general compatibility
PASS in its summary.

Fill in `context` and the separately observed `session` facts, then each of the
five `layers`: `keyboard_delivery`, `linux_focus`, `nvda_speech`,
`semantic_braille`, and `physical_braille`. For a routing-only interaction,
keyboard delivery may be `not-tested`. A `pass`/`fail` needs application,
gesture, expected behavior, an observation and a compatible source. For
example, Linux caret readback can substantiate only `linux_focus`;
`remote-protocol` can describe semantic events without certifying a display;
`windows-nvda` speech events are separate from audible user confirmation.

Physical output requires an explicit `user-confirmation` source. Mark isolated
GUI/unit evidence `isolated-test`. Unobserved layers remain `unverified` or
`not-tested`; a connected session does not fill them automatically. These are
declared evidence labels, not cryptographic verification of a report's author.
Do not include private text, passwords, relay keys or raw logs. Keep reports
with user content local; publish only sanitized, consented fixture evidence.

## Simulate one Linux caret route over SSH

For repeatable Linux routing diagnostics without coordinating physical keys,
run the private fixture script from a Linux checkout:

```sh
python3 tools/diagnostics/run_routing_simulation.py
```

It also works over SSH, for example:

```sh
ssh cyber python3 /path/to/linux-rdaccess/tools/diagnostics/run_routing_simulation.py
```

Replace the checkout path with the reviewed checkout on that host. The script
creates its own Xvfb display, D-Bus session and public GTK fixture. It verifies
session ownership, previews the target without writing, moves the caret from
2 to 7, checks a target caret event and readback, and rejects reuse of the stale
preview. It needs Python GI/GTK3/AT-SPI, Xvfb, xauth, dbus-run-session, xfwm4
and xdotool. It needs no NVDA consent, physical gesture, installation, restart,
existing editor focus or change to the active desktop.

For an **explicitly approved live caret change**, the separate command below
targets only an already focused Mousepad text area. It does not focus a window,
type, launch an application, or connect Remote Access. Its default is a preview:

```sh
python3 diagnostics/atspi/simulate_routing.py --offset 6
```

The preview returns the PID, current caret and character count. Copy those
numbers into the guarded apply command; these example values are illustrative:

```sh
python3 diagnostics/atspi/simulate_routing.py --offset 6 --apply \
  --expect-pid 1234 --expect-caret 19 --expect-count 19
```

Offsets are zero-based **characters**, not braille cells. An apply makes at
most one call to the same `a11y_model.set_caret_offset` helper used by semantic
routing. The event observer is ready first. Immediately before writing, the
command rechecks identity within that invocation, PID, caret, length and absence
of a selection. PID and counters alone do not identify a document across
separate previews; use only the approved public target and keep it focused.
Password fields, terminals, noneditable targets, invalid offsets, mismatches
and detected focus changes are refused. There are no automatic retries or restoration
writes. A provider return and a matching readback are reported separately.
Output contains numeric target/event data and fixed labels, without document
text or accessible labels. Exceptions are redacted; an interrupted/failed
command may have written already, so preview again before deciding a next step.
The `gtk-fixture` application category is for the repository's public
`tests/apps/accessibility_smoke_app.py`, used by the private test runner.

This simulation bypasses Windows NVDA, the relay, Orca's running controller,
semantic object/session checks and braille-cell translation. It cannot establish
temporary-message dismissal, device output or input origin, and it cannot
explain the historical 6→9 movement by itself. Keep #59 and #72's physical
acceptance open. Windows message-routing behavior can be exercised separately
by the companion's existing unit tests; do not add an arbitrary-input operation
to the five-minute status endpoint to simulate a physical gesture.

Validation on 2026-10-14:

```sh
# Windows, Python 3.13.13: 27 passed, 0 failures/errors/skips.
python -B -m unittest -v tests.unit.test_routing_simulator tests.unit.test_routing_observer
# WSL Ubuntu 22.04, Python 3.10.12: 1 native test passed, 0 failures/errors/skips.
python3 -B tools/diagnostics/run_routing_simulation.py
```

The unit tests use fake providers/event loops with the real caret helper. The
native test runs the actual command-line preview/apply/refusal against a GTK3
AT-SPI provider in its private desktop: caret 2→7, matching event/readback,
same focus, no dropped events. Neither result is a live NVDA, running Orca or
b.note acceptance result. No live Mousepad route was sent for this validation.

## Automated observer validation

The native integration test reuses the existing GUI runner's Xvfb, disposable
profile and private verified D-Bus session. Run it from a Linux checkout:

```sh
python3 - <<'PY'
import subprocess
import tempfile
from pathlib import Path
from tools.diagnostics.real_gui_atspi_smoke import isolated_environment

with tempfile.TemporaryDirectory(prefix="lrd-routing-private-") as private:
    result = subprocess.run(
        ["xvfb-run", "-a", "-s", "-screen 0 1280x900x24",
         "dbus-run-session", "--", "python3", "-m", "unittest", "-v",
         "tests.integration.x11.test_routing_observer"],
        env=isolated_environment(Path(private)), timeout=60,
    )
    raise SystemExit(result.returncode)
PY
```

The test verifies the Xvfb process and D-Bus daemon ownership before launching
Mousepad or moving its fixture caret with a direct AT-SPI action. That action
is an isolated test stimulus, not NVDA-origin input or a physical routing key.
The observer must capture offset 2 → 7 on the same object. Ordinary unittest
discovery skips this test outside the runner's private environment.
