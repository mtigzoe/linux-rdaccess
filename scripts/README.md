# Session helpers

Optional Windows PowerShell helpers live in `windows/`.

Run from the repository root:

```powershell
.\scripts\windows\start-windows-session.ps1
.\scripts\windows\start-windows-session.ps1 -Configure
.\scripts\windows\stop-windows-session.ps1
```

These scripts call the root `linux_rdaccess_windows.py` controller with `uv` and SSH. They do not launch or connect the NVDA Remote Access add-on. See the main README for prerequisites.
