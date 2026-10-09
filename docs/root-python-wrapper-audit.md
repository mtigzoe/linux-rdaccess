# Root Python wrapper audit

## Recommendation

Keep all 12 root Python files for now. There are **six CLI entry points that
also preserve imports, six import-only compatibility wrappers, and no root
implementation modules**. Together they contain 85 lines, including comments
and blank lines. Implementation consolidation has already happened under
`linux_rdaccess_core/`; deleting these delegates would save little code while
changing public interfaces.

**No wrapper is confirmed obsolete or safe to remove today.** Every one is a
mandatory installer input. Several also have executable consumers, and
`a11y_link` has a confirmed consumer in the separate `mtigzoe/rdAccess`
repository. The least-used import wrappers are candidates for a future
deprecation investigation, not immediate deletion.

This audit follows [the wrapper policy](../.github/PYTHON_WRAPPERS.md) and
[the AI workflow](../.github/AI_WORKFLOW.md), which were read before inspecting
the files. It changes documentation only. No wrapper, production code, workflow,
active desktop configuration, or installed Orca file was changed.

## Scope and method

Audited on 2026-10-09 at linux-rdaccess commit
`7f7cd835f51fc7f1a60346781cdb412bb5ce6b58`.

- Inventoried every tracked root `.py` file and read each delegate and its
  canonical implementation's imports.
- Searched all 255 tracked repository files for legacy filenames and module
  names, including hidden workflow files, Python imports, dynamic imports,
  subprocess paths, shell/PowerShell scripts, tests, generated Orca source,
  fixtures, installers, and documentation. Parsed Python files with `ast` to
  enumerate exact, unqualified root imports; there were no parse errors.
- Traced the installer manifest, generated Linux launcher, `configure`
  subprocess, standalone Orca copies, and both wrapper delegation styles.
- Inspected all 136 tracked files in a temporary, read-only checkout of the
  public companion repository `mtigzoe/rdAccess` at
  `7bfc0c86aa97044e044558d9cac24f9ba39c9d08`. Supplementary public web searches
  did not establish a complete inventory of other consumers.
- Ran existing compatibility and installation tests, CLI parser checks, and
  disposable installer fixtures. No GitHub Actions run was queried or monitored.

Static searches cannot establish that a public module has no users. Private
repositories, local launchers, user-written Orca customizations, historical
checkouts, and dynamically constructed imports remain outside this inventory.
Filename matches were inspected in context: a canonical package filename,
`linux_rdaccess_a11y_model.py`, or an old validation record is not automatically
a current root-wrapper dependency.

## Classification of every root Python file

All implementation paths below are relative to `linux_rdaccess_core/` and link
to the canonical source. **Alias** means the imported root name is replaced
with the implementation module in `sys.modules`. **Export** means wildcard
re-exporting; it preserves exported objects but not module identity. Every row
also depends on the shared installer contract described below.

| Root file | Classification / delegation | Real implementation | Implementation dependencies | Confirmed callers or references | Compatibility risk and recommendation |
| --- | --- | --- | --- | --- | --- |
| [`linux_rdaccess.py`](../linux_rdaccess.py) | CLI entry point + compatibility import; alias, direct `main()` | [`cli.py`](../linux_rdaccess_core/cli.py) | Standard library; `installation.files`, `installation.autostart`, `connection.remote_access`, `connection.session`; `configure` invokes root `remote_access.py` | README install commands; generated installed launcher; installation/configuration tests; workflow compilation | Removing it breaks `python3 linux_rdaccess.py install` and the installed `linux-rdaccess` launcher. Preserve as a permanent public bootstrap unless an explicitly reviewed replacement keeps the old command working. |
| [`linux_rdaccess_windows.py`](../linux_rdaccess_windows.py) | CLI entry point + compatibility import; alias, direct `main()` | [`connection/windows_controller.py`](../linux_rdaccess_core/connection/windows_controller.py) | Standard library; SSH and Windows/PowerShell facilities when executing actions | README and Windows controller guide; start/stop PowerShell helpers; Windows workflow `--help`; dynamic import identity test | No static Python importer does **not** mean unused: scripts execute this filename. Keep the public Windows controller path. |
| [`remote_access.py`](../remote_access.py) | CLI entry point + compatibility import; alias, direct `main()` | [`connection/remote_access.py`](../linux_rdaccess_core/connection/remote_access.py) | Standard library; `installation.files.orca_runtime_sources`; generated Orca integration code loads standalone adapter and native APIs | Linux CLI `configure` subprocess; README configuration commands; shared/input/reconnection tests; workflow compilation | Removal breaks current configuration, public commands, and legacy imports/private helper patching. Keep; any future subprocess migration must preserve old imports and scripts. |
| [`nvda_remote_check.py`](../nvda_remote_check.py) | CLI entry point + compatibility export; export, direct `main()` | [`connection/nvda_remote_check.py`](../linux_rdaccess_core/connection/nvda_remote_check.py) | Standard library; reads connection/customization configuration for diagnostics | README plain/JSON diagnostic commands; diagnostic tests; compatibility export test; workflow compilation | Removing it breaks documented diagnostic commands and exported API names. Keep the published diagnostic entry point. |
| [`atspi_nvda_bridge.py`](../atspi_nvda_bridge.py) | CLI entry point + compatibility import; alias, direct `main()`, interrupt exit 130 | [`accessibility/atspi_nvda_bridge.py`](../linux_rdaccess_core/accessibility/atspi_nvda_bridge.py) | GI with AT-SPI/GLib at import; `accessibility.announcer`, `transport.rdaccess_dvc`; xrdp channel library during channel setup | README xrdp command; implementation docstring commands; bridge tests; diagnostics workflow root `--help` | Removal breaks the legacy xrdp speech CLI/import. Preserve argument, exit, and interrupt behavior; keep this public entry point. |
| [`atspi_nvda_braille_bridge.py`](../atspi_nvda_braille_bridge.py) | CLI entry point + compatibility import; alias, direct `main()`, interrupt exit 130 | [`accessibility/atspi_nvda_braille_bridge.py`](../linux_rdaccess_core/accessibility/atspi_nvda_braille_bridge.py) | GI with AT-SPI/GLib and `louis` at import; announcement/model and transport modules; xrdp channel library during setup | Braille bridge tests; diagnostics workflow root `--help`; remote-a11y path filter; installer | The Linux shell launcher already uses the canonical `-m` path, but the old CLI remains supported and tested. Keep it; launcher migration alone does not retire the root path. |
| [`orca_adapter.py`](../orca_adapter.py) | Compatibility wrapper; alias, no CLI | [`accessibility/orca_adapter.py`](../linux_rdaccess_core/accessibility/orca_adapter.py) | Standard library/ctypes; package model or renamed standalone model; Orca, GI, liblouis and X11 APIs loaded for particular operations | Unit/braille/X11 tests; dynamic identity/private-state test; older documentation links; installer | Alias identity preserves mutable semantic/braille state and private helpers. Keep. Native Orca uses a separately named implementation copy, not this wrapper; future retirement would still need an import/installer migration. |
| [`a11y_model.py`](../a11y_model.py) | Compatibility wrapper; alias, no CLI | [`accessibility/a11y_model.py`](../linux_rdaccess_core/accessibility/a11y_model.py) | Standard library; optional GI/AT-SPI queries; used by the canonical adapter and braille bridge | Semantic/focus/braille tests; workflow path filters; dynamic identity test; installer | Package-qualified tools and the standalone Orca copy do not require this root import, but existing tests/public imports and installation do. Keep; investigate deprecation only in a separate migration. |
| [`announcer.py`](../announcer.py) | Compatibility wrapper; export, no CLI | [`accessibility/announcer.py`](../linux_rdaccess_core/accessibility/announcer.py), through package shim [`announcer.py`](../linux_rdaccess_core/announcer.py) | Standard library only (`time`, dataclasses, typing) | Three test files import the root; installer; organization and historical documentation. Canonical bridges import the implementation directly | Relatively weak current root usage: a future deprecation candidate after consumer review and installer migration. Not proven obsolete. Keep now, preserving exported class/constant identity. |
| [`a11y_link.py`](../a11y_link.py) | Compatibility wrapper; export, no CLI | [`transport/a11y_link.py`](../linux_rdaccess_core/transport/a11y_link.py), through package shim [`a11y_link.py`](../linux_rdaccess_core/a11y_link.py) | Standard library; `transport.rdaccess_dvc` framing/receiver helpers; xrdp library when a DVC is opened | Five Python test files; embedded heartbeat check in this repository's workflow; **external rdAccess workflow**; installer | Confirmed cross-repository public import (`decode_pong`). Keep; coordinate the external consumer before proposing deprecation. This is not an unused transport wrapper. |
| [`braille_link.py`](../braille_link.py) | Compatibility wrapper; export, no CLI | [`transport/braille_link.py`](../linux_rdaccess_core/transport/braille_link.py), through package shim [`braille_link.py`](../linux_rdaccess_core/braille_link.py) | Standard library; `transport.rdaccess_dvc`; xrdp library when a DVC is opened | Five test files for protocol/replay/stream/privacy behavior; installer; organization and historical documentation | Relatively weak current root usage: a future deprecation candidate, subject to external-user and installer review. Keep now; absence of a found production importer does not prove removal is safe. |
| [`rdaccess_dvc.py`](../rdaccess_dvc.py) | Compatibility wrapper; export, no CLI | [`transport/rdaccess_dvc.py`](../linux_rdaccess_core/transport/rdaccess_dvc.py), through package shim [`rdaccess_dvc.py`](../linux_rdaccess_core/rdaccess_dvc.py) | Standard library/ctypes; libxrdpapi loaded when requested, not merely by importing helpers | `examples/xrdp/rdaccess_speak_test.py`; eleven Python test files; installer | A shipped example still imports this root path. Keep; migrate that example and review external xrdp scripts before considering deprecation. |

The four flat **package** shims (`linux_rdaccess_core.announcer`, `.a11y_link`,
`.braille_link`, `.rdaccess_dvc`) are another compatibility layer, not additional
implementations. New internal code should import the named subpackage directly.
Removing a root wrapper and removing its package shim are separate compatibility
decisions.

## Dependencies that an import-only search would miss

### Installer and installed command

[`installation/files.py`](../linux_rdaccess_core/installation/files.py) lists
all 12 root files in `RUNTIME_FILES`. `install_runtime_files()` validates every
one **before** copying the complete core package and the wrappers. Omitting any
one produces `FileNotFoundError`, even when the installer never executes that
module. Twelve temporary source-bundle fixtures confirmed this individually,
with no installation output created on failure.

The generated `linux-rdaccess` launcher executes the installed root
`linux_rdaccess.py`. Source lookup also supports reinstalling from an installed
bundle. Separately, [`cli.py`](../linux_rdaccess_core/cli.py)'s `configure`
command launches `source_bundle_root() / "remote_access.py"` in a subprocess.
These are executable filename dependencies, not Python import statements.

The installer copies over existing directories without pruning old files.
Simply omitting a wrapper from a future manifest could make upgraded and fresh
installations behave differently: an upgraded installation might retain a stale
wrapper. A migration must address fresh installs, upgrades, installed reinstalls,
and any explicit stale-file policy together.

### Generated Orca customizations and standalone modules

`orca_runtime_sources()` selects the canonical
`accessibility/orca_adapter.py` and `accessibility/a11y_model.py` implementations.
[`connection/remote_access.py`](../linux_rdaccess_core/connection/remote_access.py)
copies these alongside the legacy Orca controller as
`linux_rdaccess_orca_adapter.py` and `linux_rdaccess_a11y_model.py` when updating
an eligible customization. It does **not** copy the corresponding root wrappers.

Generated/injected code imports `linux_rdaccess_orca_adapter`; the standalone
adapter loads `linux_rdaccess_a11y_model` when it has no package context. In a
package context it imports `.a11y_model` instead. The Linux `doctor` command
compares the installed standalone files against those same canonical sources.
Thus, retiring a root wrapper would not retire the native implementation, but
changing these renamed standalone imports or their shared state would be a
separate Orca compatibility change. The existing standalone-layout test checks
this separation in a temporary directory with a fake Orca module.

### Scripts, tools, and documentation

- [`start-windows-session.ps1`](../scripts/windows/start-windows-session.ps1)
  and [`stop-windows-session.ps1`](../scripts/windows/stop-windows-session.ps1)
  construct the root Windows controller path. Their dependence is also stated
  in [`scripts/README.md`](../scripts/README.md) and
  [the Windows guide](windows-controller.md).
- [`examples/xrdp/rdaccess_speak_test.py`](../examples/xrdp/rdaccess_speak_test.py)
  adds the repository root to `sys.path` and imports `rdaccess_dvc` directly.
  It is the only non-test `.py` file with an exact unqualified root import
  found by the AST scan. This excludes Python embedded in YAML and subprocess
  execution, which have additional consumers.
- [`scripts/linux/run_braille_bridge.sh`](../scripts/linux/run_braille_bridge.sh)
  invokes `linux_rdaccess_core.accessibility.atspi_nvda_braille_bridge` with
  `-m`. The `tools/a11y/` generators/decoder and Python diagnostics use canonical
  package imports. No implementation under `linux_rdaccess_core/` has an exact
  unqualified import of one of these 12 root module names.
- The [README](../README.md) publishes the Linux installer, Windows controller,
  configuration, diagnostic, and xrdp speech commands. The bridge implementation
  docstring also publishes root CLI examples. These are supported interfaces
  even when there is no Python importer.
- [Repository organization](repository-organization.md) and
  [the wrapper policy](../.github/PYTHON_WRAPPERS.md) list compatibility paths.
  Earlier dated audit/validation reports refer to root files before their
  implementations moved. Those are historical records, not evidence of a
  remaining duplicate implementation; preserve their historical context.

### Workflow source references

Only workflow **definitions** were inspected; no run status was requested.

| Definition | Root-path dependency or relevant coverage |
| --- | --- |
| [Full unittest suite](../.github/workflows/uv-unittest.yml) | Compiles `linux_rdaccess.py`, `linux_rdaccess_windows.py`, and `remote_access.py`; runs isolated installation acceptance and the Linux Python 3.10 suite; its Windows Python 3.12 job executes the Windows root CLI and import/standalone tests. |
| [Remote A11Y prototype](../.github/workflows/remote-a11y-tests.yml) | Root filename path filters; compiles Linux/configuration/diagnostic entry points; heartbeat check embeds `from a11y_link import decode_pong`; generators otherwise use canonical package modules. |
| [Linux diagnostics](../.github/workflows/linux-diagnostics.yml) | Executes both canonical bridge `-m` paths and both root bridge filenames with `--help`, using system GI/liblouis. |
| [Linux GUI accessibility](../.github/workflows/linux-gui-accessibility.yml) | Explicit root `a11y_model.py` path filters as well as canonical implementation coverage. |

Path filters and compilation checks are maintenance references, not proof that
an import is needed at runtime. Conversely, a workflow's embedded Python import
is a real root consumer and is not counted by scanning only `.py` files.

## External consumers and removal assessment

There is a concrete external consumer of `a11y_link`: the
[rdAccess heartbeat workflow at the audited commit](https://github.com/mtigzoe/rdAccess/blob/7bfc0c86aa97044e044558d9cac24f9ba39c9d08/.github/workflows/remote-a11y-tests.yml#L88)
checks out this repository's `main`, sets `PYTHONPATH=linux-rdaccess`, and imports
`decode_pong` with `from a11y_link import decode_pong`. Removing that wrapper
would make the import fail. The companion add-on consumes the semantic protocol;
this workflow additionally depends on the Python compatibility interface.

The companion definition also still names older `tools/` fixture paths; this
repository now keeps those tools under `tools/a11y/`. That is a source-level
coordination issue to account for in a separate consumer update, not a claim
about the result of any workflow run. No external repository was changed or run.

No other explicit imports of these root modules were found in the inspected
companion checkout. That finding covers this one commit and repository only.
Public web search cannot enumerate unindexed, private, installed, or local users.
External consumers might execute the documented filenames, import public objects
from a checkout/installed bundle, patch private helpers through an aliased module,
or load files by path. A zero repository-import count does not rule these out.

| Removal category | Files | Assessment |
| --- | --- | --- |
| Public executable interfaces | `linux_rdaccess.py`, `linux_rdaccess_windows.py`, `remote_access.py`, `nvda_remote_check.py`, both `atspi_nvda_*_bridge.py` files | Keep. Installation, scripts, documentation, or explicit CLI tests depend on these paths. |
| Confirmed external import interface | `a11y_link.py` | Keep. Coordinate the rdAccess consumer and this repository's embedded workflow import before any deprecation proposal. |
| Shipped example import interface | `rdaccess_dvc.py` | Keep. Migrate the example first; investigate downstream xrdp scripts. |
| Stateful/model import interfaces | `orca_adapter.py`, `a11y_model.py` | Keep. Internal tools already use canonical imports, but alias semantics, tests, public paths, and the installer remain compatibility contracts. |
| Weakest observed root import usage | `announcer.py`, `braille_link.py` | Possible future deprecation candidates. Current exact Python importers are tests, but installation requires both and external users are unknown. Neither is confirmed obsolete. |
| Safe immediate deletions | None | Deleting any current root wrapper fails the existing installer, independently of additional public compatibility risks. |

Alias wrappers and export wrappers must not be mechanically interchanged.
The seven aliases preserve implementation module identity, private attributes,
and writes to module globals. The five export wrappers preserve exported
class/function objects but have separate module namespaces; wildcard imports
also have rules about private names and `__all__`. Changing either pattern
could alter monkeypatching and state behavior without changing an import's
spelling. Dedicated compatibility tests deliberately assert these contracts.

## Long-term repository structure

The current package organization is already suitable for implementation work:

```text
linux-rdaccess/
├── linux_rdaccess.py                   # stable public install/CLI bootstrap
├── linux_rdaccess_windows.py           # stable Windows controller entry
├── remote_access.py                    # stable configuration entry
├── nvda_remote_check.py                # stable diagnostic entry
├── atspi_nvda_bridge.py                # stable speech bridge entry
├── atspi_nvda_braille_bridge.py         # stable braille bridge entry
├── {orca_adapter,a11y_model,announcer,a11y_link,braille_link,rdaccess_dvc}.py
│                                      # legacy import compatibility only
├── linux_rdaccess_core/
│   ├── cli.py
│   ├── accessibility/                 # Orca/AT-SPI/model/announcement code
│   ├── connection/                    # configuration, sessions, controllers
│   ├── installation/                  # bundle, launcher, autostart contracts
│   ├── transport/                     # DVC, semantic and braille transport
│   └── {announcer,a11y_link,braille_link,rdaccess_dvc}.py  # package shims
├── scripts/{linux,windows}/
├── tools/{a11y,diagnostics}/
├── diagnostics/
├── examples/xrdp/
├── tests/{unit,integration,shared,fixtures,apps}/
└── docs/
```

Recommended maintenance steps, each separate from this documentation audit:

1. Keep implementation exclusively in the named core subpackages. Use their
   qualified imports in new code and current documentation about implementation
   locations. Do not introduce more root helpers or move public files into a
   `wrappers/` directory, which changes both imports and executable paths.
2. Gradually migrate implementation-oriented tests and the xrdp example to
   canonical imports, while retaining a dedicated legacy-import/CLI/installer
   acceptance suite. Test migration is not evidence that external use ended.
   Coordinate canonical imports in the rdAccess heartbeat workflow too.
3. If distribution packaging is introduced, define an explicit package/file
   manifest and console entry points that call core `main()` functions. There
   is currently no tracked `pyproject.toml`, `setup.py`, or `setup.cfg` defining
   such a replacement. Keep `python3 linux_rdaccess.py install` and the existing
   installed command working throughout; update source-bundle/reinstall logic
   deliberately rather than assuming a wheel has checkout layout.
4. Only consider removing import-only wrappers after a separately reviewed
   deprecation proposal establishes the supported API/version window, known
   consumer migrations, release notes, and fresh/upgrade/reinstall behavior.
   Recheck external consumers at that time; this audit cannot certify their
   future or private usage. The modest root-file saving may not justify a
   breaking release at all.
5. For any proposed migration, preserve coverage of module identity/private
   state where supported, public exports, old script arguments/exit status,
   launcher quoting, installation manifests, `configure`, and standalone Orca
   module loading. Keep native Orca deployment names separate from CLI package
   layout decisions.

## Validation and limitations

Existing focused suites were run unchanged:

```sh
python3 -m unittest -v \
  tests.unit.transport.test_core_import_compatibility \
  tests.unit.transport.test_installed_layout \
  tests.unit.transport.test_installed_runtime_acceptance
```

| Check performed | Result |
| --- | --- |
| Focused suites on system Python 3.10.12 | 13 passed; no failures or skips. |
| Same suites on an existing isolated CPython 3.12.13 interpreter | 13 passed; no failures or skips. |
| All six root CLI `--help` commands on system Python | Passed; parsers exited before executing actions or starting bridge listeners. |
| `python3 linux_rdaccess.py install --help` | Passed. Actual install/reinstall behavior was also exercised by the existing acceptance tests, in disposable homes only. |
| Twelve temporary bundles, each constructed without one different root wrapper | All rejected with `FileNotFoundError` for the omitted wrapper before creating launcher/share outputs. No repository wrapper was deleted or moved. |
| Root import identity/exports and canonical imports without root wrappers | Covered by the existing compatibility suite. Package-only import success does not demonstrate safe removal from the installed bundle. |
| Standalone renamed Orca adapter/model | Existing temporary-layout test passed with a fake Orca module. |

The acceptance tests use private temporary homes/configurations and synthetic
keys. Their connect/disconnect exercises use `--no-restart`; installation and
configuration stay in disposable paths. They do not start Orca or connect to a
relay. No active desktop or installed Orca file was modified. The 3.12 interpreter
was already available locally; no dependencies or desktop software were installed
for this audit.

No full unittest suite, live NVDA/Orca interaction, physical braille session,
native Windows execution, or companion workflow was run. Workflow definitions
were read without monitoring GitHub Actions. The dependency classification is
source-based; passing import/parser tests does not validate optional native
libraries or end-to-end accessibility behavior. No new regression tests are
needed for this documentation-only change; existing regressions remain intact.

## Complete static root-import inventory

The following index lists every exact unqualified root import found in tracked
Python files at the audited commit: 87 import statements across 55 distinct
files. Counts include repeated import statements within a file. Embedded YAML
imports, dynamic identity checks, and executable filename consumers are listed
above separately; the zero for the Windows entry point is intentional.

| Root module | Import statements | Distinct Python importer files |
| --- | ---: | ---: |
| `a11y_link` | 5 | 5 |
| `a11y_model` | 7 | 7 |
| `announcer` | 4 | 3 |
| `atspi_nvda_braille_bridge` | 1 | 1 |
| `atspi_nvda_bridge` | 2 | 2 |
| `braille_link` | 5 | 5 |
| `linux_rdaccess` | 6 | 6 |
| `linux_rdaccess_windows` | 0 | 0 |
| `nvda_remote_check` | 2 | 2 |
| `orca_adapter` | 11 | 9 |
| `rdaccess_dvc` | 12 | 12 |
| `remote_access` | 32 | 25 |

<details>
<summary>All exact Python import locations</summary>

### `a11y_link.py`

- [tests/unit/accessibility/test_a11y_link.py](../tests/unit/accessibility/test_a11y_link.py), line(s) 5.
- [tests/unit/accessibility/test_a11y_link_focus_id.py](../tests/unit/accessibility/test_a11y_link_focus_id.py), line(s) 3.
- [tests/unit/transport/test_core_import_compatibility.py](../tests/unit/transport/test_core_import_compatibility.py), line(s) 19.
- [tests/unit/transport/test_dvc_stream_boundaries.py](../tests/unit/transport/test_dvc_stream_boundaries.py), line(s) 6.
- [tests/unit/transport/test_logging_privacy.py](../tests/unit/transport/test_logging_privacy.py), line(s) 7.

### `a11y_model.py`

- [tests/unit/accessibility/test_a11y_model.py](../tests/unit/accessibility/test_a11y_model.py), line(s) 3.
- [tests/unit/accessibility/test_a11y_model_bounds.py](../tests/unit/accessibility/test_a11y_model_bounds.py), line(s) 3.
- [tests/unit/accessibility/test_bridge_focus_resync.py](../tests/unit/accessibility/test_bridge_focus_resync.py), line(s) 4.
- [tests/unit/accessibility/test_bridge_text_event_gate.py](../tests/unit/accessibility/test_bridge_text_event_gate.py), line(s) 4.
- [tests/unit/accessibility/test_control_pattern_contracts.py](../tests/unit/accessibility/test_control_pattern_contracts.py), line(s) 7.
- [tests/unit/accessibility/test_prelive_ssh_focus.py](../tests/unit/accessibility/test_prelive_ssh_focus.py), line(s) 9.
- [tests/unit/braille/test_nvda_native_braille.py](../tests/unit/braille/test_nvda_native_braille.py), line(s) 9.

### `announcer.py`

- [tests/unit/accessibility/test_announcer.py](../tests/unit/accessibility/test_announcer.py), line(s) 3, 4.
- [tests/unit/accessibility/test_control_pattern_contracts.py](../tests/unit/accessibility/test_control_pattern_contracts.py), line(s) 8.
- [tests/unit/transport/test_core_import_compatibility.py](../tests/unit/transport/test_core_import_compatibility.py), line(s) 18.

### `atspi_nvda_braille_bridge.py`

- [tests/unit/braille/test_braille_bridge.py](../tests/unit/braille/test_braille_bridge.py), line(s) 16.

### `atspi_nvda_bridge.py`

- [tests/unit/accessibility/test_bridge.py](../tests/unit/accessibility/test_bridge.py), line(s) 17.
- [tests/unit/braille/test_braille_bridge.py](../tests/unit/braille/test_braille_bridge.py), line(s) 15.

### `braille_link.py`

- [tests/unit/braille/test_braille_link.py](../tests/unit/braille/test_braille_link.py), line(s) 5.
- [tests/unit/braille/test_braille_link_replay.py](../tests/unit/braille/test_braille_link_replay.py), line(s) 4.
- [tests/unit/transport/test_core_import_compatibility.py](../tests/unit/transport/test_core_import_compatibility.py), line(s) 20.
- [tests/unit/transport/test_dvc_stream_boundaries.py](../tests/unit/transport/test_dvc_stream_boundaries.py), line(s) 7.
- [tests/unit/transport/test_logging_privacy.py](../tests/unit/transport/test_logging_privacy.py), line(s) 8.

### `linux_rdaccess.py`

- [tests/unit/accessibility/test_prelive_ssh_focus.py](../tests/unit/accessibility/test_prelive_ssh_focus.py), line(s) 8.
- [tests/unit/transport/test_configuration_updates.py](../tests/unit/transport/test_configuration_updates.py), line(s) 13.
- [tests/unit/transport/test_installed_runtime_acceptance.py](../tests/unit/transport/test_installed_runtime_acceptance.py), line(s) 14.
- [tests/unit/transport/test_linux_rdaccess.py](../tests/unit/transport/test_linux_rdaccess.py), line(s) 13.
- [tests/unit/transport/test_transport_cleanup.py](../tests/unit/transport/test_transport_cleanup.py), line(s) 10.
- [tests/unit/windows/test_vscode_settings_edge_cases.py](../tests/unit/windows/test_vscode_settings_edge_cases.py), line(s) 6.

### `linux_rdaccess_windows.py`

No static unqualified Python import; see dynamic and executable consumers above.

### `nvda_remote_check.py`

- [tests/unit/transport/test_core_import_compatibility.py](../tests/unit/transport/test_core_import_compatibility.py), line(s) 22.
- [tests/unit/transport/test_nvda_remote_check.py](../tests/unit/transport/test_nvda_remote_check.py), line(s) 9.

### `orca_adapter.py`

- [tests/integration/x11/test_lock_toggle_integration.py](../tests/integration/x11/test_lock_toggle_integration.py), line(s) 18.
- [tests/unit/accessibility/test_focus_accelerator.py](../tests/unit/accessibility/test_focus_accelerator.py), line(s) 13.
- [tests/unit/accessibility/test_native_list_lifetime.py](../tests/unit/accessibility/test_native_list_lifetime.py), line(s) 8.
- [tests/unit/accessibility/test_orca_adapter.py](../tests/unit/accessibility/test_orca_adapter.py), line(s) 10, 94, 170.
- [tests/unit/braille/test_braille_cell_alignment.py](../tests/unit/braille/test_braille_cell_alignment.py), line(s) 12.
- [tests/unit/braille/test_braille_display_lifecycle.py](../tests/unit/braille/test_braille_display_lifecycle.py), line(s) 9.
- [tests/unit/braille/test_braille_input_help.py](../tests/unit/braille/test_braille_input_help.py), line(s) 9.
- [tests/unit/braille/test_braille_routing_speech.py](../tests/unit/braille/test_braille_routing_speech.py), line(s) 9.
- [tests/unit/braille/test_nvda_native_braille.py](../tests/unit/braille/test_nvda_native_braille.py), line(s) 10.

### `rdaccess_dvc.py`

- [examples/xrdp/rdaccess_speak_test.py](../examples/xrdp/rdaccess_speak_test.py), line(s) 25.
- [tests/unit/accessibility/test_a11y_link.py](../tests/unit/accessibility/test_a11y_link.py), line(s) 6.
- [tests/unit/braille/test_braille_link.py](../tests/unit/braille/test_braille_link.py), line(s) 6.
- [tests/unit/braille/test_braille_link_replay.py](../tests/unit/braille/test_braille_link_replay.py), line(s) 5.
- [tests/unit/transport/test_core_import_compatibility.py](../tests/unit/transport/test_core_import_compatibility.py), line(s) 21.
- [tests/unit/transport/test_dvc_channel.py](../tests/unit/transport/test_dvc_channel.py), line(s) 4.
- [tests/unit/transport/test_dvc_stream_boundaries.py](../tests/unit/transport/test_dvc_stream_boundaries.py), line(s) 8.
- [tests/unit/transport/test_logging_privacy.py](../tests/unit/transport/test_logging_privacy.py), line(s) 9.
- [tests/unit/transport/test_poll_guard.py](../tests/unit/transport/test_poll_guard.py), line(s) 4.
- [tests/unit/transport/test_receiver.py](../tests/unit/transport/test_receiver.py), line(s) 4.
- [tests/unit/transport/test_receiver_resync.py](../tests/unit/transport/test_receiver_resync.py), line(s) 4.
- [tests/unit/transport/test_speech_link.py](../tests/unit/transport/test_speech_link.py), line(s) 4.

### `remote_access.py`

- [tests/integration/x11/test_compat_xtest.py](../tests/integration/x11/test_compat_xtest.py), line(s) 13.
- [tests/integration/x11/test_lock_toggle_integration.py](../tests/integration/x11/test_lock_toggle_integration.py), line(s) 19.
- [tests/integration/x11/test_xtest_injection.py](../tests/integration/x11/test_xtest_injection.py), line(s) 19.
- [tests/shared/test_compat_lifecycle.py](../tests/shared/test_compat_lifecycle.py), line(s) 13.
- [tests/shared/test_remote_access.py](../tests/shared/test_remote_access.py), line(s) 12.
- [tests/unit/accessibility/test_customization_say_all_callbacks.py](../tests/unit/accessibility/test_customization_say_all_callbacks.py), line(s) 10.
- [tests/unit/accessibility/test_customization_speech_sequence.py](../tests/unit/accessibility/test_customization_speech_sequence.py), line(s) 10.
- [tests/unit/accessibility/test_say_all_presentation_lifetime.py](../tests/unit/accessibility/test_say_all_presentation_lifetime.py), line(s) 9.
- [tests/unit/accessibility/test_speech_lifecycle.py](../tests/unit/accessibility/test_speech_lifecycle.py), line(s) 10.
- [tests/unit/braille/test_braille_cell_alignment.py](../tests/unit/braille/test_braille_cell_alignment.py), line(s) 13.
- [tests/unit/braille/test_braille_protocol.py](../tests/unit/braille/test_braille_protocol.py), line(s) 103, 115.
- [tests/unit/braille/test_nvda_native_braille.py](../tests/unit/braille/test_nvda_native_braille.py), line(s) 11.
- [tests/unit/input/test_controller_v89_upgrade.py](../tests/unit/input/test_controller_v89_upgrade.py), line(s) 6.
- [tests/unit/input/test_customization_event_api.py](../tests/unit/input/test_customization_event_api.py), line(s) 9.
- [tests/unit/input/test_genuine_upgrades.py](../tests/unit/input/test_genuine_upgrades.py), line(s) 7.
- [tests/unit/input/test_input_trace.py](../tests/unit/input/test_input_trace.py), line(s) 19.
- [tests/unit/input/test_insert_modifier_deferral.py](../tests/unit/input/test_insert_modifier_deferral.py), line(s) 180, 193.
- [tests/unit/input/test_patch_hardening.py](../tests/unit/input/test_patch_hardening.py), line(s) 9.
- [tests/unit/transport/test_configuration_updates.py](../tests/unit/transport/test_configuration_updates.py), line(s) 14.
- [tests/unit/transport/test_customization_reconnect.py](../tests/unit/transport/test_customization_reconnect.py), line(s) 12.
- [tests/unit/transport/test_installed_runtime_acceptance.py](../tests/unit/transport/test_installed_runtime_acceptance.py), line(s) 15.
- [tests/unit/transport/test_linux_rdaccess.py](../tests/unit/transport/test_linux_rdaccess.py), line(s) 14, 389, 405, 419, 443, 449.
- [tests/unit/transport/test_state_hardening.py](../tests/unit/transport/test_state_hardening.py), line(s) 13.
- [tests/unit/transport/test_transport_cleanup.py](../tests/unit/transport/test_transport_cleanup.py), line(s) 11.
- [tests/unit/transport/test_transport_stream_boundaries.py](../tests/unit/transport/test_transport_stream_boundaries.py), line(s) 17.

</details>

To refresh the filename/module-name search from the repository root:

```sh
git ls-files '*.py' ':!:*/*'
git grep -n -E '\b(a11y_link|a11y_model|announcer|atspi_nvda_braille_bridge|atspi_nvda_bridge|braille_link|linux_rdaccess|linux_rdaccess_windows|nvda_remote_check|orca_adapter|rdaccess_dvc|remote_access)\b'
```

For an exact import index, parse every tracked `.py` file with `ast` and match
`Import` names or absolute `ImportFrom.module` values against the 12 root
stems. Inspect strings, workflow heredocs, loaders, and generated sources
separately, as this audit did; AST imports alone omit those dependencies.
