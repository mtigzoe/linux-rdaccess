# Compatibility audit: temporary Orca braille messages in semantic braille mode

Date: 2026-10-10. Scope: `linux-rdaccess` sender and the matching `mtigzoe/rdAccess` receiver.

## Finding (Automated-tested)

With real Orca 42.0 `braille.displayMessage("Focus mode", flashTime=5000)` and the shipped refresh hook in NVDA-native semantic braille mode, Orca showed the message locally but nothing was sent to Windows: the hook only sends a changed `lrd_a11y_focus` snapshot. Raw `display` cells cannot carry it because Windows NVDA ignores them while `receivingBraille` is False (NVDA `LocalMachine.display`, read in `master` and tag `release-2026.2`).

## Decision

Temporary status messages must reach NVDA braille in semantic mode, but NVDA keeps control of the semantic focus, caret, routing and panning presentation. Raw cells are not forwarded.

## Protocol

- Windows advertises `message_version=1` in `lrd_a11y_capability`. Each capability replaces the previous one.
- Linux wraps Orca's `braille.displayMessage` once a peer opts in. A non-zero flash time (positive, or `-1` persistent) sends `lrd_a11y_message` (`version`, `text`). A flash time of 0 is a permanent display and is not a temporary message.
- Windows presents the text with `braille.handler.message` on NVDA's main thread, so the message uses a separate buffer and the semantic focus buffer is untouched.
- Text is bounded to 256 characters, control/format/separator characters become spaces, text is never logged, and nothing is queued or replayed after reconnect, fallback or session change.

## Compatibility

- Older Windows add-on: it never advertises the feature, so Linux never sends the message. NVDA's built-in transport would only log and ignore an unknown type.
- Older Linux build: `lrd_a11y_capability` handlers that accept extra keyword arguments ignore `message_version`; the Windows side never receives the message type.
- Orca 42.0: `displayKeyEvent` (Caps Lock and Num Lock) calls the module-level `displayMessage`, so it goes through the forwarder.

## Test evidence

- Automated-tested (Linux): sanitizer unit tests and loopback wire tests for send, flash-time rules, persistent and positional flashes, sanitizing and bounds, no replay before negotiation, reconnect withdrawing support, an older peer, repeated capability not stacking forwarders, fallback, send failure keeping Orca's display and never logging text. A probe against real Orca 42.0 `orca.braille` confirmed both direct `displayMessage` and Orca's Caps Lock path produce the message.
- Automated-tested (Windows, `rdAccess`): receiver tests over the callback and built-in transport paths.
- Not live-tested: Windows NVDA display rendering, "Show messages" and timeout behavior, routing-key dismissal, panning during a message and physical braille output. See the live-validation table in issue #59.
