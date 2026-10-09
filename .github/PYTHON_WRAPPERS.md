# Python compatibility wrappers and repository layout

This guidance applies to Codex, Claude, GitHub Copilot, and other contributors working on `linux-rdaccess`.

## What is a wrapper?

A root-level Python compatibility wrapper preserves an older module import or command entry point after its implementation has moved under `linux_rdaccess_core/`. It should stay small and delegate to the implementation rather than contain a second implementation.

For example:

```text
linux-rdaccess/
├── linux_rdaccess.py          # CLI/compatibility entry point
├── remote_access.py           # legacy module wrapper
├── orca_adapter.py            # legacy module wrapper
├── linux_rdaccess_core/
│   ├── connection/
│   │   └── remote_access.py   # implementation
│   └── accessibility/
├── tests/
├── tools/
└── docs/
```

The actual root `remote_access.py` uses `importlib.import_module('linux_rdaccess_core.connection.remote_access')`. When imported, it places that implementation in `sys.modules[__name__]`; when executed directly, it invokes the implementation's `main()`. This preserves the old `import remote_access` identity and script entry point. A bare `from ... import *` is only a simplified illustration and is **not** an interchangeable replacement for that behavior.

## Repository policy

1. **Keep existing root Python wrappers in place** for backward compatibility. Do not move them into a `wrappers/` directory merely to clean up the repository root.
2. **Put new implementation code under `linux_rdaccess_core/`**, not in duplicate root-level implementations. Prefer package-qualified imports for new internal code.
3. **Do not add new root-level Python modules** unless they are needed as explicit CLI or compatibility entry points.
4. **Treat `linux_rdaccess.py` and other script entry points as public interfaces.** Preserve supported shell commands, imports, and installation paths.
5. **Avoid editing root wrappers during unrelated fixes.** Their unchanged status is often checked by tests and should be stated accurately in PR reports.
6. A future wrapper removal or relocation is a **breaking compatibility change**. Propose it separately, inventory all importers and entry points (including generated Orca patches, installers, tests, diagnostics, scripts, documentation and external users), provide a migration plan, and add targeted coverage before proceeding. Never silently move or delete wrappers.

## Why not a wrappers/ directory?

Moving `remote_access.py` to `wrappers/remote_access.py` changes the module path. Existing `import remote_access`, script invocations, loaders, and installation assumptions might fail. A neater directory is not by itself a sufficient reason to break them.

## AI agent checklist

Before changing Python module locations:

- Identify whether each file is an implementation, an entry point, or a legacy compatibility wrapper.
- Inspect the current wrapper's delegation semantics rather than assuming it is a simple wildcard import.
- Search references to the original module path and executable filename throughout the repository and installation outputs.
- Keep root wrappers stable unless the task explicitly requires a reviewed compatibility migration.
- Test imports, command invocation, installation/upgrades and old entry-point behavior if any wrapper-related code must change.

This document is a maintenance convention, not a prohibition on all future reorganizations. Compatibility migrations require explicit review and test evidence.
