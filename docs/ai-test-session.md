# AI-assisted Windows test session (Stage 1)

This **Windows-side** tool provides noninteractive, machine-readable readiness
checks for Codex/Claude. It reuses the existing SSH configuration in
`%APPDATA%\\linux-rdaccess\\windows-config.json`. It does not require an
additional relay key or store credentials.

Run from **Windows PowerShell** in a local Windows checkout:

```powershell
python .\\linux_rdaccess_windows.py configure
python .\\linux_rdaccess_test_session.py status
python .\\linux_rdaccess_test_session.py doctor
```

The JSON output includes only allowlisted Linux configuration booleans,
SSH reachability, and whether a Windows NVDA process is running. It intentionally
does not expose the relay address, username, key, SSH command output or process
details. Its `windows_remote_connected`, `semantic_braille_negotiated`, and
`physical_braille` fields are **unverified**, not fabricated success signals.
SSH reachability and `ready: true` do *not* mean NVDA is connected.

To authorize running the **existing Linux connect command**, which may
restart Orca and interrupt access, use this only when ready:

```powershell
python .\\linux_rdaccess_test_session.py start --confirm-start
```

This starts the Linux side **only**. You must still connect the Windows
NVDA Remote Access add-on manually using its existing configuration. Do not
put relay keys in commands, GitHub issues, code, or AI prompts.

For unattended AI use, prefer `status` or `doctor`. The tool uses SSH
batch mode and requires a *previously trusted* SSH host key; unfamiliar hosts
fail without interactive trust prompts. If the SSH key is not set up, use the
existing interactive Windows controller to configure access yourself.

```powershell
python -m unittest tests.unit.test_windows_test_session -v
```

Stage 2 would require a separately reviewed, local authenticated Windows
NVDA add-on control interface with explicit user consent before it could
connect the Windows side or run live keyboard tests. **Stage 2 is not part of
this PR.** Desktop Commander, Remote-SSH and terminal access do not themselves
prove that an AI has GUI input, NVDA speech observation or physical braille
observation capabilities.
