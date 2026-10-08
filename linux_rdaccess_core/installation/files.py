"""Install the user-level Linux runtime bundle.

Kept independent of the command-line entry point to avoid circular imports.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys


RUNTIME_FILES = (
    "linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py",
    "orca_adapter.py", "a11y_model.py",
)


def install_runtime_files(source_dir: Path, *, share_dir: Path, bin_path: Path) -> None:
    """Validate the source bundle before copying files and writing the launcher."""
    for name in RUNTIME_FILES:
        if not (source_dir / name).is_file():
            raise FileNotFoundError(source_dir / name)
    package = source_dir / "linux_rdaccess_core"
    connection_check = package / "connection" / "nvda_remote_check.py"
    if not connection_check.is_file():
        raise FileNotFoundError(connection_check)

    share_dir.mkdir(parents=True, exist_ok=True)
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    for name in RUNTIME_FILES:
        source = source_dir / name
        target = share_dir / name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)

    target_package = share_dir / "linux_rdaccess_core"
    if package.resolve() != target_package.resolve():
        shutil.copytree(
            package, target_package, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    wrapper = (
        "#!/bin/sh\n"
        f'exec "{sys.executable}" "{share_dir / "linux_rdaccess.py"}" "$@"\n'
    )
    bin_path.write_text(wrapper, encoding="utf-8")
    bin_path.chmod(0o755)
