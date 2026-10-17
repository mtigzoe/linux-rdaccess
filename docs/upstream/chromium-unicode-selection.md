# Chromium Unicode selection candidate

The [later compiled-source checkpoint](../compatibility-audit-2026-10-17-sourcebuilt-checkpoint.md)
records the actual Chromium `accessibility_unittests` target compiled and run
on 2026-10-16 at pinned commit `f916f1b7136907af19d96b95b891533d091d932a`.
The original provider with the proposed tests passed 7 and failed 3; the
corrected provider passed the same 10 tests, then all 16 tests in a broader
ATK-text inventory. This validates the correction at the compiled Chromium/ATK unit-test
level. A complete Chromium application, completed source-built Electron runtime,
full VS Code source build and real NVDA/physical braille acceptance remain
outstanding.

The earlier [private native experiment](../compatibility-audit-2026-10-15-native-chromium-selection.md)
tests a compiled-method counterpart to the correction. It adds native
application evidence separately from those compiled upstream gtests.
The [source-validation follow-up](../compatibility-audit-2026-10-15-chromium-source-validation.md)
reviews the coordinate systems and build target, and expands the contract to
25 cases with exact per-case baseline and candidate evidence checks.

`chromium-unicode-selection.diff` is an **unsubmitted upstream candidate** for
Chromium `150.0.7871.250`. Chromium source and patch context are covered by the
included [BSD license](Chromium-LICENSE.txt). This repository does not distribute
or install a patched Chromium/Electron binary.

The test host's installed Code 1.141.0 reports Electron `43.7.7`, Chromium
`150.0.7871.250`, and Microsoft build `15553055` when its executable runs in
Node-only mode. [Electron's version-pinned DEPS][deps] agrees with this Chromium
version. None of the 319 `.patch` files under Electron v43.7.7's
`patches/chromium` mentions `ax_platform_node_auralinux`.

In the [pinned Chromium provider source][provider], `GetSelectionExtents`
converts UTF-16 selection offsets into Unicode character offsets.
`GetSelectionWithText` then converts those results again. For a selection that
ends after one supplementary character, 14 UTF-16 units become 13 characters,
then 12. Two supplementary characters produce 16 → 14 → 12. The separate
caret getter converts once.

The candidate converts only the find-in-page fallback, whose stored offsets
remain UTF-16. It preserves the already converted ordinary selection extents.
Five proposed upstream gtests cover ASCII, BMP and combining characters,
supplementary characters, partial/reversed and multiline selections, two
supplementary characters, and full/partial/cleared find-in-page results.

The source-extraction contract compiles the **actual two selection methods**
with explicit test dependencies for ATK, selection storage, text retrieval,
and Unicode conversion. It checks full and partial selections, a supplementary
character selected alone, reversed extents, two supplementary characters,
find-in-page fallback and precedence, multiline text and no selection. It
checks both returned offsets and selected text. Code points are distinct from
grapheme clusters: a combining mark retains its own offset.

On the Linux Mint test host, g++ 11.4.0 compiled both versions with
`-std=c++17 -Wall -Wextra -Werror`:

| Source | Passed | Failed | Executable exit status |
| --- | ---: | ---: | ---: |
| Original | 13 | 12 | 1 |
| Candidate | 25 | 0 | 0 |

The contract succeeds only when it observes the exact 25-case inventory,
per-case expected/observed offsets, text comparisons, 12 original failure
identities and exit codes, and all candidate cases pass. It verifies the source SHA-256 before creating
output:
`1d50dc6645c011e6fa2f036c2b08f7bb35967a60dbda12d52d55e901e8dd731f`.
It writes per-case numeric JSONL, a summary, extracted C++, and executables to
a new output directory. The evidence from 2026-10-15 is retained on the host
under `/tmp/lrd-source-validation-20261015-source/contract-25-verified`.
The historical nine-case results remain under
`/tmp/lrd-chromium-selection-20261015.5ynYuk/result`.

From the repository root on Linux, with g++, git, and curl available:

```sh
mkdir -p /tmp/lrd-chromium-selection-source
curl --fail --location 'https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc' -o /tmp/lrd-chromium-selection-source/ax_platform_node_auralinux.cc
python3 tools/diagnostics/chromium_selection_contract.py --source /tmp/lrd-chromium-selection-source/ax_platform_node_auralinux.cc --patch docs/upstream/chromium-unicode-selection.diff --output /tmp/lrd-chromium-selection-contract
```

Choose a new `--output` path for each invocation. The contract does not fetch
source or contact a desktop. Its output alone does not establish a full Chromium
application build, execution of the proposed upstream gtests, a native
application test of the C++ candidate, or NVDA/physical braille acceptance.
The later checkpoint supplies the separate compiled-gtest evidence; application
and device acceptance remain outstanding.
The separate native observation establishes that the Unicode offset defect
also occurs in private original and experimentally patched VS Code copies;
it does not establish native acceptance of this Chromium candidate.

[deps]: https://raw.githubusercontent.com/electron/electron/v43.7.7/DEPS
[provider]: https://raw.githubusercontent.com/chromium/chromium/150.0.7871.250/ui/accessibility/platform/ax_platform_node_auralinux.cc
