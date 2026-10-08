# Windows SSH controller

The optional `linux_rdaccess_windows.py` utility runs on Windows and invokes the
**installed Linux** `linux-rdaccess` command over OpenSSH. It does not replace
the Windows NVDA Remote add-on or the Linux Orca accessibility bridge.

Requirements: Python 3.10+, Windows OpenSSH client (`ssh` in PATH), SSH access
to a Linux machine, and `linux-rdaccess` installed and available in the remote
non-interactive SSH PATH. Enable the Linux desktop session before connecting.
The Linux CLI already searches for the active graphical session when restarting Orca.

Run from PowerShell in a checkout of the repository:

```powershell
python .\linux_rdaccess_windows.py configure
python .\linux_rdaccess_windows.py status
python .\linux_rdaccess_windows.py connect
python .\linux_rdaccess_windows.py doctor
python .\linux_rdaccess_windows.py compatibility
python .\linux_rdaccess_windows.py disconnect
```

Run `python .\linux_rdaccess_windows.py` without an action for an accessible,
numbered text menu. The first-time setup asks for Linux host, SSH username and
SSH port, then writes `%APPDATA%\linux-rdaccess\windows-config.json`.
On non-Windows development machines, it uses
`~/.config/linux-rdaccess/windows-config.json` instead.

**Never commit the generated config file.** No account or host details are baked
into repository source. Authentication and SSH host-key verification use the
system OpenSSH client; SSH keys stay in the user's usual SSH key storage.
Verify the SSH server fingerprint when first prompted.

The controller runs only a fixed allowlist of remote CLI subcommands; it does
not accept arbitrary remote shell commands. It returns the SSH process exit
status. A successful SSH command indicates the Linux CLI ran successfully, not
that Windows NVDA speech and braille have been independently verified.
If the command is not found remotely, arrange for the installed
`~/.local/bin` directory to be on the non-interactive SSH PATH.

Unit tests (do not require Linux, SSH access or NVDA):

```powershell
python -m unittest discover -s tests -p "test_windows_controller.py"
```
