#!/usr/bin/env python3
"""Install and operate linux-rdaccess as a user-level Linux command."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

from remote_access import (
    DEFAULT_CONFIG,
    disable_legacy_orca_connection,
    load_config,
    print_status,
    update_legacy_orca_customizations,
)

APP_NAME = "linux-rdaccess"
DEFAULT_ORCA_CONFIG = Path("~/.local/share/orca/orca-customizations.py").expanduser()
DEFAULT_SHARE_DIR = Path("~/.local/share/linux-rdaccess").expanduser()
DEFAULT_BIN = Path("~/.local/bin/linux-rdaccess").expanduser()
DEFAULT_AUTOSTART = Path("~/.config/autostart/linux-rdaccess.desktop").expanduser()
GRAPHICAL_SESSION_PROCESSES = (
    "xfce4-session",
    "gnome-shell",
    "cinnamon",
    "mate-session",
    "lxqt-session",
    "plasmashell",
)


def graphical_session_env(
    *,
    proc_root: Path = Path("/proc"),
    base_env: dict[str, str] | None = None,
    uid: int | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return env

    target_uid = os.getuid() if uid is None else uid
    wanted = {
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR",
        "XDG_SESSION_TYPE",
    }

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
            if comm not in GRAPHICAL_SESSION_PROCESSES:
                continue
            status = (entry / "status").read_text(encoding="utf-8")
            uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
            real_uid = int(uid_line.split()[1])
            if real_uid != target_uid:
                continue
            raw = (entry / "environ").read_bytes().split(b"\0")
        except (OSError, StopIteration, ValueError):
            continue

        session_env: dict[str, str] = {}
        for item in raw:
            if not item or b"=" not in item:
                continue
            key_b, value_b = item.split(b"=", 1)
            key = key_b.decode(errors="ignore")
            if key in wanted:
                session_env[key] = value_b.decode(errors="ignore")

        if session_env.get("DISPLAY") or session_env.get("WAYLAND_DISPLAY"):
            env.update(session_env)
            return env

    return env


def restart_orca() -> int:
    try:
        completed = subprocess.run(
            ["orca", "--replace"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=graphical_session_env(),
        )
    except FileNotFoundError:
        print("Orca was not found in PATH.")
        return 1
    return completed.returncode


def install_user_files(
    source_dir: Path,
    *,
    share_dir: Path = DEFAULT_SHARE_DIR,
    bin_path: Path = DEFAULT_BIN,
) -> None:
    share_dir.mkdir(parents=True, exist_ok=True)
    bin_path.parent.mkdir(parents=True, exist_ok=True)

    for name in ("linux_rdaccess.py", "remote_access.py", "nvda_remote_check.py"):
        shutil.copy2(source_dir / name, share_dir / name)

    wrapper = (
        "#!/bin/sh\n"
        f'exec "{sys.executable}" "{share_dir / "linux_rdaccess.py"}" "$@"\n'
    )
    bin_path.write_text(wrapper, encoding="utf-8")
    bin_path.chmod(0o755)


def write_autostart(
    *,
    autostart_path: Path = DEFAULT_AUTOSTART,
    bin_path: Path = DEFAULT_BIN,
) -> None:
    autostart_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""[Desktop Entry]
Type=Application
Name=linux-rdaccess
Comment=Connect Orca Remote for Windows NVDA accessibility
Exec={bin_path} connect --quiet
Terminal=false
X-GNOME-Autostart-enabled=true
"""
    autostart_path.write_text(content, encoding="utf-8")


def remove_autostart(path: Path = DEFAULT_AUTOSTART) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def connect(
    *,
    config_path: Path,
    orca_config: Path,
    restart: bool = True,
    quiet: bool = False,
) -> int:
    config = load_config(config_path)
    if not config.ready:
        if not quiet:
            print("Remote Access configuration is incomplete.")
            print("Run: linux-rdaccess configure --role host --generate-key")
        return 1
    if not orca_config.exists():
        if not quiet:
            print(f"Orca Remote legacy config not found: {orca_config}")
        return 1

    update_legacy_orca_customizations(config, orca_config)
    if not quiet:
        print(f"Configured {config.host}:{config.port} as role {config.role}.")
        print("Remote Access key remains hidden.")
    if restart:
        return restart_orca()
    return 0


def disconnect(*, orca_config: Path, restart: bool = True, quiet: bool = False) -> int:
    if not orca_config.exists():
        if not quiet:
            print(f"Orca Remote legacy config not found: {orca_config}")
        return 1
    disable_legacy_orca_connection(orca_config)
    if not quiet:
        print("Disabled Orca Remote auto-connect. Saved linux-rdaccess settings were kept.")
    if restart:
        return restart_orca()
    return 0



DEFAULT_VSCODE_SETTINGS = Path("~/.config/Code/User/settings.json").expanduser()


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas (VS Code uses JSONC)."""
    out: list[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        else:
            out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def configure_vscode_accessibility(path: Path = DEFAULT_VSCODE_SETTINGS) -> None:
    """Enable VS Code screen-reader accessibility without replacing other settings.

    settings.json is JSONC, so comments and formatting are preserved by editing
    the text in place rather than re-serialising it. A one-time backup is kept.
    """
    path = path.expanduser()
    text = path.read_text(encoding="utf-8") if path.exists() else "{\n}\n"
    try:
        data = json.loads(_strip_jsonc(text) or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"VS Code settings are not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"VS Code settings must contain a JSON object: {path}")

    wanted = {"editor.accessibilitySupport": "on"}
    if "window.titleBarStyle" not in data:
        wanted["window.titleBarStyle"] = "custom"
    for key, value in wanted.items():
        line = f'"{key}": {json.dumps(value)}'
        existing = re.search(rf'"{re.escape(key)}"\s*:\s*"[^"]*"', text)
        if existing:
            text = text[:existing.start()] + line + text[existing.end():]
            continue
        brace = text.index("{")
        rest = _strip_jsonc(text[brace + 1:]).strip()
        sep = "" if rest.startswith("}") else ","
        text = f"{text[:brace + 1]}\n    {line}{sep}{text[brace + 1:]}"
    json.loads(_strip_jsonc(text))  # never write something we cannot parse
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if path.exists() and not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = path.with_name(path.name + ".linux-rdaccess-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


COMPATIBILITY_APPS = (
    ("thunar", "Thunar File Manager"),
    ("xfce4-terminal", "XFCE Terminal"),
    ("xfce4-settings-manager", "XFCE Settings Manager"),
    ("mousepad", "Mousepad"),
    ("xed", "Xed"),
    ("mintupdate", "Update Manager"),
    ("mintinstall", "Software Manager"),
    ("xfce4-panel", "XFCE panel"),
    ("firefox", "Firefox"),
    ("code", "VS Code"),
)


def compatibility_status() -> list[tuple[str, str, bool]]:
    """Return command availability for the primary Linux Mint compatibility targets."""
    return [
        (command, label, shutil.which(command) is not None)
        for command, label in COMPATIBILITY_APPS
    ]


def print_compatibility_status() -> None:
    print("Linux Mint / XFCE compatibility targets:")
    for command, label, available in compatibility_status():
        print(f"  {label}: {'installed' if available else 'not found'} ({command})")
    print("")
    print("Also test reusable UI patterns:")
    print("  GTK Open/Save dialogs")
    print("  XFCE panel/application menu")
    print("  notifications")
    print("  authentication prompts")
    print("  trees/lists/tables/menus/dialogs/tabs/toolbars")



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--orca-config", type=Path, default=DEFAULT_ORCA_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="install the linux-rdaccess command for this user")
    install.add_argument("--no-autostart", action="store_true")

    sub.add_parser("uninstall", help="remove the user command and autostart entry")

    connect_p = sub.add_parser("connect", help="apply settings and connect Orca Remote")
    connect_p.add_argument("--no-restart", action="store_true")
    connect_p.add_argument("--quiet", action="store_true")

    disconnect_p = sub.add_parser("disconnect", help="disconnect Orca Remote but keep saved settings")
    disconnect_p.add_argument("--no-restart", action="store_true")
    disconnect_p.add_argument("--quiet", action="store_true")

    sub.add_parser("status", help="show redacted Remote Access status")

    autostart = sub.add_parser("autostart", help="enable or disable login autostart")
    autostart.add_argument("state", choices=("enable", "disable", "status"))

    sub.add_parser("shortcuts", help="show common NVDA/Orca shortcuts")
    sub.add_parser("compatibility", help="show Linux Mint application compatibility targets")

    vscode = sub.add_parser("vscode-setup", help="enable VS Code Linux screen-reader accessibility")
    vscode.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_VSCODE_SETTINGS,
        help="path to VS Code settings.json",
    )

    sub.add_parser("configure", help="run the Remote Access configuration manager")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, forwarded = parser.parse_known_args(argv)
    if forwarded and args.command != "configure":
        parser.error("unrecognized arguments: " + " ".join(forwarded))
    config_path = args.config.expanduser()
    orca_config = args.orca_config.expanduser()

    if args.command == "install":
        source_dir = Path(__file__).resolve().parent
        install_user_files(source_dir)
        if not args.no_autostart:
            write_autostart()
        print(f"Installed command: {DEFAULT_BIN}")
        print(f"Autostart: {'disabled' if args.no_autostart else 'enabled'}")
        print("If ~/.local/bin is not already in PATH, log out and back in or add it to PATH.")
        return 0

    if args.command == "uninstall":
        remove_autostart()
        try:
            DEFAULT_BIN.unlink()
        except FileNotFoundError:
            pass
        if DEFAULT_SHARE_DIR.exists():
            shutil.rmtree(DEFAULT_SHARE_DIR)
        print("Removed the linux-rdaccess command and autostart entry.")
        print("Saved Remote Access configuration was kept.")
        return 0

    if args.command == "connect":
        return connect(
            config_path=config_path,
            orca_config=orca_config,
            restart=not args.no_restart,
            quiet=args.quiet,
        )

    if args.command == "disconnect":
        return disconnect(
            orca_config=orca_config,
            restart=not args.no_restart,
            quiet=args.quiet,
        )

    if args.command == "status":
        config = load_config(config_path)
        print_status(config)
        print(f"autostart_enabled: {DEFAULT_AUTOSTART.exists()}")
        print(f"command_installed: {DEFAULT_BIN.exists()}")
        print(f"orca_remote_config_found: {orca_config.exists()}")
        return 0 if config.ready else 1

    if args.command == "autostart":
        if args.state == "enable":
            write_autostart()
            print("Enabled linux-rdaccess autostart.")
        elif args.state == "disable":
            remove_autostart()
            print("Disabled linux-rdaccess autostart.")
        else:
            print("enabled" if DEFAULT_AUTOSTART.exists() else "disabled")
        return 0

    if args.command == "compatibility":
        print_compatibility_status()
        return 0

    if args.command == "shortcuts":
        print("Windows NVDA:")
        print("  Insert+Alt+Tab    Toggle local/remote computer control")
        print("")
        print("Legacy Orca Remote:")
        print("  Orca+Alt+PageUp / Orca+Alt+C      Connect")
        print("  Orca+Alt+PageDown / Orca+Alt+D    Disconnect")
        print("  Orca+Alt+M                         Mute/unmute remote output")
        return 0

    if args.command == "vscode-setup":
        configure_vscode_accessibility(args.settings)
        print(f"Enabled VS Code screen-reader accessibility in: {args.settings.expanduser()}")
        print("If Orca is still silent, launch VS Code with: ACCESSIBILITY_ENABLED=1 code")
        return 0

    if args.command == "configure":
        remote_access = Path(__file__).resolve().parent / "remote_access.py"
        return subprocess.call([sys.executable, str(remote_access), "--config", str(config_path), "configure", *forwarded])

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
