#!/usr/bin/env python3
"""Manage the NVDA Remote / Orca Remote backend used by linux-rdaccess."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import secrets
from typing import Literal

DEFAULT_HOST = "nvdaremote.com"
DEFAULT_PORT = 6837
DEFAULT_ROLE: Literal["host", "client"] = "host"
DEFAULT_CONFIG = Path("~/.config/linux-rdaccess/remote.json").expanduser()

_ROLE_TO_ORCA = {
    "host": "slave",
    "client": "master",
}


@dataclass(frozen=True)
class RemoteAccessConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    role: Literal["host", "client"] = DEFAULT_ROLE
    key: str = ""
    mute_local_orca_speech: bool = True

    @property
    def orca_connection_type(self) -> str:
        return _ROLE_TO_ORCA[self.role]

    @property
    def ready(self) -> bool:
        return bool(self.host and self.port and self.key and self.role in _ROLE_TO_ORCA)

    def redacted(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "role": self.role,
            "orca_connection_type": self.orca_connection_type,
            "key_configured": bool(self.key),
            "mute_local_orca_speech": self.mute_local_orca_speech,
            "ready": self.ready,
        }


def generate_key(bytes_count: int = 18) -> str:
    """Generate a high-entropy channel key without punctuation that is awkward to type."""
    return secrets.token_hex(bytes_count)


def validate_host(host: str) -> str:
    host = host.strip()
    if not host:
        raise ValueError("host must not be empty")
    if any(ch.isspace() for ch in host):
        raise ValueError("host must not contain whitespace")
    return host


def validate_port(port: int) -> int:
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def load_config(path: Path = DEFAULT_CONFIG) -> RemoteAccessConfig:
    if not path.exists():
        return RemoteAccessConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    role = raw.get("role", DEFAULT_ROLE)
    if role not in _ROLE_TO_ORCA:
        raise ValueError(f"unsupported role: {role}")
    return RemoteAccessConfig(
        host=validate_host(raw.get("host", DEFAULT_HOST)),
        port=validate_port(raw.get("port", DEFAULT_PORT)),
        role=role,
        key=str(raw.get("key", "")),
        mute_local_orca_speech=bool(raw.get("mute_local_orca_speech", True)),
    )


def save_config(config: RemoteAccessConfig, path: Path = DEFAULT_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def update_legacy_orca_customizations(
    config: RemoteAccessConfig,
    path: Path,
) -> None:
    """Update the three connection constants in a legacy Orca Remote install."""
    text = path.read_text(encoding="utf-8")
    replacements = {
        "YOUR_NVDAREMOTE_SERVER_ADDRESS": json.dumps(config.host),
        "YOUR_NVDAREMOTE_SERVER_PORT": str(config.port),
        "YOUR_NVDAREMOTE_KEY": json.dumps(config.key),
    }
    for name, value in replacements.items():
        pattern = rf"^\s*{re.escape(name)}\s*=.*$"
        updated, count = re.subn(
            pattern,
            f"{name} = {value}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError(f"{name} was not found in {path}")
        text = updated

    # Legacy Orca Remote hard-codes slave/host in the transport constructor.
    text, count = re.subn(
        r'connection_type\s*=\s*["\'](?:slave|master)["\']',
        f'connection_type="{config.orca_connection_type}"',
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"connection_type was not found in {path}")

    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(text, encoding="utf-8")



def disable_legacy_orca_connection(path: Path) -> None:
    """Disable legacy Orca Remote auto-connect without deleting saved linux-rdaccess settings."""
    text = path.read_text(encoding="utf-8")
    replacements = {
        "YOUR_NVDAREMOTE_SERVER_ADDRESS": json.dumps("host"),
        "YOUR_NVDAREMOTE_KEY": json.dumps("key"),
    }
    for name, value in replacements.items():
        pattern = rf"^\s*{re.escape(name)}\s*=.*$"
        text, count = re.subn(
            pattern,
            f"{name} = {value}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError(f"{name} was not found in {path}")
    path.write_text(text, encoding="utf-8")

def print_status(config: RemoteAccessConfig) -> None:
    data = config.redacted()
    for key in (
        "host",
        "port",
        "role",
        "orca_connection_type",
        "key_configured",
        "mute_local_orca_speech",
        "ready",
    ):
        print(f"{key}: {data[key]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show redacted Remote Access configuration")

    gen = sub.add_parser("generate-key", help="generate a new Remote Access channel key")
    gen.add_argument("--save", action="store_true", help="save the generated key to the config")
    gen.add_argument("--show", action="store_true", help="print the generated key once")

    configure = sub.add_parser("configure", help="configure the Remote Access backend")
    configure.add_argument("--host", default=None)
    configure.add_argument("--port", type=int, default=None)
    configure.add_argument("--role", choices=("host", "client"), default=None)
    configure.add_argument("--key", default=None)
    configure.add_argument("--generate-key", action="store_true")
    configure.add_argument(
        "--local-orca-speech",
        choices=("mute", "speak"),
        default=None,
        help="mute is recommended when NVDA is speaking Linux output",
    )

    apply_legacy = sub.add_parser(
        "apply-legacy",
        help="apply the saved settings to a legacy Orca Remote customization file",
    )
    apply_legacy.add_argument(
        "--orca-config",
        type=Path,
        default=Path("~/.local/share/orca/orca-customizations.py").expanduser(),
    )

    sub.add_parser("shortcuts", help="show Remote Access shortcuts")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = args.config.expanduser()
    config = load_config(path)

    if args.command == "status":
        print_status(config)
        return 0 if config.ready else 1

    if args.command == "generate-key":
        key = generate_key()
        if args.save:
            config = RemoteAccessConfig(
                host=config.host,
                port=config.port,
                role=config.role,
                key=key,
                mute_local_orca_speech=config.mute_local_orca_speech,
            )
            save_config(config, path)
            print("Generated and saved a new Remote Access key.")
        else:
            print("Generated a new Remote Access key.")
        if args.show:
            print(key)
        return 0

    if args.command == "configure":
        key = config.key
        if args.generate_key:
            key = generate_key()
        elif args.key is not None:
            key = args.key

        mute = config.mute_local_orca_speech
        if args.local_orca_speech is not None:
            mute = args.local_orca_speech == "mute"

        config = RemoteAccessConfig(
            host=validate_host(args.host if args.host is not None else config.host),
            port=validate_port(args.port if args.port is not None else config.port),
            role=args.role if args.role is not None else config.role,
            key=key,
            mute_local_orca_speech=mute,
        )
        save_config(config, path)
        print("Saved Remote Access configuration.")
        print_status(config)
        return 0

    if args.command == "apply-legacy":
        if not config.ready:
            print("Remote Access configuration is incomplete.")
            return 1
        update_legacy_orca_customizations(config, args.orca_config.expanduser())
        print("Applied Remote Access settings to legacy Orca Remote.")
        print("Restart Orca to use the new settings.")
        return 0

    if args.command == "shortcuts":
        print("Windows NVDA:")
        print("  Insert+Alt+Tab  Toggle local/remote computer control")
        print("")
        print("Linux Orca Remote:")
        print("  Orca+Alt+PageUp / Orca+Alt+C      Connect (legacy)")
        print("  Orca+Alt+PageDown / Orca+Alt+D    Disconnect (legacy)")
        print("  Orca+Alt+M                         Mute/unmute remote output (legacy)")
        print("  Orca+Alt+Tab                       Toggle local/remote control (legacy client role)")
        print("")
        print("Roles:")
        print("  host    Linux is controlled by Windows NVDA (recommended for this project)")
        print("  client  Linux controls another NVDA Remote computer")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
