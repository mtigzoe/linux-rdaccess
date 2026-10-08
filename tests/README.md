# Test suite

Run test commands from the **repository root**, not from inside `tests/`.

## Test directory layout

- `unit/accessibility/` — AT-SPI model, Orca integration logic, focus, and speech
- `unit/braille/` — braille protocol, display lifecycle, and routing
- `unit/input/` — keyboard commands, compatibility, and input tracing
- `unit/transport/` — bridge transport, controller lifecycle, and configuration
- `unit/windows/` — Windows controller and VS Code settings
- `integration/x11/` — X11 keyboard and desktop integration
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
Linux with Xvfb, uploads a test log even when it fails, and can be started
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


## Real Linux GUI accessibility tests in GitHub Actions

The dedicated `.github/workflows/linux-gui-accessibility.yml` workflow starts
a disposable Ubuntu Xvfb display and D-Bus session. It runs the existing GTK
controls/event smoke test plus a real-application AT-SPI smoke test for Thunar
and Mousepad. The test checks that application windows appear in the AT-SPI
tree; it does not need SSH, an active Linux Mint session, or NVDA credentials.

Run locally on Linux with the workflow dependencies installed:

```bash
timeout 180s python3 tools/diagnostics/gtk_atspi_smoke.py
timeout 100s dbus-run-session -- xvfb-run -a python3 tools/diagnostics/real_gui_atspi_smoke.py
```

These tests **do not** verify Windows NVDA speech, remote keyboard command
translation, or a physical braille display. Those still require a separate
NVDA Remote integration harness and live acceptance testing.
