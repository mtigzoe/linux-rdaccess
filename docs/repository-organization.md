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
The two remaining test modules have moved to `tests/shared/`:
`test_remote_access.py` and `test_compat_lifecycle.py`. Existing imports
of their old names are temporarily supported by module aliases in
`tests/__init__.py`. Once all cross-test imports have moved to
`tests.shared`, remove the temporary aliases. `unittest` discovery must
load their tests only once.

The production `linux_rdaccess_windows.py` entry point is unchanged.
The Windows test's source path was updated, and moved tests with fixture paths
were adjusted to continue using `tests/fixtures/`. Do not merge without
passing CI and the Mint/Orca integration checks.

## Production source layout

`linux_rdaccess_core/` holds internal pure-Python implementation modules,
currently containing the announcement engine, accessibility object-channel link,
braille transport link, and xrdp dynamic virtual channel (DVC) protocol helpers. The root `announcer.py`, `a11y_link.py`, `braille_link.py`, and
`rdaccess_dvc.py` files are compatibility imports for existing callers. The root `announcer.py` is retained as
a compatibility import so existing bridges and tests continue to work.

Keep executable entry points and installer-managed source files at the root
until the installation and Orca script-copy contracts can be migrated together.
In particular, `linux_rdaccess.py`, `remote_access.py`, `orca_adapter.py`, and
`a11y_model.py` have root-relative installation dependencies. Do not remove
those root paths as part of cosmetic cleanup.

## Optional launch scripts and examples

- `scripts/windows/start-windows-session.ps1` and
  `scripts/windows/stop-windows-session.ps1` are optional Windows PowerShell
  session helpers. Run them from the repository root as
  `.\\scripts\\windows\\start-windows-session.ps1` and
  `.\\scripts\\windows\\stop-windows-session.ps1`. They resolve the
  repository root before launching `linux_rdaccess_windows.py`.
- `examples/xrdp/rdaccess_speak_test.py` is an experimental manual xrdp
  speech diagnostic, not part of the recommended Orca Remote backend.

The root directory still contains Python modules that are used by installer
copy operations, compatibility imports, and standalone Linux entry points.
Do not move those files without an installer and integration migration.
