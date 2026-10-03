#!/usr/bin/env python3
"""Manage the NVDA Remote / Orca Remote backend used by linux-rdaccess."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import secrets
import sys
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

    remote_controller = path.parent / LEGACY_REMOTE_CONTROLLER_RELATIVE
    if remote_controller.exists():
        # The input shim is an enhancement: a changed upstream layout must not
        # stop the connection settings above from being applied.
        try:
            patch_legacy_orca_remote_controller(remote_controller)
        except (ValueError, OSError) as exc:
            print(
                f"warning: NVDA input compatibility patch not applied: {exc}",
                file=sys.stderr,
            )


LEGACY_REMOTE_CONTROLLER_RELATIVE = Path("orca-scripts/remote_controller.py")
LEGACY_COMPAT_MARKER_V1 = "# linux-rdaccess NVDA/Orca input compatibility"
LEGACY_COMPAT_MARKER = "# linux-rdaccess NVDA/Orca input compatibility v3"
# v1 is a prefix of every later marker, so any older patch is detected by it.

_LEGACY_HELPERS = '''\
    ''' + LEGACY_COMPAT_MARKER + '''
    # Helpers injected by linux-rdaccess. They never log key names, braille
    # dots, speech text or connection keys.
    _LRD_CTRL_VKS = (0x11, 0xA2, 0xA3)
    _LRD_MODIFIER_VKS = (
        0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5,
        0x5B, 0x5C, 0x2D, 0x14,
    )  # Shift, Ctrl, Alt, Win, Insert, CapsLock (NVDA modifier keys)
    _LRD_BRAILLE_ACTIONS = {
        "braille_scrollBack": "pan_back",
        "braille_scrollForward": "pan_forward",
        "braille_routeTo": "route",
    }
    _LRD_TRACE_MAX_BYTES = 262144
    _LRD_OTHER_MOD_VKS = (
        0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5, 0x5B, 0x5C,
    )
    # NVDA chord -> Orca command, checked against the Orca 42 desktop keymap.
    # NVDA+Up/review keys are deliberately NOT mapped: Orca's KP_Up enters flat
    # review, which would leave braille following the review cursor.
    #   vk: (extended-required, Orca key name, target vk, drop NVDA modifier,
    #        press count)
    # "drop" is needed where Orca binds the key with NO Orca modifier.
    _LRD_CHORDS = {
        0x20: (False, "a", 0x41, False, 1),         # NVDA+Space: Orca+A focus/browse
        0x28: (True, "KP_Add", 0x6B, True, 1),      # NVDA+Down: say all
        0x09: (False, "KP_Enter", 0x0D, True, 1),   # NVDA+Tab: where am I
        0x54: (False, "KP_Enter", 0x0D, False, 1),  # NVDA+T: Orca+KP_Enter title
        0x23: (True, "KP_Enter", 0x0D, False, 2),   # NVDA+End: status bar (2x)
    }

    def _linux_rdaccess_filter_key(self, pressed, vk_code, extended, modifiers,
                                   key_name=None, scan_code=None):
        """Return True when the event was fully handled here."""
        state = (
            getattr(self, "control_state", None),
            bool(getattr(getattr(self, "transport", None), "connected", True)),
        )
        if getattr(self, "_lrd_state", None) != state:
            # Control moved local/remote or the transport reconnected:
            # forget held keys so a stale NVDA modifier cannot rewrite Space.
            self._lrd_state = state
            self._lrd_down = set()
            self._lrd_nvda_down = False
            self._lrd_swapped = set()
            self._lrd_nvda_key = None
        pressed = bool(pressed)
        held = (vk_code, bool(extended))
        repeat = pressed and held in self._lrd_down
        if pressed:
            self._lrd_down.add(held)
        else:
            self._lrd_down.discard(held)
        if vk_code in (0x2D, 0x14):
            self._lrd_nvda_down = pressed
            self._lrd_nvda_key = held if pressed else None

        # Interrupt stale speech on a real action, as NVDA does. Plain
        # modifier keys (and their auto-repeat) must not cut off speech that
        # a chord such as NVDA+Down started; Ctrl itself does interrupt.
        if pressed and (
            vk_code not in self._LRD_MODIFIER_VKS
            or (vk_code in self._LRD_CTRL_VKS and not repeat)
        ):
            try:
                self.local_machine.cancel_speech()
            except Exception:
                log.exception("linux-rdaccess: failed to cancel speech")

        # NVDA chords -> Orca commands (see _LRD_CHORDS). Only the first press
        # with the NVDA modifier held and no Shift/Ctrl/Alt/Win is translated;
        # auto-repeat is consumed, and a release is consumed only for a
        # translated press, so a normally forwarded key is never left stuck.
        if pressed:
            if vk_code in self._lrd_swapped:
                return True  # auto-repeat of a translated chord
            chord = self._LRD_CHORDS.get(vk_code)
            if (
                chord is None
                or repeat
                or not self._lrd_nvda_down
                or any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down)
                or bool(extended) != chord[0]
            ):
                return False
            need_ext, name, target_vk, drop, count = chord
            nvda = self._lrd_nvda_key
            if drop and (nvda is None or nvda[0] == 0x14):
                # Re-pressing CapsLock would toggle the lock state.
                return False
            self._lrd_swapped.add(vk_code)
            send = self.local_machine.send_key
            if drop:
                send(key_name=None, pressed=False, modifiers=modifiers,
                     vk_code=nvda[0], scan_code=0, extended=nvda[1])
            for _ in range(count):
                for down in (True, False):
                    send(key_name=name, pressed=down, modifiers=modifiers,
                         vk_code=target_vk, scan_code=0, extended=False)
            if drop:
                send(key_name=None, pressed=True, modifiers=modifiers,
                     vk_code=nvda[0], scan_code=0, extended=nvda[1])
            return True
        if vk_code in self._lrd_swapped:
            self._lrd_swapped.discard(vk_code)
            return True
        return False

    def _linux_rdaccess_classify_braille(self, kwargs):
        """Return (action, safe_record) for an NVDA Remote braille_input."""
        def text(value):
            return str(value)[:120]
        ids = [kwargs.get("id")] + list(kwargs.get("identifiers") or [])
        keyboard = bool(kwargs.get("dots") or kwargs.get("space")) or any(
            "dot" in str(i).lower() for i in ids if i
        )
        if keyboard:
            # Braille keyboard input is typed text (possibly a password).
            return "keyboard", {
                "redacted": "braille-keyboard-input",
                "model": text(kwargs.get("model")),
                "source": text(kwargs.get("source")),
            }
        record = {}
        for name in ("id", "scriptPath", "source", "model", "routingIndex"):
            if name in kwargs:
                value = kwargs[name]
                record[name] = (
                    [text(v) for v in value]
                    if isinstance(value, (list, tuple)) else text(value)
                )
        if kwargs.get("identifiers"):
            record["identifiers"] = [text(i) for i in kwargs["identifiers"]]
        script = kwargs.get("scriptPath") or []
        name = str(script[-1]) if script else ""
        if name.startswith("script_"):
            name = name[len("script_"):]
        action = self._LRD_BRAILLE_ACTIONS.get(name)
        return action, record

    def _linux_rdaccess_trace_braille(self, record):
        import json as _json
        import os as _os
        path = _os.path.expanduser(
            "~/.local/share/orca/orca-remote-braille-input.log")
        try:
            if _os.path.getsize(path) > self._LRD_TRACE_MAX_BYTES:
                _os.replace(path, path + ".1")
        except OSError:
            pass
        fd = _os.open(path, _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT, 0o600)
        with _os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(_json.dumps(record, sort_keys=True) + "\\n")
        try:
            _os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _linux_rdaccess_run_main(func):
        try:
            from gi.repository import GLib
        except Exception:
            func()
            return
        GLib.idle_add(lambda: (func(), False)[1])

    def _linux_rdaccess_handle_braille_input(self, kwargs):
        action, record = self._linux_rdaccess_classify_braille(kwargs)
        try:
            self._linux_rdaccess_trace_braille(record)
        except Exception:
            log.exception("linux-rdaccess: failed to trace braille input")
        if action in ("pan_back", "pan_forward"):
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call(
                    "panBrailleLeft" if action == "pan_back" else "panBrailleRight"))
        elif action == "route":
            index = kwargs.get("routingIndex")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 1024:
                return
            import types as _types
            event = _types.SimpleNamespace(event={"argument": index})
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call("processRoutingKey", event))

    @staticmethod
    def _linux_rdaccess_script_call(method, *args):
        """Run an Orca script handler (never braille.* directly) on the main loop.

        The script handlers own flat review, line wrapping and display refresh;
        calling braille.panLeft/panRight would only move the viewport.
        """
        try:
            from orca import orca_state as _state
            script = _state.activeScript
            handler = getattr(script, method, None)
            if handler is None:
                return
            if method.startswith("pan"):
                handler(None)
            else:
                handler(*args)
        except Exception:
            log.exception("linux-rdaccess: Orca %s failed", method)

'''

_LEGACY_RESET_HOOKS = (
    LEGACY_COMPAT_MARKER + "\n"
    "# Control hand-over and reconnects forget held-key state, even when no key\n"
    "# event arrives in between.\n"
    "def _linux_rdaccess_wrap_reset(name):\n"
    "    original = getattr(RemoteController, name, None)\n"
    "    if original is None:\n"
    "        return\n"
    "    def wrapper(self, *args, **kwargs):\n"
    "        self._lrd_state = None\n"
    "        return original(self, *args, **kwargs)\n"
    "    wrapper.__name__ = original.__name__\n"
    "    setattr(RemoteController, name, wrapper)\n"
    "\n\n"
    "for _lrd_name in (\"toggle_control\", \"disconnect\",\n"
    "                  \"_on_transport_connected\", \"_on_transport_disconnected\"):\n"
    "    _linux_rdaccess_wrap_reset(_lrd_name)\n"
)

_LEGACY_KEY_CALL = (
    "        " + LEGACY_COMPAT_MARKER + "\n"
    "        if self._linux_rdaccess_filter_key(\n"
    "                pressed, vk_code, extended, modifiers, key_name, scan_code):\n"
    "            return\n"
)

_LEGACY_BRAILLE_HANDLER = (
    "    def _on_remote_braille_input(self, **kwargs):\n"
    "        " + LEGACY_COMPAT_MARKER + "\n"
    "        try:\n"
    "            self._linux_rdaccess_handle_braille_input(kwargs)\n"
    "        except Exception:\n"
    "            log.exception(\"linux-rdaccess: braille input handling failed\")\n"
)


def patch_legacy_orca_remote_controller(path: Path) -> bool:
    """Patch legacy Orca Remote input handling for NVDA compatibility.

    Returns True when the file changed. The patch is idempotent, replaces an
    earlier v1 patch from the one-time .linux-rdaccess-backup, verifies the
    result compiles before writing, and writes atomically.
    """
    text = path.read_text(encoding="utf-8")
    if LEGACY_COMPAT_MARKER in text:
        return False
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if LEGACY_COMPAT_MARKER_V1 in text:
        if not backup.exists():
            raise ValueError(f"v1 patch found but backup is missing: {backup}")
        text = backup.read_text(encoding="utf-8")

    key_def = re.search(r"^    def _on_remote_key\(([^)]*)\):\n", text, re.MULTILINE)
    if key_def is None:
        raise ValueError(f"legacy _on_remote_key was not found in {path}")
    params = key_def.group(1)
    for needed in ("pressed", "vk_code", "extended", "modifiers"):
        if needed not in params:
            raise ValueError(f"legacy _on_remote_key lacks {needed} in {path}")
    body_end = text.find("\n    def ", key_def.end())
    body_end = len(text) if body_end == -1 else body_end
    key_anchor = "        self.local_machine.send_key(\n"
    anchor_at = text.find(key_anchor, key_def.end(), body_end)
    if anchor_at == -1:
        raise ValueError(f"legacy _on_remote_key send_key anchor was not found in {path}")
    text = text[:anchor_at] + _LEGACY_KEY_CALL + text[anchor_at:]
    text = text[:key_def.start()] + _LEGACY_HELPERS + text[key_def.start():]

    braille_def = re.search(
        r"^    def _on_remote_braille_input\(self, \*\*kwargs\):\n"
        r"(?:        .*\n)+?(?=\n|    def |\Z)",
        text,
        re.MULTILINE,
    )
    if braille_def is None:
        raise ValueError(f"legacy braille-input handler was not found in {path}")
    text = text[:braille_def.start()] + _LEGACY_BRAILLE_HANDLER + text[braille_def.end():]
    text = text.rstrip("\n") + "\n\n\n" + _LEGACY_RESET_HOOKS

    try:
        compile(text, str(path), "exec")
    except SyntaxError as exc:
        raise ValueError(f"patched {path} would not compile: {exc}") from exc

    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    tmp = path.with_name(path.name + ".linux-rdaccess-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


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
