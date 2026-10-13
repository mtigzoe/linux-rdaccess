"""Windows-only local test IPC client, originally from mtigzoe/rdAccess PR #10.

The four localTest modules are the authoritative source for the launcher and
the companion NVDA add-on, whose builder packages them verbatim. See NOTICE.md
for GPL-2.0-or-later attribution. No NVDA runtime imports are required by this
client. Importing it does not open any endpoint or file.
"""

from __future__ import annotations

from pathlib import Path

from .localTestTransport import descriptorPath, loadDescriptor, request


class AuthorizedClient:
    """Credentials stay in memory and never appear in CLI arguments or output."""

    def __init__(self, path: Path | None = None):
        self._address, self._key = loadDescriptor(path or descriptorPath())

    def operation(self, action: str) -> dict:
        return request(self._address, self._key, action)
