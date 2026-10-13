"""Isolated NVDA companion tests; never imported by the Linux test suite."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ADDON_ROOT.parent
PLUGIN_ROOT = ADDON_ROOT / "addon/globalPlugins/linuxRdAccess"
WIRE_ROOT = REPO_ROOT / "linux_rdaccess_core/connection/nvda_test_client"
NVDA_SOURCE = Path(os.environ.get("NVDA_SOURCE_DIR", REPO_ROOT.parent / "nvda/source")).resolve()
if not (NVDA_SOURCE / "baseObject.py").is_file():
	raise RuntimeError("Set NVDA_SOURCE_DIR to an NVDA source checkout, or clone nvda beside linux-rdaccess")
sys.path.insert(0, str(NVDA_SOURCE))
package = types.ModuleType("_linux_rdaccess_addon_tests")
package.__path__ = [str(PLUGIN_ROOT), str(WIRE_ROOT)]
sys.modules[package.__name__] = package

from . import _stubs  # noqa: E402

_stubs.install()
