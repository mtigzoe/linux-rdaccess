# Developer tools

The tools are grouped by purpose; run commands from the **repository root**.

## Accessibility protocol fixture generators

`tools/a11y/` contains `generate_remote_a11y_*.py` and
`decode_remote_a11y_action.py`. These are used by the Linux ↔ rdAccess
semantic contract in GitHub Actions.

Run the individual generators from the repository root:

```bash
python3 tools/a11y/generate_remote_a11y_fixture.py
python3 tools/a11y/generate_remote_a11y_role_matrix.py
python3 tools/a11y/generate_remote_a11y_state_matrix.py
python3 tools/a11y/generate_remote_a11y_navigation_fixture.py
python3 tools/a11y/generate_remote_a11y_action_fixture.py
python3 tools/a11y/generate_remote_a11y_text_fixture.py
```

The decoder `tools/a11y/decode_remote_a11y_action.py` accepts an encoded
action request on standard input. GitHub Actions runs this contract check.

## Diagnostics and manual smoke checks

```sh
python3 tools/diagnostics/gtk_atspi_smoke.py
python3 tools/diagnostics/orca42_d_landmark_check.py
python3 tools/diagnostics/summarize_input_trace.py --timeline
python3 tools/diagnostics/xkb_lock_state.py
python3 tools/diagnostics/run_routing_simulation.py
```

Some tools require Linux, the Orca/X11 environment, or external test
dependencies. Refer to the README and dedicated diagnostics documentation.

`run_routing_simulation.py` creates a private GTK/Xvfb/D-Bus test desktop,
previews a target, routes its caret from 2 to 7, checks the event and readback,
and verifies that reusing the stale preview is refused. It does not touch the
active desktop or require a physical display. For an explicitly approved
existing Mousepad target, use
[`diagnostics/atspi/simulate_routing.py`](../diagnostics/atspi/simulate_routing.py).

## Windows NVDA speech probe

The installer and packaged NVDA add-on live together in `tools/nvda/`.

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\nvda\install_nvda_speech_probe.ps1
```

Keep `tools/nvda/nvda_speech_probe/` alongside the installer: the
PowerShell installer resolves this add-on folder relative to its own file.

Do not silently move these paths again: tests, workflows, and operator
documentation invoke them directly.
