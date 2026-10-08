# Remote SSH NVDA/Orca follow-up, October 8, 2026

Started from current `origin/main` at `019a94d` (PRs #26 and #27) with a clean
working tree. Commit `edbc363` was reviewed against the reorganized package:
its keyboard/transport helpers and accessibility model are already present
through PR #23 and the package move. No obsolete root implementation was
restored. Root modules remain compatibility imports.

The host is Linux Mint 21.3 with Python 3.10.12 and Orca 42. The restricted
execution environment hides host desktop processes; an authorized read-only
host check found the existing Orca and XFCE session on `:0`. Session discovery
provided its display, Xauthority and D-Bus variables. A read-only AT-SPI query
found 26 applications and a focused terminal, with a complete focus search.
No names or application text were printed. The active Orca session, relay,
braille settings and desktop were left intact. All input ran inside Xvfb.

## Reproduced defects and corrections

| Defect | Correction and regression evidence |
| --- | --- |
| A complete SSH environment with `DISPLAY=localhost:10.0` plus the systemd bus/runtime bypassed graphical discovery. An inherited accessibility-bus address could survive selection of another desktop. | Discover the local desktop for loopback-forwarded displays and replace the selected session variables together, including `AT_SPI_BUS_ADDRESS`. Regressions cover IPv4/IPv6 forwarding, desktop bus selection, and preservation when no desktop is available. |
| Live diagnostics returned focused ancestors or stale inactive-window controls before the actual keyboard target, and assumed the default display was `:0`. | Prefer focused descendants in active windows, bound traversal including provider cycles, and default to the discovered display. Explicit display mismatches remain errors. Diagnostic input tests verify Xvfb identity, including rejection of an active desktop at `:1`. |
| Re-executing the native braille forwarding hook could capture its own wrapper as the original refresh function, causing recursion or duplicate output. | Preserve the native refresh callable across customization reloads and upgrades. The v4 hook upgrades the exact v3 source while retaining strict validation and idempotency. Reload tests and loopback messages verify one native refresh and one forwarding result. |

No additional core keyboard mapping defect was reproduced. Existing regression
coverage exercises NVDA+Tab/T/F7/Space, Ctrl interruption, Desktop/Laptop
commands, Caps/Num Lock, keypad identity, modifier release and pass-next
behavior. Insert+Alt+Tab is a Windows Remote Access control toggle and still
requires acceptance with the Windows peer. Unsupported commands retain their
documented limitations.

## Automated environments

The GTK gallery now asserts Shift+Tab focus restoration, keyboard table-row
selection and names, and menu opening/Escape restoration in addition to its
existing roles, focus events, text/caret and modal-dialog checks.

The real-application runner owns a private Xvfb display, D-Bus session and
settings/cache/runtime directories. It clears inherited accessibility and
VS Code Remote CLI state before loading AT-SPI. Traversal distinguishes
equally named controls by proxy identity. Applications are required by default;
explicit `--skip` options are reported and do not count as passing coverage.
The GUI workflow supplies all seven desktop applications.

| Application | Behavior asserted |
| --- | --- |
| XFCE Settings Manager | Named search field, Tab/Shift+Tab focus and event delivery, text edits and caret navigation. |
| Thunar | Location-bar focus/text, named fixture files, keyboard changes to table selection. |
| Mousepad | Editor text/caret, window switching, Open dialog, Tab/Shift+Tab and Escape focus restoration. |
| XFCE Terminal | Shell output in the terminal text interface, menus and focus restoration. |
| XFCE clock/calendar | Named clock, calendar popup focus and dismissal; provider limitations below. |
| Firefox | Labelled document input, text/caret, Tab/Shift+Tab, location-bar focus and restoration. |
| VS Code | Accessible command-palette input, query/result list and editor focus restoration using a separate desktop installation. |

The installed XFCE clock toggle advertises an AT-SPI click action but cannot
take keyboard focus, and that action did not open its popup. The private test
uses a pointer click to inspect the popup. Its GtkCalendar provider exposes
no Text, Table, Selection or Value interface and no date-cell children, so
arrow-driven date selection cannot be asserted through AT-SPI. These are
reported as limitations, not verified date-navigation support.

Remote SSH places its Code CLI first in PATH even when the desktop editor is
installed. Discovery now checks the desktop installation independently of PATH
and launches its native executable in an owned process group. Both local and
CI runs use temporary user-data and extension directories. The Remote CLI is
rejected instead of opening the user's active editor. An explicit
`--skip vscode` remains available on machines without a desktop installation.
An initial native Code startup opened the existing shared-storage database
before that additional storage path was identified. The final invocation
also supplies private shared-data and agent directories and avoids keyring
prompts. It verifies ownership of the private D-Bus daemon before setting
screen-reader status, which Electron needs to export its accessibility tree.
Code's command palette reports focus on its active result rather than its
text input; the test checks that result and the input's actual typed text.

The loopback protocol harness uses the production patcher, pinned relay source,
real TCP stream and native sender/reconnector threads. A test callback manager
and protocol-v2 JSON serializer dispatch messages; the TLS socket factory and
external Orca services are replaced. It tests keyboard/modifier
delivery, connection handshakes, ordered speech/cancellation, raw-cell fallback,
semantic braille/focus/actions, stale callback rejection, malformed frames,
reconnect and thread cleanup. No user's relay credentials are loaded.

## Reproduction and acceptance boundary

```sh
python3 -m compileall -q linux_rdaccess_core diagnostics tools tests
env -u DISPLAY -u WAYLAND_DISPLAY python3 -m unittest discover -s tests -t .
xvfb-run -a python3 -m unittest discover -s tests -t .
python3 tools/diagnostics/gtk_atspi_smoke.py
dbus-run-session -- xvfb-run -a python3 tools/diagnostics/real_gui_atspi_smoke.py
python3 -m unittest -v tests.integration.test_nvda_remote_loopback
```

The loopback peer does not verify TLS, Windows NVDA's synthesizer/add-on, or
physical braille hardware. Existing native Liblouis tests check cell alignment,
40/80-cell panning and routing contracts; they are software checks. Audible
speech ordering/pacing, Windows command consumption/control toggling, physical
display translation and routing, and a real reconnect remain live acceptance
tasks. Use the existing compatibility matrix and live acceptance checklist
with explicit authorization before injecting input into the user's desktop.

## Validation on Linux Mint

| Check | Result |
| --- | --- |
| Full Python 3.10 suite, headless | 1,183 tests run; 18 expected private-X11 skips; passed. |
| Full Python 3.10 suite, private Xvfb | 1,183 tests passed; no skips. |
| GTK gallery | 38 accessibility/keyboard checks passed. |
| All seven real applications, private Xvfb/D-Bus | 43 checks passed; 220 AT-SPI events; no skips. |
| GUI runner isolation and traversal | Seven regression tests passed. |
| Loopback protocol and braille hook reload regressions | 15 tests passed. |
| Compileall, Python 3.10 grammar, shell syntax, diff whitespace | Passed; 132 Python files checked. |

The full-suite totals include the focused regression tests. The GUI workflow
also runs strict desktop Firefox and Code checks; its result must be recorded
separately from these local tests.
