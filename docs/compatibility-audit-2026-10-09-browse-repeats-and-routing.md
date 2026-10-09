# NVDA–Orca browse repeat and braille routing audit

Base: `main` at `af02a56`, containing PR #38.
Branch: `fix/nvda-orca-browse-repeats-and-routing`.

## Confirmed defects

### Held NVDA browse commands lost translation on repeat

The controller published a remote command claim only for the first press of
NVDA+V, NVDA+Ctrl+F, NVDA+F3/Shift+F3, and NVDA+Shift+F10. Their repeated
presses were still injected, but without a claim. Orca could run an unrelated
native binding or pass the key to an application, including outside document
content where the first press was deliberately consumed.

The controller now publishes a separate claim for each press while the exact
NVDA chord is held. Orca makes the same document/context decision for repeats
as for the first press. Find Previous retains Shift direction. Releasing the
NVDA modifier still permits ordinary repeats, preserving PR #38's application
release behavior. Local Linux keys do not acquire these remote claims.

The [upstream NVDA screen-layout handler](https://github.com/nvaccess/nvda/blob/master/source/browseMode.py)
confirms NVDA+V's document-layout meaning. The change preserves that command
identity; it does not establish Windows auto-repeat timing or debounce parity.
Controller v105 upgrades to v106 through the existing private backup path.

### Raw braille routing accepted invisible cell positions

The receiver bounded routing coordinates using the last remote display width,
but the adapter only checked the protocol maximum of 1024. Orca's local
BrlAPI initialization can replace `_displaySize` after a command is received.
An 80-cell remote coordinate such as 79 therefore reached native routing even
after Orca's viewport became 20 cells. A peer without display information could
also route beyond Orca's default viewport.

The adapter now checks current native geometry immediately before calling the
active script on Orca's main loop. Out-of-range positions and malformed
geometry return False, preventing legacy fallback from retrying the rejected
command. In-range routing still works. The older API path remains available
when Orca does not expose `_displaySize`.

Orca's native `processRoutingKey()` adds the supplied cell to `viewport[0]`
without enforcing the display width. The native routing/Liblouis fixture
reproduces a caret move to the ninth cell of an eight-cell viewport. The
disposable TCP test also orders a real protocol receipt before the local
geometry change and verifies rejection on main-loop execution.

## Evidence and focused validation

Before changing production code, six new test methods produced **10 assertion
failures**, including subtests: seven browse-repeat failures, two controller
routing failures, and one native braille routing failure. All pass after the
fix. Further regressions cover Shift+F3 with Insert/Caps Lock in both layouts,
invalid native geometry, and the queued TCP routing case.

| Check | Result |
| --- | --- |
| Browser context, display lifecycle, native braille alignment, Orca adapter | 108 passed |
| Additional modifier/geometry cases, legacy controller, pass-next, upgrades, patch integrity, trace, braille protocol/semantics/hooks | 394 passed |
| Disposable NVDA Remote TCP loopback, including queued geometry change | 23 passed |
| Actual v105 output from the saved original generator, upgraded to v106 | Passed; original backup retained; private modes preserved; second update was a no-op |
| Changed Python compilation and whitespace checks | Passed |

All **525 focused test executions** passed on Python 3.10.12 with zero skips.
The loopback suite ran with permission to create its disposable localhost
sockets. No user's relay, credentials, active desktop, installed runtime, or
physical keyboard state was used or changed.

## Limits

The full suite, GUI acceptance, live Windows NVDA/Orca interaction, audible
speech, and physical braille devices were not tested. Fixture/native-source
coverage and localhost framing do not establish end-to-end device behavior.

The routing fix rejects positions outside a known native viewport; it does not
invalidate all same-focus text or viewport changes, reapply the remote width
after local BrlAPI reconnect, or add geometry identifiers to the protocol.
Orca versions without `_displaySize` retain the previous protocol-bound check.

Later live checks should hold each affected browse shortcut in document
content and browser chrome, release its modifiers during a hold, and confirm
subsequent typing. For braille, reconnect a smaller local display while remote
routing is queued, verify invisible cells cannot move the caret, and verify
visible routing, panning, and reconnect cleanup still work.
