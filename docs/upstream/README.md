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
# Original: expected nonzero, 9 passed / 7 assertions failed / 0 errors.
ELECTRON_RUN_AS_NODE=1 /usr/share/code/code tools/diagnostics/vscode_selection_contract.cjs "$TREE/original.ts" "$COMPILER"
# Patched: expected 16 passed / 0 failures / 0 errors.
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
emoji input or supplementary-character offset mapping works.
The experiment uses `xclip -selection clipboard` plus Ctrl+V for the two
Unicode fixtures on its private Xvfb display; ASCII and multiline still use
`xdotool type`. `xclip` must be installed for these cases. Keep fixture-entry
failures distinct from failures after routing, and do not mark Unicode
acceptance passed without native evidence.

In the isolated patched Code 1.141.0 run on 2026-10-15, the BMP fixture passed
all native routing, clipboard, and focus-return checks. The emoji fixture was
entered correctly (13 code points, 14 UTF-16 code units), and caret routing
plus Right=2/Left=1 passed, but the strict semantic-selection check failed:
the text exposed 13 code points while selection end was 12. This remains a
Unicode selection mismatch; no selection assertion was relaxed.
The [follow-up investigation](../compatibility-audit-2026-10-15-vscode-unicode-selection.md)
identifies duplicate conversion in Chromium's Linux accessibility provider.
Preserve all failing run logs and exit codes.

## Compare DOM, AT-SPI and semantic selection

The separate selection-only diagnostic prepares an independent Code copy,
uses a fresh private Xvfb/D-Bus session and reads DOM selection through
loopback CDP. It requires the normal experiment dependencies plus Python's
`websocket-client` package. The output path must be new:

```sh
python3 tools/diagnostics/vscode_unicode_selection_probe.py --execute --output /tmp/code-unicode-original
python3 tools/diagnostics/vscode_unicode_selection_probe.py --execute --output /tmp/code-unicode-candidate --source "$TREE/$SOURCE"
```

It records BMP, one-emoji and two-emoji measurements without requesting a
caret route. `diagnostic_complete` means observations completed; it is not
Unicode acceptance. `provider_full_selection=false` remains visible in its
numeric report. The strict normal experiment above still fails on the emoji
selection. The probe changes no installed Code files and preserves logs and
hashes under its output directory.

## Chromium Unicode selection candidate

`chromium-unicode-selection.diff` is an **unsubmitted candidate** for Chromium
150.0.7871.250, the version bundled in the tested Electron 43.7.7. It changes
`ui/accessibility/platform/ax_platform_node_auralinux.cc` and adds upstream
gtests in the neighboring `_unittest.cc`. The source/patch context is copyright
The Chromium Authors under the accompanying [BSD license](Chromium-LICENSE.txt).

The candidate converts ordinary selection offsets once and preserves the
separate UTF-16 conversion needed by find-in-page. Apply it only to a
disposable checkout of that exact Chromium tag. This repository does not
build, install or inject a Chromium binary. Native validation of the candidate,
the full upstream build/gtest suite and real NVDA/physical braille acceptance
remain outstanding. See the follow-up audit for evidence and limitations.

The [source-extraction contract](chromium-unicode-selection.md) compiles the
actual two Chromium selection methods with explicit ATK/delegate/conversion
test dependencies. Original: 4 passed / 5 failed (exit 1); candidate: 9 passed /
0 failed (exit 0), using g++ 11.4.0 with warnings treated as errors. These are
source-contract results; the upstream gtests have not been built or run.

Download the pinned provider source and run from the repository root on Linux.
Use a **new disposable output directory outside any Git checkout**, such as
the `/tmp` path below:

```sh
mkdir -p /tmp/lrd-chromium-selection-source
curl --fail --location 'https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc' -o /tmp/lrd-chromium-selection-source/ax_platform_node_auralinux.cc
python3 tools/diagnostics/chromium_selection_contract.py --source /tmp/lrd-chromium-selection-source/ax_platform_node_auralinux.cc --patch docs/upstream/chromium-unicode-selection.diff --output /tmp/lrd-chromium-selection-contract
```

The tool verifies the exact source SHA-256 and preserves numeric JSONL,
summary, extracted C++, and executable evidence. It does not access a GUI.
