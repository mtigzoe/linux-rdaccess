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

## Optional Windows NVDA launch

From a **Windows-local** PowerShell (not a Remote-SSH Linux terminal), first
check whether NVDA is already running:

```powershell
python .\\linux_rdaccess_test_session.py status
```

If NVDA is not running, the launcher can request a normal launch using an
explicitly specified installed executable:

```powershell
python .\\linux_rdaccess_test_session.py launch-nvda --confirm-launch --nvda-path "C:\\Program Files (x86)\\NVDA\\nvda.exe"
```

Adjust the executable path to match your installation. This will **not**
terminate, restart, or reconfigure an NVDA process that is already running.
The process being launched is not proof that the Remote Access add-on is
connected. You must still connect the Windows add-on manually until the
separately reviewed opt-in Stage 2 interface is implemented.

To authorize the existing Linux-side connect command (which may restart Orca):

```powershell
python .\\linux_rdaccess_test_session.py start --confirm-start
```

Do not run `launch-nvda` through a Linux Remote-SSH terminal; this command is
Windows-only. Nothing here types relay credentials or injects keys.

## Combined preparation command

From **Windows-local** PowerShell, authorize both the Linux connection and
the launch of NVDA (if it is not already running):

```powershell
python .\\linux_rdaccess_test_session.py prepare --confirm-start --confirm-launch --nvda-path "C:\\Program Files (x86)\\NVDA\\nvda.exe"
```

This runs the Windows NVDA launch check first, then invokes the existing
Linux connect command through SSH. It preserves an already-running NVDA
process, does not send the channel key, and prints machine-readable JSON.
**It does not connect the Windows NVDA Remote Access add-on.** The remote
transport and braille status remain unverified until Stage 2 supplies a
separately authorized Windows add-on interface. The Linux connect command
may restart Orca, so run `prepare` only when both actions are authorized.
