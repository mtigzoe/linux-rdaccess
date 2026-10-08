"""Install the user-level Linux runtime bundle.

Kept independent of the command-line entry point to avoid circular imports.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import shlex
import sys


RUNTIME_FILES = (
    "linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py",
    "orca_adapter.py", "a11y_model.py", "linux_rdaccess_windows.py",
    "announcer.py", "a11y_link.py", "braille_link.py", "rdaccess_dvc.py",
    "atspi_nvda_bridge.py", "atspi_nvda_braille_bridge.py",
)

RUNTIME_PACKAGE_FILES = (
    "__init__.py", "cli.py",
    "accessibility/__init__.py", "accessibility/announcer.py",
    "accessibility/a11y_model.py", "accessibility/orca_adapter.py",
    "accessibility/atspi_nvda_bridge.py", "accessibility/atspi_nvda_braille_bridge.py",
    "connection/__init__.py", "connection/remote_access.py",
    "connection/windows_controller.py", "connection/nvda_remote_check.py", "connection/session.py",
    "installation/__init__.py", "installation/files.py", "installation/autostart.py",
    "transport/__init__.py", "transport/a11y_link.py", "transport/braille_link.py",
    "transport/rdaccess_dvc.py",
    "announcer.py", "a11y_link.py", "braille_link.py", "rdaccess_dvc.py",
)


def source_bundle_root() -> Path:
    """Locate the source bundle in both a checkout and a user-level installation."""
    return Path(__file__).resolve().parents[2]


def orca_runtime_sources() -> dict[str, Path]:
    """The standalone implementations Orca loads under its historical filenames."""
    directory = Path(__file__).resolve().parents[1] / "accessibility"
    return {name: directory / f"{name}.py" for name in ("orca_adapter", "a11y_model")}


def install_runtime_files(source_dir: Path, *, share_dir: Path, bin_path: Path) -> None:
    """Validate the source bundle before copying files and writing the launcher."""
    for name in RUNTIME_FILES:
        if not (source_dir / name).is_file():
            raise FileNotFoundError(source_dir / name)
    package = source_dir / "linux_rdaccess_core"
    for name in RUNTIME_PACKAGE_FILES:
        if not (package / name).is_file():
            raise FileNotFoundError(package / name)

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
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(share_dir / "linux_rdaccess.py"))} "$@"\n'
    )
    bin_path.write_text(wrapper, encoding="utf-8")
    bin_path.chmod(0o755)
