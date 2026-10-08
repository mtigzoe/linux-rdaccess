# Developer tools

The tools are grouped by purpose; run commands from the **repository root**.

## Accessibility protocol fixture generators

`tools/a11y/` contains `generate_remote_a11y_*.py` and
`decode_remote_a11y_action.py`. These are used by the Linux ↔ rdAccess
semantic contract in GitHub Actions.

## Diagnostics and manual smoke checks

```sh
python3 tools/diagnostics/gtk_atspi_smoke.py
python3 tools/diagnostics/orca42_d_landmark_check.py
python3 tools/diagnostics/summarize_input_trace.py --timeline
python3 tools/diagnostics/xkb_lock_state.py
```

Some tools require Linux, the Orca/X11 environment, or external test
dependencies. Refer to the README and dedicated diagnostics documentation.

## Windows NVDA speech probe

The installer and packaged NVDA add-on live together in `tools/nvda/`.

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\nvda\install_nvda_speech_probe.ps1
```

Keep `tools/nvda/nvda_speech_probe/` alongside the installer: the
PowerShell installer resolves this add-on folder relative to its own file.

Do not silently move these paths again: tests, workflows, and operator
documentation invoke them directly.
