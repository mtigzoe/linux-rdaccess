"""The adapter and model as installed into Orca's scripts directory.

update_legacy_orca_customizations() copies them as linux_rdaccess_orca_adapter.py and
linux_rdaccess_a11y_model.py. Importing only from the repository layout hid that the
installed adapter could not find its model, so semantic braille silently never worked.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Runs in a clean interpreter whose only importable project files are the installed ones.
PROBE = r'''
import json, sys, types

class State:
    def __init__(self, nick): self.value_nick = nick

class StateSet:
    def __init__(self, *names): self.names = [State(n) for n in names]
    def get_states(self): return self.names

class Node:
    def __init__(self, name, role, parent=None, *states):
        self.name, self.role, self.parent, self.states = name, role, parent, states
    def get_name(self): return self.name
    def get_role_name(self): return self.role
    def get_parent(self): return self.parent
    def get_state_set(self): return StateSet(*self.states)
    def get_child_count(self): return 0

orca_state = types.ModuleType("orca.orca_state")
orca = types.ModuleType("orca")
orca.orca_state = orca_state
sys.modules.update({"orca": orca, "orca.orca_state": orca_state})
app = Node("Smoke App", "application")
orca_state.locusOfFocus = Node("Apply changes", "push button", app, "focusable", "enabled")

import linux_rdaccess_orca_adapter as adapter
assert "a11y_model" not in sys.modules
payload = adapter.OrcaRuntimeAdapter.semantic_focus_payload()
names = {} if payload is None else {o["id"]: o["name"] for o in payload["objects"]}
orca_state.locusOfFocus.get_text_iface = lambda: types.SimpleNamespace(
    get_character_count=lambda: 3, set_caret_offset=lambda offset: True)
reasons = []
caret_result = adapter.OrcaRuntimeAdapter.set_semantic_caret(payload["focus_id"], 1, diagnostic=reasons.append)
print(json.dumps({"ok": payload is not None, "focus": names.get(payload and payload["focus_id"]),
                  "caret_result": caret_result, "caret_reasons": [reason.value for reason in reasons]}))
'''


class InstalledLayoutTests(unittest.TestCase):
    def probe(self, *, helper=True):
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory)
            # Standalone runtime files, with no repository package on sys.path.
            shutil.copy2(ROOT / "linux_rdaccess_core/accessibility/orca_adapter.py", scripts / "linux_rdaccess_orca_adapter.py")
            shutil.copy2(ROOT / "linux_rdaccess_core/accessibility/a11y_model.py", scripts / "linux_rdaccess_a11y_model.py")
            if helper:
                shutil.copy2(ROOT / "linux_rdaccess_core/caret_diagnostics.py", scripts / "linux_rdaccess_caret_diagnostics.py")
            result = subprocess.run(
                [sys.executable, "-c", PROBE],
                cwd=scripts, capture_output=True, text=True, timeout=30,
                env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_installed_adapter_finds_its_renamed_model(self):
        self.assertEqual(self.probe(), {"ok": True, "focus": "Apply changes",
                         "caret_result": True, "caret_reasons": ["setter_returned"]})

    def test_missing_optional_helper_preserves_standalone_caret_behavior(self):
        self.assertEqual(self.probe(helper=False), {"ok": True, "focus": "Apply changes",
                         "caret_result": True, "caret_reasons": []})


if __name__ == "__main__":
    unittest.main()
