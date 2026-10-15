# Chromium Unicode selection source validation — 2026-10-15

The correction uses the correct coordinate systems in Chromium
`150.0.7871.250`: ordinary selection already contains Unicode code-point
offsets, while find-in-page supplies UTF-16 offsets. The expanded extracted
source contract reproduces **12 baseline failures out of 25 cases** and passes
**25/25** with the candidate. This is neither a full Chromium build nor an
execution of the proposed upstream gtests. Those production integration checks
remain outstanding, and issue [#79](https://github.com/mtigzoe/linux-rdaccess/issues/79)
must remain open.

This continues the [original investigation](compatibility-audit-2026-10-15-vscode-unicode-selection.md)
and [private native experiment](compatibility-audit-2026-10-15-native-chromium-selection.md)
after PR #92 merged at `7b0f959`. Read-only SSH inventory and source tests used
Linux Mint at `miriam@cyber.local`. No installed application, desktop, Orca,
NVDA, Remote Access or physical-device configuration changed. These source
tests do not contact a display or accessibility bus.

## Coordinate-system review

The exact [provider source](https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc)
has SHA256
`1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f`.
Its relevant paths are:

| Path | Input | Output and use |
| --- | --- | --- |
| `GetHypertextAdjustments` (4259) | UTF-16 hypertext | Records each supplementary character's two-unit to one-code-point adjustment; combining marks remain separate code points |
| `UTF16ToUnicodeOffsetInText` (4282) | UTF-16 offset | `base::OffsetAdjuster::AdjustOffset` produces a code-point offset |
| `GetSelectionExtents` (4748) | UTF-16 selection extents | Normalizes direction, converts once, returns code-point endpoints |
| `GetSelectionWithText` (4778) ordinary branch | Endpoints from `GetSelectionExtents` | Must retain those code-point offsets |
| `ActivateFindInPageResult` (5027) | UTF-16 result offsets | Stores them unchanged; separately converts its caret event |
| `GetSelectionWithText` find fallback | Stored UTF-16 offsets | Must convert once before returning them or calling `atk_text::GetText` |
| `atk_text::GetText` (994) | Code-point start/end | Converts to UTF-16 for hypertext slicing and returns UTF-8 |
| `GetCharacterCount` (1025) | UTF-16 hypertext length | Converts once to the exposed code-point count |

`base::OffsetAdjuster` also marks an offset inside a surrogate pair invalid;
the selected substring must therefore use valid code-point boundaries.
These are code points, not UTF-16 units or grapheme clusters. For example,
`e` followed by a combining acute accent counts as two code points.

The [candidate diff](upstream/chromium-unicode-selection.diff) moves only the
second conversion into the find fallback. It preserves the real no-selection
and text retrieval paths. No semantic bridge conversion or caret assertion was
changed. The source review found no reason to change this branch correction.

## Build feasibility and genuine upstream target

The pinned [Linux build instructions](https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/docs/linux/build_instructions.md)
require at least 8 GiB RAM, recommend more than 16 GiB, recommend at least
16 GiB swap for a 16 GiB SSD host, and require at least 100 GiB free disk.
They identify Clang and libc++ as the supported toolchain.

Inventory on this Mint 21.3 / Ubuntu Jammy x86-64 host found 16 logical CPUs,
14 GiB RAM, 2 GiB swap, about 10 GiB available RAM and 1.3 TiB free disk.
There is no full Chromium checkout, depot_tools, GN, Ninja, autoninja or usable
Clang executable. The installed compiler is g++ 11.4.0. ATK, ATK bridge, GTK3
and NSS development packages are absent; X11 development headers are installed.
The `/usr/lib/llvm-14` directory does not contain a compiler `bin` directory.

The [pinned target declaration](https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/BUILD.gn)
places `ax_platform_node_auralinux_unittest.cc` in
`//ui/accessibility:accessibility_unittests`, guarded by `use_atk`. It is not
an independently buildable one-file gtest target. The actual target depends
on generated accessibility mojom, base/test support, Mojo/IPC, Skia, gfx and
gtest/gmock, among other components. A gtest filter reduces execution scope;
it does not remove these build dependencies.

A full checkout and a constrained-parallelism build are technically possible
with this disk capacity, but not practical in the current unprovisioned test
environment without substantial source/toolchain/sysroot downloads and resource
planning. No package installation or swap/system configuration change was made.
Neither the full Chromium target nor its upstream gtests was built or run.

For a provisioned checkout of the exact version, the intended verification is:

```sh
git apply --check /path/to/chromium-unicode-selection.diff
git apply /path/to/chromium-unicode-selection.diff
gn gen out/lrd-a11y --args='is_debug=false is_component_build=true symbol_level=0 use_atk=true'
autoninja -C out/lrd-a11y -j2 accessibility_unittests
out/lrd-a11y/accessibility_unittests --gtest_filter='AXPlatformNodeAuraLinuxTest.TestAtkText*Selection*:*TestAtkTextFindInPageUnicodeOffsets'
```

**These build commands were not executed.** Build arguments may need adjustment
against the provisioned checkout's supported configuration. The production
follow-up must retain compiler/linker output and individual gtest results, then
validate an application built from the corrected source. An extracted-method
contract and the prior native binary counterpart do not replace those steps.

## Source-level results and confirmed test improvements

Both the provider and the exact [upstream unit source](https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux_unittest.cc)
were downloaded into `/tmp/lrd-source-validation-20261015-source`.
The unit source SHA256 is
`f18932d4de877d2074b541b4b77bfb9321e4292c5bf62df5a3d32c96481af540`.
`git apply --check` passed across **both complete files**. The candidate now
contains five proposed gtests covering ordinary supplementary, BMP/combining,
multiline, two-supplementary and find-in-page selections. Find assertions also
cover suffix, emoji-only and clearing the result. These gtests remain unrun.

The source contract retains the actual `GetSelectionExtents` and
`GetSelectionWithText` method bodies. ATK, delegate selection storage, Unicode
conversion and text retrieval remain explicit test dependencies. It now covers
25 cases: ASCII, BMP and combining characters; one and multiple supplementary
characters including distinct emoji and musical symbols; full, suffix,
single-character, reversed and multiline selections; collapsed selection;
find full/partial/multiline results; an unrelated node's find result; and
ordinary-selection precedence over an active find result.

The earlier aggregate-only acceptance check was insufficient: swapping the
identities of failures could preserve the totals. The diagnostic now requires
the exact case inventory, individual expected and observed offsets, text
comparison flags, the 12 known baseline failure identities, and the original
and candidate exit codes. Missing/duplicate cases, wrong offsets, unexpected
baseline success and any candidate failure fail validation. Six focused unit
tests cover extraction/pinning, evidence retention and those rejection paths.

Executed on Mint from that private source directory:

```sh
git apply --check chromium-unicode-selection.diff
python3 -B chromium_selection_contract.py --source ui/accessibility/platform/ax_platform_node_auralinux.cc --patch chromium-unicode-selection.diff --output contract-25-verified
```

Both variants compiled with `-std=c++17 -Wall -Wextra -Werror`:

| Variant | Cases passed | Cases failed | Child exit | Exact per-case evidence verified |
| --- | ---: | ---: | ---: | --- |
| Original pinned methods | 13 | 12 | 1 | Yes |
| Candidate methods | 25 | 0 | 0 | Yes |

The diagnostic returned 0 only after checking both sets of evidence. The
[durable sanitized evidence](chromium-source-validation-evidence-2026-10-15.json)
preserves every original failure and candidate result. Private C++, executables,
JSONL, logs and source files remain under the remote directory above;
`contract-25-verified` is the final run, and the earlier `contract-25` run is
also retained.

One initial full patch check failed because a Windows edit had introduced
CRLF patch context against LF upstream source. The diff was normalized to LF,
after which the same full check succeeded. This formatting failure is recorded
in the evidence and is not counted as a source-contract case. The first Windows
unit-test attempt also failed during temporary-directory setup because of
sandbox access restrictions; the authorized unsandboxed run passed all six
tests. Scoped Ruff and formatting checks passed.

No complete source build, upstream gtest execution, live Windows NVDA input,
audible speech or physical braille acceptance is established by these results.
The source candidate is unsubmitted and installed VS Code still contains the
production defects.
