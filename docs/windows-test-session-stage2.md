# Authorized Windows test-session workflow

Build and review the [Linux Remote Access Companion](../nvda-addon/README.md)
maintained in this repository, then install it into your chosen Windows NVDA
copy. An older RDAccess PR #10 endpoint remains compatible with this launcher,
but a development RDAccess build with the Linux integration must be disabled
before enabling the companion to prevent duplicate handlers and consent menus.
Installation/reload into a running NVDA session requires separate explicit
authorization during agent-assisted development. Build `20261013.0.1` has been
installed and activated in Windows NVDA, with authenticated connection/status
and one user-confirmed physical Firefox panning observation. Broader keyboard,
speech, routing, caret and lifecycle acceptance remains incomplete; see the
[live audit](compatibility-audit-2026-10-13-companion.md).

Configure NVDA's built-in Remote Access saved relay settings as **Control
another computer**. The relay must have a valid certificate or an already
trusted fingerprint. Self-hosted and controlled-computer profiles are rejected.
Configure Linux Remote Access and the existing Orca session separately. The
SSH controller must already have saved settings, authentication and a verified
host key. The launcher never accepts relay credentials as arguments.

1. In NVDA Tools, choose **Authorize Linux test session…**.
2. Check **Allow connection using saved Remote Access relay settings** if a
   new Windows connection is wanted. It is unchecked by default.
3. Activate **Authorize for five minutes**. Wait for the ready announcement.
4. From this repository on Windows, run:

   ```powershell
   python .\linux_rdaccess_test_session.py start-all
   ```

`start-all` checks Linux readiness over read-only SSH and connects Windows
using the authenticated local pipe. It reuses pre-existing Remote Access
connections and does not restart NVDA or Orca, load add-ons, send keystrokes,
change relay settings or bypass certificate verification. The current Linux
connect API normally restarts Orca; it is therefore not invoked. If the saved
Linux setup is incomplete, the command reports `setup_required`. A configured
Linux session still needs to be running and connected/reconnecting normally.

Use `nvda-status` to query authorized status, and `cancel` to cancel only the
connection created by this consent session. Revoke authorization in NVDA Tools
to close the endpoint and delete the encrypted discovery file. Authorization
also ends after five minutes, on profile changes, lock, secure-desktop entry,
or NVDA shutdown. Session-owned connections are cleaned up at that boundary;
pre-existing connections are preserved.

For bounded live input checks, prepare the read-only observer and select a safe
Windows input target before asking for fresh consent. Recheck `nvda-status`
immediately before input: authorization must be active, the transport connected,
and remote control confirmed. A successful `start-all` does not establish
keyboard control. Send one gesture, inspect the Linux focus/event result, and
then choose the next action. If the computer-use helper detects user input,
refresh its window state and recheck control/consent before one retry. Do not
attribute a concurrent focus change to a blocked or unknown input attempt.

Avoid broad speech/braille log windows when the user is also navigating Windows:
they can contain unrelated local output. A timed observer must still be running
when the gesture is sent; a zero-event trace that ended beforehand does not prove
the key failed to reach Linux. Stop input when consent expires, even if an
observer was just prepared, and request a fresh session for further live input.

The discovery file is `%LOCALAPPDATA%\rdaccess-test-session.bin`: user-scoped
DPAPI ciphertext, created with a protected user-only DACL. It contains an
ephemeral pipe key, never the saved relay password. `--session-file` accepts an
alternate encrypted descriptor for isolated testing. Do not copy or commit
descriptor files. Neither endpoint addresses nor keys appear in JSON output.

The IPC modules in `linux_rdaccess_core/connection/nvda_test_client` originated
in rdAccess PR #10 and are now the authoritative source in this repository.
The companion build packages those files verbatim. Preserve/version existing
wire compatibility when changing them. The standalone `nvda-addon/tests` suite
exercises real Windows kernel transport, DPAPI, ACLs and cancellation in isolated
temporary endpoints; launcher orchestration tests use isolated mocks.

Legacy NVDARemote connections can be queried/reused when already active.
Automatic connection of the legacy add-on is unavailable because its API
cannot provide bounded GUI-thread cleanup. Manual compatibility is preserved.

A connected relay does not prove an active Linux peer, speech output,
semantic-braille negotiation, or physical display output. `start-all` reports
these separately and leaves physical braille `unverified`. Use the normal
Remote Access control shortcut yourself when ready; keyboard injection is
never an IPC action. End-to-end NVDA/Orca/physical braille acceptance remains
separate consented live testing.
