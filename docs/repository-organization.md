# Repository organization

The reorganization is deliberately incremental. Production entry points and Linux
installer paths remain at the repository root until their import, install and
runtime contracts can be validated.

## Test layout

- `tests/unit/windows/`: Windows SSH controller and VS Code settings tests
- `tests/unit/accessibility/`: accessibility links, Orca adapter and browser/speech tests
- `tests/unit/braille/`: braille link, bridge and protocol unit tests
- `tests/unit/input/`: keyboard validation and compatibility hardening tests
- `tests/unit/transport/`: sockets, DVC, polling, receivers and state tests
- `tests/integration/x11/`: live X11 tests; additional integration groups are planned
- `tests/apps/` and `tests/fixtures/`: existing reusable applications and data

Test moves must be made in batches. Each batch must preserve package import
paths, relative source/fixture lookups, commands in documentation and CI,
and total test discovery counts.

From the repository root:

```sh
python3 -m unittest discover -s tests -t .
xvfb-run -a python3 -m unittest discover -s tests -t .
```

On Windows, the focused controller tests can also be run with:

```powershell
uv run --no-project python -m unittest discover -s tests -p "test_windows_controller.py" -t .
```

Use `python3 -m unittest tests.unit.windows.test_windows_controller` to
directly run the relocated tests. Keep `tests/__init__.py` and package
`__init__.py` files in every new nested test directory because unittest
discovery depends on importable packages.

The migration has grouped 65 test modules under `unit/` and `integration/`.
Two root-level modules remain because they export shared test fixtures:
`tests/test_remote_access.py` and `tests/test_compat_lifecycle.py`.
Move them only after updating every importing test and checking that they
are not accidentally imported and discovered twice.

The production `linux_rdaccess_windows.py` entry point is unchanged.
The Windows test's source path was updated, and moved tests with fixture paths
were adjusted to continue using `tests/fixtures/`. Do not merge without
passing CI and the Mint/Orca integration checks.
