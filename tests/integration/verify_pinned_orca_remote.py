#!/usr/bin/env python3
"""Verify production legacy patches against pinned *actual* Orca Remote files.

Only temporary copies are modified. No Orca instance, relay, user profile,
credentials, or screen-reader session is accessed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile

from linux_rdaccess_core.connection.remote_access import (
    _patch_legacy_transport_cleanup,
    legacy_controller_patch_current,
    patch_legacy_orca_local_machine,
    patch_legacy_orca_remote_controller,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    args = parser.parse_args()
    scripts = args.upstream / "orca-scripts"
    required = ("transport.py", "remote_controller.py", "local_machine.py")
    for name in required:
        if not (scripts / name).is_file():
            raise RuntimeError(f"Pinned upstream is missing {name}")

    with tempfile.TemporaryDirectory(prefix="lrd-upstream-patch-") as temp:
        target = Path(temp)
        for name in required:
            shutil.copyfile(scripts / name, target / name)

        controller = target / "remote_controller.py"
        machine = target / "local_machine.py"
        transport = target / "transport.py"
        assert patch_legacy_orca_remote_controller(controller), (
            "controller patch did not modify pinned upstream"
        )
        assert legacy_controller_patch_current(controller.read_text()), (
            "patched real upstream controller is not current"
        )
        assert patch_legacy_orca_local_machine(machine), (
            "local-machine patch did not modify pinned upstream"
        )
        # Fail closed if either the injection backend or held-key accounting
        # changes after the vetted upstream patch has been applied.
        patched_machine = machine.read_text(encoding="utf-8")
        for replacement in (
            ("if self._send_key_portal(key, pressed):\n                return True",
             "if self._send_key_portal(key, pressed):\n                return None"),
            ("if delivered:\n            if pressed:",
             "if True:\n            if pressed:"),
            ("        return delivered\n", "        return True\n"),
        ):
            altered = patched_machine.replace(replacement[0], replacement[1], 1)
            if altered == patched_machine:
                raise AssertionError(f"missing validation fixture: {replacement[0]}")
            from linux_rdaccess_core.connection.remote_access import (
                legacy_local_machine_patch_current,
            )
            assert not legacy_local_machine_patch_current(altered), (
                f"validator accepted unsafe alteration: {replacement}"
            )
        patched_transport = _patch_legacy_transport_cleanup(
            transport.read_text(encoding="utf-8")
        )
        assert patched_transport != transport.read_text(encoding="utf-8"), (
            "transport patch did not modify pinned upstream"
        )
        for path, source in (
            (controller, controller.read_text(encoding="utf-8")),
            (machine, machine.read_text(encoding="utf-8")),
            (transport, patched_transport),
        ):
            compile(source, str(path), "exec")

        assert not patch_legacy_orca_remote_controller(controller), (
            "controller patch is not idempotent"
        )
        assert not patch_legacy_orca_local_machine(machine), (
            "local-machine patch is not idempotent"
        )
        assert _patch_legacy_transport_cleanup(patched_transport) == patched_transport, (
            "transport patch is not idempotent"
        )
    print("Actual pinned Orca Remote controller, local-machine and transport patch contracts passed")


if __name__ == "__main__":
    main()
