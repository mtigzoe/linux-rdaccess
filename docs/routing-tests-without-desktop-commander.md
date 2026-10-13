# Routing acceptance without Desktop Commander

Use the normal Windows NVDA Remote connection and the physical display. The
user operates the application and display; the agent only observes Linux
through SSH. Desktop Commander, Windows UI automation, keyboard injection,
clipboard access, relay changes and an NVDA/Orca restart are not required.
The tools below do not connect Remote Access or send input.

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
