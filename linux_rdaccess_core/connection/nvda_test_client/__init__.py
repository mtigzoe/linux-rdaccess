"""Windows-only local test IPC client shared with mtigzoe/rdAccess PR #10.

The four localTest modules are vendored verbatim from the Windows add-on so
framing, DPAPI, schema validation and MAC rules agree. No NVDA runtime imports
are required by this client. Importing it does not open any endpoint or file.
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
