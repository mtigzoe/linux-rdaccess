# VS Code system-caret selection experiment

`vscode-selection-sync.diff` is an **unsubmitted upstream candidate** for VS Code
1.141.0, revision `2a59476c9bfcb90b3ddc372c36762471b7dfad1c`. It changes
`src/vs/editor/browser/controller/editContext/native/screenReaderContentSimple.ts`.
The source and patch context are Microsoft copyright, under the included
[MIT license](VSCode-LICENSE.txt); the remainder of this repository keeps its
existing license.

The patch preserves a pending external DOM caret across unchanged model renders
and replaces timing-based selection suppression with an actual selection
comparison. Focus return invalidates the cached render so model selection can be
restored. Cut/paste hooks remain present without suppressing subsequent external
requests.

See the [investigation and limitations](../compatibility-audit-2026-10-14-vscode-selection-sync.md).
This repository does not install the patch, change Code settings, or inject it
into the installed editor. Do not use the experimental copy as a production
editor. Upstream review, full VS Code testing and real NVDA/physical routing
acceptance remain outstanding.

## Reproduce on Linux

From this repository's root, download the pinned source into a disposable tree
and apply the candidate. The temporary path must be relative to the repository
for `git apply --directory`:

```sh
mkdir -p tmp/braille-routing-outcomes/vscode-source/src/vs/editor/browser/controller/editContext/native
SOURCE=src/vs/editor/browser/controller/editContext/native/screenReaderContentSimple.ts
TREE=tmp/braille-routing-outcomes/vscode-source
curl --fail --location "https://raw.githubusercontent.com/microsoft/vscode/2a59476c9bfcb90b3ddc372c36762471b7dfad1c/$SOURCE" -o "$TREE/$SOURCE"
cp "$TREE/$SOURCE" "$TREE/original.ts"
git apply --check --directory "$TREE" docs/upstream/vscode-selection-sync.diff
git apply --directory "$TREE" docs/upstream/vscode-selection-sync.diff

COMPILER=/usr/share/code/resources/app/extensions/node_modules/typescript/lib/typescript.js
# Original: expected nonzero, 7 passed / 6 assertions failed / 0 errors.
ELECTRON_RUN_AS_NODE=1 /usr/share/code/code tools/diagnostics/vscode_selection_contract.cjs "$TREE/original.ts" "$COMPILER"
# Patched: expected 13 passed / 0 failures / 0 errors.
ELECTRON_RUN_AS_NODE=1 /usr/share/code/code tools/diagnostics/vscode_selection_contract.cjs "$TREE/$SOURCE" "$COMPILER"
```

The contract executes the actual TypeScript class after transpilation, with
isolated DOM, view-model and service dependencies. It is not a VS Code build,
typecheck, upstream test suite or browser integration test.

For a native experiment, install the existing GUI runner's Linux dependencies
listed in `tools/diagnostics/real_gui_atspi_smoke.py`. The script rejects any
installed Code bundle whose hash differs from the reviewed build. Each output
path must be new; allow roughly 1.1 GB per private Code copy, plus profiles/logs.

```sh
python3 tools/diagnostics/vscode_selection_experiment.py --execute --output /tmp/code-79-baseline
python3 tools/diagnostics/vscode_selection_experiment.py --execute --output /tmp/code-79-candidate --source "$TREE/$SOURCE" --runs 12
python3 tools/diagnostics/vscode_selection_experiment.py --execute --output /tmp/code-79-multiline --source "$TREE/$SOURCE" --case multiline
```

The original is expected to fail intermittently; a pass alone does not negate
the bug. Each session issues exactly one route, requires readback 1 and keyboard
continuation 2 then 1, and checks semantic selection, clipboard paste/undo/cut/
restore and focus-return navigation. Failures remain nonzero and stop the run.
`--case unicode` retains a broader exploratory fixture which currently fails;
see the audit before interpreting it. There are no routing retries, quiet-period
workarounds, longer readback timeouts or skipped VS Code assertions.

Only a copied bundle is changed. A syntax check runs before launch. The existing
runner verifies a private Xvfb display and private D-Bus owner before desktop
actions. Each session uses fresh profiles/extensions and public test text;
clipboard operations belong to that private display. The installed root-owned
`chrome-sandbox` helper is reused by symlink without modifying it or disabling
the sandbox. Results include hashes and numeric state; private logs may include
the public fixture and local paths. No active desktop, Orca, NVDA connection or
physical braille device is exercised.

## Unicode isolation cases

The native experiment exposes two independent Unicode fixtures:

- `--case unicode_bmp`: `a café omega` (12 code points, 12 UTF-16 code units).
- `--case unicode`: `a🙂 café omega` (13 code points, 14 UTF-16 code units).

Run them in **separate new output directories**, using the same reviewed
patched TypeScript source. The test performs GUI input only in a private
Xvfb/D-Bus session and leaves the installed Code copy unchanged:

```sh
python3 tools/diagnostics/vscode_selection_experiment.py --execute --output /tmp/code-79-unicode-bmp --source "$TREE/$SOURCE" --case unicode_bmp
python3 tools/diagnostics/vscode_selection_experiment.py --execute --output /tmp/code-79-unicode-astral --source "$TREE/$SOURCE" --case unicode
```

Each result records numeric expected/observed code-point and UTF-16 lengths
and equality, even on a caught fixture-entry failure before routing. Interpret
`input_failed_before_route=true` as an input-harness problem, **not** evidence
of a caret synchronization defect. A correct BMP fixture does not prove that
emoji input or supplementary-character offset mapping works. The current
harness uses `xdotool type`, which has not been shown to reliably inject
these characters; do not mark Unicode acceptance passed without actual
native evidence. Preserve all failing run logs and exit codes.
