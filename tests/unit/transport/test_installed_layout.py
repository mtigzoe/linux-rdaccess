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
print(json.dumps({"ok": payload is not None, "focus": names.get(payload and payload["focus_id"])}))
'''


class InstalledLayoutTests(unittest.TestCase):
    def test_installed_adapter_finds_its_renamed_model(self):
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory)
            # Exactly the two files update_legacy_orca_customizations installs.
            shutil.copy2(ROOT / "linux_rdaccess_core/accessibility/orca_adapter.py", scripts / "linux_rdaccess_orca_adapter.py")
            shutil.copy2(ROOT / "linux_rdaccess_core/accessibility/a11y_model.py", scripts / "linux_rdaccess_a11y_model.py")
            result = subprocess.run(
                [sys.executable, "-c", PROBE],
                cwd=scripts, capture_output=True, text=True, timeout=30,
                env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"ok": True, "focus": "Apply changes"})


if __name__ == "__main__":
    unittest.main()
