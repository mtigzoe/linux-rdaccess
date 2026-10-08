# Test suite

Run test commands from the **repository root**, not from inside `tests/`.

## Test directory layout

- `unit/accessibility/` — AT-SPI model, Orca integration logic, focus, and speech
- `unit/braille/` — braille protocol, display lifecycle, and routing
- `unit/input/` — keyboard commands, compatibility, and input tracing
- `unit/transport/` — bridge transport, controller lifecycle, and configuration
- `unit/windows/` — Windows controller and VS Code settings
- `integration/x11/` — X11 keyboard and desktop integration
- `integration/test_nvda_remote_loopback.py` — NVDA Remote messages and lifecycle over a disposable loopback relay
- `shared/` — reusable test harnesses (`test_remote_access.py`, `test_compat_lifecycle.py`)
- `fixtures/` — reusable test data
- `apps/` — accessibility smoke-test applications

## Windows PowerShell: controller tests

The complete test suite targets Linux and **is not expected to pass on native Windows**.
Run the focused Windows controller tests instead:

```powershell
uv run --no-project python -m unittest tests.unit.windows.test_windows_controller
```

## Linux: full suite

Use `uv` from the repository root:

```bash
uv run --no-project python -m unittest discover -s tests -t .
```

For X11 integration coverage, use Xvfb when it is installed:

```bash
xvfb-run -a uv run --no-project python -m unittest discover -s tests -t .
```

Run one test module directly, for example:

```bash
uv run --no-project python -m unittest tests.unit.braille.test_braille_link
```

Some tests depend on Linux-specific system packages, including X11 libraries
and AT-SPI/Orca bindings. Check the GitHub Actions workflow for the CI environment.

## GitHub Actions

[Full unittest suite with uv](../.github/workflows/uv-unittest.yml) runs the suite on
Linux both headless and with Xvfb, checks Windows entry points, uploads a test log even when it fails, and can be started
manually from the GitHub Actions page.

[Remote A11Y prototype tests](../.github/workflows/remote-a11y-tests.yml) also
checks Linux producer behavior and the rdAccess semantic contract.

## Moving or adding tests

Keep `__init__.py` in each importable test package and update cross-test
imports, relative fixture paths, and CI references when moving tests.
See [repository organization](../docs/repository-organization.md).

## Installed Linux command acceptance (no live connection)

GitHub Actions runs a focused acceptance test against a temporary copy of the
installed runtime. It checks `status`, `doctor`, `connect --no-restart`,
and `disconnect --no-restart` with deliberately missing configuration. These
checks verify safe failure paths without starting Orca, changing the user's
configuration, or using an NVDA Remote relay. A second acceptance case uses
synthetic credentials and a disposable Orca customization file to test
successful `connect --no-restart` and `disconnect --no-restart`, including
secret redaction and preserving the saved private config.

Run the same test locally from the repository root:

```bash
python3 -m unittest -v tests.unit.transport.test_installed_runtime_acceptance
```

The real Linux Mint installation and connected Windows NVDA/braille acceptance
still require a live desktop and hardware. Passing this suite alone does not
establish that Remote Access speech and braille work end to end.

Acceptance also invokes the actual `install` command in a private home,
reinstalls from the installed bundle, forwards `configure` options, verifies
private file modes and key redaction, and checks launcher paths containing
quotes and dollar signs. Package import tests run without root compatibility
files. Orca fixture tests load only the renamed standalone adapter and model.

Run keyboard injection tests under Xvfb; they refuse a regular desktop display.
For a headless run on a host that exports a desktop display, use:

```bash
env -u DISPLAY -u WAYLAND_DISPLAY python3 -m unittest discover -s tests -t .
```


## Real Linux GUI accessibility tests in GitHub Actions

The dedicated `.github/workflows/linux-gui-accessibility.yml` workflow starts
a disposable Ubuntu Xvfb display and D-Bus session. It runs the GTK gallery
and real applications: XFCE Settings Manager, Thunar, Mousepad, XFCE Terminal,
the XFCE clock/calendar, Firefox, and desktop VS Code. Assertions cover
keyboard focus and events, text/caret changes, file selection, dialogs,
menus, and focus restoration. No SSH session or NVDA credentials are needed.

Run locally on Linux with the workflow dependencies installed:

```bash
timeout 180s python3 tools/diagnostics/gtk_atspi_smoke.py
timeout 300s dbus-run-session -- xvfb-run -a python3 tools/diagnostics/real_gui_atspi_smoke.py
```

The real-application runner also creates its own isolated display and bus when
called directly. An unavailable application fails by default. Use an explicit
`--skip vscode` locally when only VS Code's Remote SSH CLI is installed; that
CLI cannot be used as the Linux desktop editor. CI requires every application.
An explicit skip is reported in the result and is not accessibility evidence.

## Isolated NVDA Remote protocol integration

```bash
python3 -m unittest -v tests.integration.test_nvda_remote_loopback
```

This suite is included in standard discovery. It runs the production-patched
Orca Remote transport against a disposable TCP peer bound to `127.0.0.1` with
an ephemeral port and a test-only channel. It checks handshakes, framing,
keyboard/modifier delivery, ordered speech and cancellation, raw and semantic
braille messages, focus/action contracts, reconnects, errors, and cleanup.
The test replaces TLS with a local socket and uses doubles for Orca services.
It never reads the user's relay configuration.

GUI and protocol tests **do not** establish audible Windows NVDA speech or
physical braille display behavior. Live acceptance must verify remote control
toggle, actual NVDA command consumption, speech pacing, device translation,
panning/routing, and focus/caret synchronization using the real Windows peer.


## Dedicated NVDA Remote loopback CI

The [NVDA Remote loopback workflow](../.github/workflows/nvda-remote-loopback.yml)
executes the existing disposable TCP relay integration suite independently on
Python 3.10 and 3.12. It exercises fragmented messages, modifier release,
reconnection, speech cancellation and ordering, native semantic/raw braille,
routing/panning messages, and controller cleanup. Logs are saved as CI artifacts.

Run the same suite locally without accessing the active desktop or relay:

```bash
python3 -m unittest -v tests.integration.test_nvda_remote_loopback
```

This is **not** a Windows NVDA session test or a physical braille-display test.
The harness uses synthetic credentials and loopback sockets only; live NVDA
speech/braille acceptance remains necessary. Do not connect CI to the user's
production relay or running Orca instance.
