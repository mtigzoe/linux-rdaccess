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
