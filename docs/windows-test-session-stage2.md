# Authorized Windows test-session workflow

Install a build of RDAccess PR #10 into your chosen NVDA copy after reviewing
that PR. Installation/reload into a running NVDA session requires separate
explicit authorization during agent-assisted development.

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

The discovery file is `%LOCALAPPDATA%\rdaccess-test-session.bin`: user-scoped
DPAPI ciphertext, created with a protected user-only DACL. It contains an
ephemeral pipe key, never the saved relay password. `--session-file` accepts an
alternate encrypted descriptor for isolated testing. Do not copy or commit
descriptor files. Neither endpoint addresses nor keys appear in JSON output.

The IPC client modules in `linux_rdaccess_core/connection/nvda_test_client`
are vendored verbatim from rdAccess PR #10. Update them together when the wire
protocol changes. Windows tests in that PR exercise the real kernel transport,
DPAPI, ACLs and cancellation; orchestration tests here use isolated mocks.

Legacy NVDARemote connections can be queried/reused when already active.
Automatic connection of the legacy add-on is unavailable because its API
cannot provide bounded GUI-thread cleanup. Manual compatibility is preserved.

A connected relay does not prove an active Linux peer, speech output,
semantic-braille negotiation, or physical display output. `start-all` reports
these separately and leaves physical braille `unverified`. Use the normal
Remote Access control shortcut yourself when ready; keyboard injection is
never an IPC action. End-to-end NVDA/Orca/physical braille acceptance remains
separate consented live testing.
