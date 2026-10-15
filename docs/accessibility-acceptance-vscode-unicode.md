# VS Code Unicode accessibility acceptance

Status: **preparation and automated evidence only**. This procedure has not
been performed with live Windows NVDA or a physical Eurobraille b.note 80.
Keep [issue #79](https://github.com/mtigzoe/linux-rdaccess/issues/79) open until
a production application contains the correction and completes acceptance.
The private compiled-method experiment does not satisfy that requirement.

Use the evidence labels in the [NVDA/Linux behavior contract](../.github/NVDA_LINUX_BEHAVIOR.md).
The [Chromium investigation](upstream/chromium-unicode-selection.md) and
[native experiment report](compatibility-audit-2026-10-15-native-chromium-selection.md)
describe different layers of proof. A source contract, a native application
test, a live NVDA session and a physical display observation are separate results.

## The path being accepted

Ordinary Windows keyboard input passes through NVDA Remote Access to the Linux
controller and its native keyboard injection. Orca observes Linux focus,
caret and selection through AT-SPI and generates the speech forwarded to NVDA.
Successful AT-SPI caret readback alone does not prove that the editor's next
keyboard action will start at that caret; #79 specifically requires both.

Braille has two supported paths. Record the negotiated path for every test:

| Path | Presentation and routing | What must agree |
| --- | --- | --- |
| Semantic | Linux AT-SPI snapshot → `lrd_a11y_focus`/`lrd_a11y_text` → Windows rdAccess companion → NVDA text/braille presentation. Routing returns `lrd_a11y_caret` to the current Linux object. | Snapshot text, code-point offset, NVDA text position, actual editor caret and subsequent keyboard movement. |
| Raw fallback | Orca's current braille line/cells → Remote Access `display`; braille commands return to native Orca handlers. | Orca's translated-cell mapping, display width/window, AT-SPI caret and subsequent keyboard movement. |

The implementation is in the [Linux controller](../linux_rdaccess_core/connection/remote_access.py),
[semantic model](../linux_rdaccess_core/accessibility/a11y_model.py),
[Orca adapter](../linux_rdaccess_core/accessibility/orca_adapter.py),
[Windows semantic bridge](../nvda-addon/addon/globalPlugins/linuxRdAccess/remoteAccessSemanticBraille.py)
and [remote TextInfo](../nvda-addon/addon/globalPlugins/linuxRdAccess/remoteA11yObject.py).
Semantic text offsets remain Python Unicode code-point positions. NVDA's
[2026.2 base TextInfo](https://github.com/nvaccess/nvda/blob/release-2026.2/source/NVDAObjects/__init__.py)
uses unencoded Python text, consistent with that inheritance. Chromium's
internal UTF-16 positions must be converted at its ATK boundary, not converted
again in this bridge. A braille cell number is not a Unicode offset: role
prefixes, contractions and emoji translation can all change the mapping.

Read-only SSH inspection on 2026-10-15 found Orca **42.0-1ubuntu2** on
`cyber.local`. Installed `scripts/default.py` delegates routing to
`braille.processRoutingKey`, and `goBrailleHome` uses native focus return.
Panning at line boundaries can use native caret movement, so record the
presentation mode and actual behavior rather than imposing semantic-mode
expectations on raw fallback. Consult the [Orca source guide](../.github/ORCA_SOURCE_REFERENCES.md)
and recheck the installed version before future bridge changes.

## What automation can establish

| Layer | Available automated checks | Remaining boundary |
| --- | --- | --- |
| Chromium | Pinned source review, conversion contracts and targeted upstream gtests when built. | Isolated method contracts do not validate a complete Chromium build. |
| Native Linux application | Private Xvfb/D-Bus: exact text, provider/semantic selection, DOM comparison, caret routing, Left/Right, editing/clipboard, focus return and actual Electron find-in-page. | Scripted routing is not a physical NVDA braille gesture. A temporary patched executable is not a shipped correction. |
| Linux bridge/protocol | Semantic object lifetime, bounds, raw cell alignment at 40/80 cells, input help, speech cancellation and real socket Remote Access loopback. | Mocked Orca/runtime state does not prove audible speech or physical output. |
| Windows companion | Decoder and TextInfo hooks, pending refresh before routing, message restoration, session/focus expiry and routing outcomes. | Fake NVDA base classes do not exercise NVDA's complete text, Liblouis, display driver or device stack. |
| Live Windows NVDA | Can collect version/status, speech-viewer output, numeric route telemetry and synchronized Linux caret evidence in an authorized session. | Actual command ownership and audible usability require that live session. A viewer cannot certify tactile cells or physical keys. |
| b.note 80 | Driver source and official mappings establish intended commands. | Tactile readability, hardware routing/contact recognition and device timing require the connected display and operator feedback. |

Relevant suites are [Linux native-braille contracts](../tests/unit/braille/test_nvda_native_braille.py),
[cell alignment](../tests/unit/braille/test_braille_cell_alignment.py),
[Remote Access loopback](../tests/integration/test_nvda_remote_loopback.py),
[Windows companion tests](../nvda-addon/tests), and the
[Linux GUI workflow](../.github/workflows/linux-gui-accessibility.yml).
Five new [Unicode boundary tests](../nvda-addon/tests/test_unicodeOffsets.py)
exercise the real Linux snapshot, fragmented JSON decoding and companion
TextInfo hooks/routing with BMP, distinct supplementary characters, multiline
and combining text. They preserve an in-range provider shortfall instead of
silently correcting it. They are included in the **359-test Windows companion
pass** under Python 3.13 with declared `configobj==5.0.9` and CI-pinned NVDA
source `1406f9f8a04eb50f7317af87aba3a9d439c2a772`. Their provider/NVDA base are
doubles; this does not run installed NVDA or braille translation. The initial
Python 3.14 attempt lacked `configobj`; its failure remains in the development
evidence and is not counted as a complete suite pass.
Do all source, SSH, fixture and isolated-application checks before requesting
device feedback. Do not ask the operator to repeat those software checks.

On 2026-10-15, six existing Linux braille/loopback modules passed **170 tests,
zero failures/errors/skips** in a private Xvfb/D-Bus session. The invocation
was `python3 -B /tmp/lrd-nvda-acceptance-20261015-66Rth4/run_nvda_acceptance_contracts.py`;
its wrapper preloads real Atspi/GLib/GObject/Gio before the tests' `sys.modules`
mocks and uses private XDG directories. The initial plain combined invocation
is retained in `bridge-loopback.log`: 166 tests ran, one GI enum-registration
setup error prevented four tests from running, and one downstream long-text
snapshot assertion failed. Corrected-invocation output is retained in
`bridge-loopback-isolated.log` and `bridge-loopback-isolated-summary.json` in
the same remote directory. No production change or assertion relaxation was
made to obtain the passing result.

## Prepare a future live session

These are instructions for a separately authorized acceptance session, not
permission to change the current desktop, NVDA installation or device setup.
Use a disposable Linux login/test session connected to the bridge, temporary
application copies and public fixture files. Automated Xvfb sessions remain
private. Do not redirect the active production bridge to a test display.

Record Windows/NVDA/Remote Access/companion versions, keyboard layout and NVDA
modifier; Linux/Orca/bridge versions; VS Code/Electron/Chromium versions and
hashes; production build versus private experiment; connection/control state;
semantic versus raw mode; b.note model/firmware, USB or Bluetooth, driver,
reported 80-cell width, input/output tables, contraction/normalization,
cursor/selection visibility and focus/review tether. Redact connection keys.
Do not infer the device model from a negotiated width alone.

Keep the operator's established device settings for the first pass. If a
different braille table or tether is needed to diagnose a failure, document a
separate explicitly authorized test configuration and restore it afterwards.
The correction must not depend on undocumented changes to daily settings.

Use keyboard navigation throughout. `NVDA` means the operator's configured
modifier. In local control, `NVDA+n` opens the NVDA menu; arrows and Enter reach
Tools, Help and Preferences without mouse targeting. The official
[NVDA 2026.2 guide](https://api.nvaccess.org/releases/2026.2/documentation/userGuide.html#RemoteAccess)
documents `NVDA+alt+tab` for local/remote handoff and the Tools → Remote Access
menu for clipboard transfer. Verify commands for the installed version.

## Verify b.note commands before editing

Eurobraille's [b.note 64/80 product specification](https://www.eurobraille.com/produit/b-note-64-b-note-80/?print-products=pdf)
confirms the 80-cell model, routing keys and configurable controls. Its
two-contact routing controls make assumptions about press strength unsafe.
The older [2.3.0 manual](https://www.eurobraille.fr/wp-content/uploads/2023/12/b.note-Manual-2.3.0-UK.pdf)
describes 20/40-cell hardware; do not treat its default contact configuration
as a verified b.note 80 setting.

In **local control**, enable input help with `NVDA+1`, press each intended
physical gesture once, record the announced identifier/action, then leave
input help with the same keyboard command. Commands should be described
without execution. Confirm that no document edits/caret changes occur. The
[2026.2 Eurobraille command reference](https://api.nvaccess.org/releases/2026.2/documentation/userGuide.html#Eurobraille)
gives these defaults; recorded input help and installed bindings take priority:

| Device identifier | Intended action |
| --- | --- |
| `leftKeypadLeft` / `leftKeypadRight` | Pan backward / forward. |
| `rightKeypadLeft` / `rightKeypadRight` | Send keyboard Left / Right. |
| `routing` | Place the cursor using a displayed cell. |
| `doubleRouting` | Inspect formatting rather than move the caret. |

If a contact instead pans, opens a device menu or reports another command,
stop that case and record the binding; do not call it an application routing
failure. Do not guess a b.note return-to-focus chord from another Eurobraille
model. Identify the installed binding through NVDA Help/Input Gestures using
the keyboard; an unbound function is recorded as untested until an agreed
binding is available. Repeat input-help ownership checks in remote control
with the public fixture and synchronized observation before routing tests.

## Public fixture matrix

Create these UTF-8 documents automatically in the temporary Linux session.
Use LF for the multiline fixture. Counts exclude a trailing newline. Offsets
are zero-based boundaries and selection ranges are half-open `[start,end)`.

| Fixture | Exact content | Code points | UTF-16 units | Select-all range |
| --- | --- | --- | --- | --- |
| ASCII | `a cafe omega` | 12 | 12 | `[0,12)` |
| BMP | `a café omega` | 12 | 12 | `[0,12)` |
| One supplementary character | `a🙂 café omega` | 13 | 14 | `[0,13)` |
| Distinct supplementary characters | `a🙂🚀 café omega` | 14 | 16 | `[0,14)` |
| Multiline | `a🙂 café` then LF then `omega🚀` | 14 | 16 | `[0,14)` |

For the one-emoji document, boundaries 1 and 2 surround 🙂. For the two-emoji
document, `[1,3)` covers both and `[2,3)` covers only 🚀. In the multiline
document LF occupies `[7,8)` and 🚀 occupies `[13,14)`. These fixtures avoid
ambiguous grapheme clusters; combining/ZWJ sequences need separate expected
editor movement rules and must not be claimed from these results.

## Keyboard and physical acceptance sequence

Perform each case once per recorded configuration and retain failures. New
attempts must have a new result entry; they do not erase the first failure.

1. **Establish ownership.** From local control, hand off to the designated
   Linux test session. Open the public document through the application
   keyboard interface. Confirm the editor's name/role, focus and text in
   Windows speech and braille. Hand back and forward once; no queued key,
   speech or routing action may affect the wrong session.
2. **Verify Unicode selection.** Use Ctrl+Home then Ctrl+Shift+End. Compare
   native provider offsets, semantic payload and document text against the
   table. Record what Windows announces and the actual tactile selection.
   Repeat selection in reverse, select the emoji alone and both distinct
   emoji, then collapse in both directions. Readable text with an off-by-one
   selection remains a failure.
3. **Route and continue.** Collapse selection. Locate the displayed emoji
   through its surrounding text; use the verified routing contact for the
   cell representing the position after `a` (code-point offset 1). Record one
   physical gesture, Windows route telemetry, Linux receipt/provider write,
   AT-SPI readback and tactile cursor separately. Press keyboard Right once:
   caret must be 2; Left once: caret must be 1. Repeat with verified b.note
   right-keypad arrows. Type `X`, require `aX🙂…`, then undo. A moving braille
   cursor alone does not pass routing.
4. **Selection continuation.** At offset 1, Shift+Right selects 🙂 with range
   `[1,2)`. Type `X` to replace it, verify exact document text, then undo.
   For two emoji, verify `[1,3)` and `[2,3)` before replacement and undo.
   Include keyboard navigation across LF and selection ending after 🚀.
5. **Clipboard and focus.** Copy the exact selected public substring, paste
   into a second temporary document and compare code points; undo. Cut,
   verify the original lost precisely that selection, paste/undo/restore.
   Separately test Remote Access clipboard transfer using only a public
   fixture. Local application clipboard success does not establish remote
   clipboard transport. Open VS Code's command palette with Ctrl+Shift+P,
   dismiss with Escape, confirm editor focus and route/Right/Left again.
6. **Find.** In VS Code use Ctrl+f, search for each distinct emoji and the
   suffix, then Escape and confirm focus/keyboard continuation. Record editor
   search separately from the real Electron find-in-page fallback probe;
   VS Code's search widget does not establish that Chromium fallback path.
7. **80-cell behavior.** Use an automatically generated public ASCII line
   longer than two display widths with numbered landmarks. Pan both ways;
   test visible cells 1, 40 and 80 before and after panning, accounting for
   role/context cells and the active translation map. Repeat with Unicode
   embedded near a window boundary. Confirm tactile text and cursor, correct
   routed position and keyboard continuation. Do not assume cell 80 means
   text offset 79. Repeat under the operator's usual contracted table if it
   differs from the first configuration.
8. **Speech/messages and recovery.** Interrupt reading with routing and the
   verified return-to-focus command; stale reading must not undo the route.
   Check ordinary panning against the recorded speech-interruption setting.
   Trigger a benign temporary status message, dismiss it with routing, and
   verify restored text/cursor without an unintended edit. Hand back to
   Windows, reconnect only the disposable test endpoint, then verify that
   stale routes and held modifiers do not replay. Keep semantic and raw
   fallback results separate; do not force fallback by modifying production
   configuration.

## Record a result without conflating evidence

Use one accessible text record per case; speak or type observations while
the observer timestamps numeric Linux events. Preserve the unedited failed
record before diagnosis. Public fixture content may be retained, but exclude
connection keys, private clipboard contents and unrelated application text.

```text
Case and configuration:
Build type and application/native/renderer hashes:
NVDA / Remote Access / companion / Orca / bridge versions:
Device model / firmware / driver / connection / width / tables / tether:
Control owner / semantic or raw / focused application:
Action and physical gesture identifier:
Expected text / selection / caret / next keyboard result:
Observed native and semantic offsets, with timestamps:
Observed Windows speech and route telemetry:
Observed tactile text / selection / cursor / physical-key behavior:
Result: PASS / FAIL / NOT RUN, with reason:
Evidence paths and initial failure reference:
```

Production readiness requires the source correction to be integrated into
the actual shipped Chromium/Electron/VS Code dependency chain, relevant
upstream/native regression coverage, live Windows NVDA acceptance and actual
physical-braille results. Passing this document's preparation checks, private
binary experiments or CI does not authorize merging a PR or closing #79.
