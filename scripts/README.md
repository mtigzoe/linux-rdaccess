# Session helpers

Optional Windows PowerShell helpers live in `windows/`.

Run from the repository root:

```powershell
.\scripts\windows\start-windows-session.ps1
.\scripts\windows\start-windows-session.ps1 -Configure
.\scripts\windows\stop-windows-session.ps1
```

These scripts call the root `linux_rdaccess_windows.py` controller with `uv` and SSH. They do not launch or connect the NVDA Remote Access add-on. See the main README for prerequisites.

## Linux shell helpers

The Linux shell implementation scripts are in `scripts/linux/`:

```bash
./scripts/linux/start-orca-session.sh
./scripts/linux/start-orca-remote.sh
DISPLAY=:10 ./scripts/linux/run_braille_bridge.sh --check
```

The original root commands remain executable compatibility wrappers. They
forward all arguments to the corresponding scripts in `scripts/linux/`.
The braille bridge script resolves `atspi_nvda_braille_bridge.py` relative to
the repository root, even if called from a different working directory.
CI checks syntax using `bash -n scripts/linux/*.sh` and validates the wrappers.

Do not run the Orca restart scripts as an unattended test on an active accessible
desktop: they replace the active Orca process.
