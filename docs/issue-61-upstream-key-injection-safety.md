# Issue #61 — upstream local-key injection safety finding

Pinned upstream: `serrebidev/orca-remote@d273e82fbc93bf6a6eb473a00e38291d84f1dccb`.

The test in PR #112 currently **fails by design** because the production
`_patch_local_key_results()` cannot safely infer the success of
`LocalMachine.send_key()` in this upstream revision.

## Verified control flow

1. `send_key()` resolves the key name and immediately adds or removes it
   from `self._held_keys`, **before** attempting input injection.
2. It invokes `self._inject(key, pressed)` but does not return a result.
3. `_inject()` attempts portal/ydotool on Wayland, and
   xdotool/ydotool/portal on X11. It returns **None** on success, on
   denial, and when all backends fail.
4. Thus a true/false delivery result cannot be recovered at the
   `send_key()` call site without changing `_inject()` and carefully
   reviewing held-key ownership.

## Why merely allowlisting self._inject is unsafe

An unconditional `return True` after `self._inject()` could acknowledge
failed key presses or releases. That can leave a stuck key, drop a retry,
or let a stale release affect a replacement session. The present rejection
is therefore preferable to a false-success compatibility shim.

## Implementation requirements for a production fix

- Match a verified upstream AST shape; reject unexpected helper bodies and
  any unrecognized injection side effects.
- Preserve backend order and Wayland portal-denial semantics.
- Return booleans from the injection helper only when backend outcomes are
  known; map all failed/denied branches to false.
- Couple held-key ownership to **observed** delivery. If key release fails,
  keep ownership for a later cleanup/retry; if key press fails, do not claim
  a held key. Account for auto-repeat and release-without-owned-key.
- Add tests for X11 and Wayland, each backend succeeding/failing, portal
  denial, exception, repeated keypress, failed release + retry, disconnect,
  and the existing changed-upstream fail-closed conditions.
- Run the pinned-real-upstream CI and full suite before merging. Maintain
  issue #61 open pending integrated NVDA/braille acceptance.

No production workaround has been applied.
