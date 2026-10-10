# Read-only diagnostics MCP prototype

This is a developer-only MCP stdio adapter around existing diagnostics, not a replacement for xa11y or NVDA Remote. It does **not** type, click, screenshot, reconfigure Orca, or alter the user's connection.

## Start from the Linux Mint session

From the repository root:

```sh
/usr/bin/python3 tools/mcp/linux_rdaccess_mcp.py
```

Codex configuration (adjust absolute paths for the installation):

```sh
codex mcp add linux-rdaccess-diag -- /usr/bin/python3 /home/miriam/linux-rdaccess/tools/mcp/linux_rdaccess_mcp.py
codex mcp list
```

The MCP client must inherit the **actual Linux XFCE graphical session** environment. Confirm `DISPLAY`, `XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`, and `XDG_RUNTIME_DIR`. VS Code Remote-SSH does not automatically guarantee working AT-SPI access.

## Tools

- `atspi_status`: Counts AT-SPI application entries without returning names, optional integer `limit` (0–20).
- `atspi_event_counts`: Runs the existing redacted AT-SPI event probe for 1–15 seconds; optional integer `seconds`.
- `x11_status`: Executes the existing read-only X11 status diagnostics using the inherited local `DISPLAY`.

Commands and arguments are allowlisted. Each subprocess has a timeout and bounded output, and stderr is not exposed on failure. This is observation-only and **cannot verify NVDA speech, braille, or remote keyboard translation**.

Run unit tests:

```sh
python3 -m unittest discover -s tests/unit/mcp -p 'test_*.py' -v
```

See [live xa11y guidance](../.github/XA11Y_LIVE_TESTING.md) for the distinction between Linux AT-SPI inspection and actual NVDA Remote end-to-end testing. The server is not a production dependency and should not be deployed as a background service.
