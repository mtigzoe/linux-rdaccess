# Issue #61: Connected Orca + transport recovery acceptance

## What the existing CI proves

- PR #105 uses disposable TCP sockets and a patched fixture of the pinned
  Orca Remote transport. Its native reconnection worker handles multiple
  disconnects; the compatibility controller is fixture-backed.
- PRs #103, #106, and #107 launch a real Orca process in a private Xvfb/D-Bus
  session and coordinate isolated transport checks. **Those transports are
  not installed into, or connected to, the running Orca process.**
- Accordingly, none of those checks proves actual Orca Remote extension
  loading, in-process controller lifecycle after Orca crashes, real NVDA
  speech output, or hardware braille recovery.

## Required next integration test

Run only on a disposable Linux runner; never inherit a user's DISPLAY,
DBUS_SESSION_BUS_ADDRESS, XDG directories, saved channel key, or Orca profile.

1. Create private HOME/XDG configuration, Xvfb and D-Bus, plus a relay
   bound exclusively to 127.0.0.1 with a randomly generated test-only key.
2. Stage and patch the pinned Orca Remote extension and
   `orca-customizations.py` using the same production installation functions.
   Verify the patched files compile and are loaded by **real Orca**, rather
   than a separate Python process using fixture modules.
3. Instrument the extension's lifecycle through a test-only local control
   channel/marker that reports startup, real transport connection, and
   disconnect; do not infer readiness from a three-second sleep.
4. Establish an authenticated session with the local relay. Drive a held
   modifier and queue Orca-side work; drop the TCP connection during a partial
   protocol message. Assert modifier release and expiration of old callbacks.
5. Kill the isolated Orca process while the connection is active. Assert
   transport teardown and no lingering sender/reconnector workers or keys.
   Restart Orca in the same isolated private session and verify it reloads
   the patched extension, reconnects, and accepts **new** input without
   replaying old input/output.
6. Stop all child processes and check for leaks. A timeout, missing observer,
   or skipped assertion must fail the CI job, not count as a pass.

## Distinct manual hardware acceptance (still outstanding)

A separate consented Windows NVDA + Linux Mint + physical braille test must
verify speech interruption, panning/routing, ownership of semantic braille,
and behavior on disconnect/reconnect. Do not close issue #61 based on the
isolated automation alone.

## Safe implementation order

First build a test-only extension-loaded readiness signal; then wire the
private relay and assert a genuine session. Only after that add fault
injection and process-death recovery. Avoid another concurrent-only Orca
smoke test, because it would not establish the missing integration.
