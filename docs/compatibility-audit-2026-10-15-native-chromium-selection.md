# Native Chromium selection follow-up — 2026-10-15

PR [#92](https://github.com/mtigzoe/linux-rdaccess/pull/92) stays open and
issue [#79](https://github.com/mtigzoe/linux-rdaccess/issues/79) remains open.
The earlier [source investigation](compatibility-audit-2026-10-15-vscode-unicode-selection.md)
established the duplicate conversion but had not tested a correction in a
native application. This follow-up adds automated native evidence using
independent private application copies. It does **not** establish a full
Chromium source build, execution of upstream gtests or Windows NVDA/physical
braille acceptance.

## What was tested

The test host still runs Linux Mint, Code 1.141.0, Microsoft Electron 43.7.7
build 15553055 and Chromium 150.0.7871.250. The installed executable is stripped;
the matching Microsoft debug symbols are private. Public Electron symbols for
the same version cannot establish addresses in this Microsoft build. There was
no existing Chromium checkout/toolchain on the host; a full source build was
not performed. The host has 14 GiB RAM, 2 GiB swap and ample disk space.

A read-only observer loaded into an owned private Code process recorded its
real ATK selection callback at virtual address `0xa3290d0`. It called the real
ATK function without modifying arguments, offsets or text. Disassembly traced
the callback's tail jump to `GetSelectionWithText` at `0xa325790`, including
its call to `GetSelectionExtents` at `0xa3256b0`. The code matches the pinned
source's conversion and find-in-page paths. These names describe the matched
source methods; the stripped executable does not expose their symbols.

The native experiment changes five reviewed sites in a **new independent
executable copy**, implementing the source candidate's branch behavior:

- Ordinary selection: use the code-point start/end already returned by
  `GetSelectionExtents`, then execute existing validation and text retrieval.
- Find-in-page: retain the original UTF-16 conversion path. Both fallback
  branches execute the original relocated instructions before rejoining it.
- No-selection behavior, caller ABI, setters, keyboard handling and subsequent
  text retrieval remain on their existing paths.

Two call-free trampolines occupy terminal `INT3` alignment padding after
completed functions. Independent disassembly review checked registers, both
fallback branches and the executable segment mapping (file offset = virtual
address − `0x1000`). No offset correction shim or output interception runs in
the final tests. The original observation-only library is not loaded by them.
The existing experimental VS Code renderer synchronization patch is also
present in the strict Code tests so the separate #79 caret race does not
prevent testing later selection/clipboard behavior.

The guarded runner rejects another native hash, changed instruction sites,
overlapping edits, an already modified input, a symlink/hard link, an unowned
copy or a target outside the new experiment directory. It checks both native
hashes before and after execution and records installed integrity. It always
prepares a fresh private copy; there is no in-place patch command or installer.
Strict runner exit codes and assertions are preserved.

| Artifact | SHA256 |
| --- | --- |
| Installed native executable | `f36c0ef83163bb3c7b99c5860ce98a5d4055dd6b69d3a4d393d7563e499d3456` |
| Private native candidate | `851b6cbe2a980344d09a1de58e451dc7a91116ea7bae5ef465abc1f5ee1799ad` |
| Installed renderer bundle | `631c1d79c4f3af9177ca23a70cfe0cf2586a692678bd897af6c869324160d905` |
| Private renderer synchronization candidate | `02f7853f04a4fad8796e5710fc87044e046e68f1dc84e51e17a2cddba8883b83` |

The ELF Build ID remains the original
`bbcca70c7e74fa871cca024670960f3720ccd016`; the full hashes distinguish the
copies. The experiment does not rebuild unwind information, so asynchronous
backtraces inside the small trampolines may differ. It is not a production
binary or a replacement for compiling and validating the upstream patch.

## Native results

Every GUI run used SSH, private Xvfb and a verified private D-Bus session, fresh
profiles and public fixture text. CDP observed DOM selection; the keyboard
matrix did not issue AT-SPI selection/caret setters. Clipboard operations
belonged to the private display.

| Check | Native baseline | Native candidate |
| --- | --- | --- |
| Full selection, BMP / one emoji / two emoji | Ends 12 / 12 / 12 | Ends 12 / 13 / 14 |
| Keyboard matrix provider endpoints | 11/23 correct | 23/23 correct |
| Keyboard matrix DOM endpoints/text | 23/23 correct | 23/23 correct |
| Keyboard matrix caret | 23/23 correct | 23/23 correct |
| Nonempty selected-text clipboard checks | 17/17 correct | 17/17 correct |
| Real Electron find-in-page, including clear/no-selection | 21/21 correct | 21/21 correct |

The 23-case matrix includes full forward/reverse selections, forward/reverse
suffixes, one character (emoji for the supplementary fixtures), collapse to
either end, both emoji together and the second emoji alone. Before correction,
some selections returned `[0,0]` because the second conversion interpreted a
code-point endpoint as the middle of a UTF-16 surrogate pair. The corrected
provider and semantic payload agree on all 23 expected selections, including
normalized absence after collapse (provider `null`, semantic `[null,null]`). No semantic
conversion code was changed.

The find fixture uses actual Electron `webContents.findInPage`, rather than
Code's editor search. Renderer DOM selection remains empty, establishing that
the native accessibility fallback supplies the result. BMP, one-emoji and
two-emoji fixtures each test full, suffix and one-character search results,
initial absence of selection and clearing after each query. Both runtimes
retain the correct offsets. The finalized fixture binds acknowledgements to
request IDs and checks match counts/active results before reading AT-SPI.
It also requires nonempty exact-text accessibility observations, exact DOM
fixture text and an empty DOM selection before counting a case as passed.
Focused regressions reject missing nodes and ordinary DOM selection as proof
of the fallback path.

Early fixture-development failures remain retained and excluded from these
counts. Three initial find runs exited 1 waiting for a result after using
`findNext:false` for an initial request; the pinned Electron API specifies
`true`. Two initial promoted matrix runs exited 1 before any sample because
the long evidence-directory path exceeded Code's Unix IPC path limit. The
matrix now creates a short separate private session root, as the existing
runner does. No application assertion or exception classifier was relaxed.

The unchanged strict experiment passed once in each of four fresh copies:
**ASCII, BMP, emoji and multiline**. Each issued one route, observed readback 1,
required Right=2/Left=1, passed semantic selection, clipboard paste/undo/cut/
restore and focus-return navigation, and exited 0. The one-emoji fixture had
13 code points and 14 UTF-16 units. Cleanup occurs after selections have been
collapsed, so final cleanup null selection fields are not the selection
assertion; its explicit PASS log is recorded separately in the evidence.

The separate diagnostic runner mode also completed natively with correct
provider/semantic full-selection ends 12/13/14. Diagnostic completion retains
the `unicode_acceptance=not_established` label.

## Reproduction and verification

With the reviewed patched TypeScript prepared as described in
[the upstream README](upstream/README.md), choose a new output path:

```sh
python3 tools/diagnostics/vscode_native_selection_experiment.py --execute --output /tmp/code-native-unicode --source "$TREE/$SOURCE" --case unicode
python3 tools/diagnostics/vscode_native_selection_experiment.py --execute --selection-probe --output /tmp/code-native-selection-probe --source "$TREE/$SOURCE"
```

The first command runs the existing strict test. The second collects the
separate stage comparison. The new matrix and find probes provide broader
native coverage; see the upstream README for their commands.

Twenty-one focused regressions passed on Linux: seventeen native-runner cases
and four find-evidence cases. The native-runner cases also passed on Windows.
They check pinned instruction sites, branch destinations, baseline immutability, rejection of
unsafe/changed targets, child-mode dispatch, post-run integrity and preservation
of failing exit codes. Scoped lint/format, compilation and whitespace checks
were also performed. Existing successful suites were not repeated without a
change requiring them.

An independent Windows sandbox attempt initially failed while setting up
temporary directories. The authorized run outside that sandbox passed all
seventeen native-runner tests; the setup failure is not counted as a native
application failure.

The [sanitized numeric evidence](vscode-native-selection-evidence-2026-10-15.json)
records expected and observed endpoints, strict selection PASS evidence,
native edits and integrity checks. Raw private evidence is retained under
`/tmp/lrd-native-selection-20261015-glT6pq` on `cyber.local`; baseline keyboard
matrix evidence is also under `/tmp/lrd-vscode-unicode-20261015-MXANAK`.

## Remaining acceptance

This is automated native application testing of a reviewed compiled-method
counterpart to the source correction. The complete Chromium/Electron source
candidate has **not been built**, its upstream gtests have **not run**, and
there has been no live Windows NVDA input, audible speech or physical braille
test. These results do not establish arbitrary Unicode, IME, platform or
application compatibility. The two small trampolines are an experimental
validation technique only.

Installed Code still contains both upstream defects. Its executable and bundle
hashes stayed unchanged. No active desktop, installed accessibility software,
connection or device settings changed. PR #92 must remain open for review;
issue #79 is not resolved. No new CI was polled or awaited, and nothing was
merged or submitted upstream.
