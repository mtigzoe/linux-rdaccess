# Repository organization

Production implementations live in `linux_rdaccess_core`. The twelve root Python
files preserve published commands and import paths. They contain compatibility
imports or executable forwarding; internal modules import the package directly.

## Runtime modules and compatibility paths

| Root path retained | Implementation | Role and callers |
| --- | --- | --- |
| `linux_rdaccess.py` | `linux_rdaccess_core/cli.py` | User installer and CLI; Linux launcher and Windows SSH controller |
| `linux_rdaccess_windows.py` | `connection/windows_controller.py` | Windows menu and SSH CLI; PowerShell session helpers |
| `remote_access.py` | `connection/remote_access.py` | Configuration CLI and legacy Orca patching; installer and input regressions |
| `nvda_remote_check.py` | `connection/nvda_remote_check.py` | Redacted connection diagnostic and public CLI |
| `orca_adapter.py` | `accessibility/orca_adapter.py` | In-process Orca commands, semantic focus, native braille; copied into Orca scripts |
| `a11y_model.py` | `accessibility/a11y_model.py` | AT-SPI semantic objects, text, actions and caret routing; bridges and fixtures |
| `atspi_nvda_bridge.py` | `accessibility/atspi_nvda_bridge.py` | Optional xrdp speech bridge CLI |
| `atspi_nvda_braille_bridge.py` | `accessibility/atspi_nvda_braille_bridge.py` | Optional xrdp speech, semantic objects and braille bridge CLI |
| `announcer.py` | `accessibility/announcer.py` | AT-SPI announcement filtering; both xrdp bridges |
| `a11y_link.py` | `transport/a11y_link.py` | Semantic object-channel protocol |
| `braille_link.py` | `transport/braille_link.py` | Braille transport, replay and commands |
| `rdaccess_dvc.py` | `transport/rdaccess_dvc.py` | xrdp DVC and speech transport |

Implementation paths in the table are relative to `linux_rdaccess_core/`, except
the explicitly qualified CLI path. The earlier `linux_rdaccess_core.announcer`,
`.a11y_link`, `.braille_link` and `.rdaccess_dvc` imports also remain supported.

Moved module wrappers alias the implementation module in `sys.modules`. This
preserves private helpers, shared state and patching through historical imports,
including Orca's braille display and semantic object registries. Wrapper imports
resolve through `importlib`, so an old package attribute cannot revive a removed
or stubbed module.

## Installation contracts

`installation/files.py` validates every required compatibility file and package
module before updating an installation. The user bundle includes the complete
package and compatibility files; installed commands work outside the checkout
and can reinstall themselves. The shell launcher quotes interpreter and source
paths, including spaces, quotes and literal dollar signs.

Orca loads two standalone implementations from its `orca-scripts/` directory:
`linux_rdaccess_orca_adapter.py` and `linux_rdaccess_a11y_model.py`. Connection
updates copy these from `accessibility/`, rather than copying the root wrappers.
The installed adapter imports the renamed model beside it without requiring the
source checkout or the installed CLI package. `doctor` compares those same
implementation files. Preserve their standalone imports when changing them.

`installation/autostart.py` manages the desktop autostart file and
`connection/session.py` coordinates connection changes. Tests use private
temporary homes/configurations, synthetic keys and `--no-restart`; they never
connect to a relay or restart the user's Orca.

## Scripts and tools

Linux implementations live in `scripts/linux/`; root shell wrappers preserve
existing commands. The braille launcher locates the package with `PYTHONPATH`
and invokes `python3 -m linux_rdaccess_core.accessibility.atspi_nvda_braille_bridge`
without changing the caller's directory. `.gitattributes` keeps shell scripts
in LF format in Windows checkouts as well as Linux checkouts.

Windows PowerShell helpers in `scripts/windows/` locate the repository root
before launching the Windows compatibility entry point. `tools/a11y/` generates
the semantic protocol fixtures and `tools/diagnostics/` holds isolated smoke
checks. `diagnostics/` contains live read-only probes; `examples/xrdp/` contains
experimental xrdp examples. The recommended backend remains Orca Remote.

## Test layout and checks

Unit tests are grouped under `tests/unit/{windows,accessibility,braille,input,transport}`.
Shared legacy patch harnesses live in `tests/shared/`; fixtures and applications
live in `tests/fixtures/` and `tests/apps/`. Temporary historical aliases in
`tests/__init__.py` still support cross-test imports without duplicate discovery.

```sh
python3 -m compileall -q linux_rdaccess_core diagnostics tools tests
python3 -m py_compile linux_rdaccess.py linux_rdaccess_windows.py remote_access.py
for script in scripts/linux/*.sh ./*.sh; do bash -n "$script"; done
env -u DISPLAY -u WAYLAND_DISPLAY python3 -m unittest discover -s tests -t .
xvfb-run -a python3 -m unittest discover -s tests -t .
python3 tools/diagnostics/gtk_atspi_smoke.py
```

Keyboard injection integration tests require a private Xvfb display. Native
Windows runs controller, public import and standalone Orca fixture tests; the
complete suite targets Linux. System Python with GTK/AT-SPI/liblouis exercises
accessibility integrations that a standalone Python interpreter may skip.

CI includes installation acceptance, headless and Xvfb suites, package/legacy
bridge CLI smoke checks, Windows entry points, and the rdAccess semantic protocol
contract. Physical braille and connected NVDA keyboard/speech still require
live verification. See [cleanup validation](root-python-cleanup-validation-2026-10-08.md).
