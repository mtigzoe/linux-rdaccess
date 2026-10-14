# IPC source attribution

`localTestIpc.py`, `localTestRequest.py`, `localTestTransport.py` and
`localTestWindows.py` were originally vendored from mtigzoe/rdAccess PR #10.
They are RDAccess code, Copyright 2026 RDAccess contributors, licensed under
GNU GPL version 2 or later. Their license is not replaced by the Linux
repository's root Apache-2.0 license. The full license is available in
[`nvda-addon/COPYING.txt`](../../../nvda-addon/COPYING.txt).

This directory is now the authoritative IPC source for the Linux project's
Windows launcher and the companion NVDA add-on. The companion builder packages
these four files verbatim, without maintaining a second source copy. Wire
changes must preserve or explicitly version compatibility with existing
consented RDAccess endpoints. See
[`nvda-addon/NOTICE.md`](../../../nvda-addon/NOTICE.md) for upstream revisions.

`localTestRoutingTrace.py` is an additional project-authored GPL-2.0-or-later
module, packaged verbatim by the companion builder. Its optional diagnostic
read is explicitly versioned separately from the original version 1 operations.
