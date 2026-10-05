#!/usr/bin/env python3
"""Manage the NVDA Remote / Orca Remote backend used by linux-rdaccess."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tempfile
import textwrap
from typing import Literal

DEFAULT_HOST = "nvdaremote.com"
DEFAULT_PORT = 6837
DEFAULT_ROLE: Literal["host", "client"] = "host"
DEFAULT_CONFIG = Path("~/.config/linux-rdaccess/remote.json").expanduser()

_ROLE_TO_ORCA = {
    "host": "slave",
    "client": "master",
}

LOCAL_SPEECH_PREF_MARKER = "# linux-rdaccess local Orca speech preference"
_LOCAL_SPEECH_PREF_HOOK_V1 = """# linux-rdaccess local Orca speech preference
# Legacy Orca Remote forwards Orca speech to NVDA and then calls the original
# local SpeechServer methods. In slave/controlled mode, replace only those
# original local-output callables when requested. The forwarding wrappers stay
# installed, so Windows NVDA continues to receive all Orca speech.
if (
    LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH
    and globals().get("transport") is not None
    and getattr(transport, "connection_type", None) == "slave"
):
    if "old_speak" in globals():
        def _linux_rdaccess_muted_old_speak(*args, **kwargs):
            return None
        old_speak = _linux_rdaccess_muted_old_speak
    if "old_speakCharacter" in globals():
        def _linux_rdaccess_muted_old_speak_character(*args, **kwargs):
            return None
        old_speakCharacter = _linux_rdaccess_muted_old_speak_character
"""
_LOCAL_SPEECH_PREF_HOOK_V2 = """# linux-rdaccess local Orca speech preference
# Keep forwarding wrappers installed; mute only while the remote transport is
# actually connected in slave mode, and restore local output on disconnect.
def _linux_rdaccess_local_speech_muted():
    peer = globals().get("transport")
    return (LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH
            and getattr(peer, "connected", False)
            and getattr(peer, "connection_type", None) == "slave")

if "old_speak" in globals():
    _linux_rdaccess_saved_old_speak = old_speak
    def _linux_rdaccess_muted_old_speak(*args, **kwargs):
        if _linux_rdaccess_local_speech_muted():
            return None
        return _linux_rdaccess_saved_old_speak(*args, **kwargs)
    old_speak = _linux_rdaccess_muted_old_speak
if "old_speakCharacter" in globals():
    _linux_rdaccess_saved_old_speak_character = old_speakCharacter
    def _linux_rdaccess_muted_old_speak_character(*args, **kwargs):
        if _linux_rdaccess_local_speech_muted():
            return None
        return _linux_rdaccess_saved_old_speak_character(*args, **kwargs)
    old_speakCharacter = _linux_rdaccess_muted_old_speak_character
"""

_LOCAL_SPEECH_PREF_HOOK = """# linux-rdaccess local Orca speech preference
# Keep forwarding wrappers installed; mute only while the remote transport is
# actually connected in slave mode, and restore local output on disconnect.
def _linux_rdaccess_local_speech_muted():
    peer = globals().get("transport")
    return (LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH
            and getattr(peer, "connected", False)
            and getattr(peer, "connection_type", None) == "slave")

def _linux_rdaccess_wrap_local_speech(original):
    def wrapped(*args, **kwargs):
        if _linux_rdaccess_local_speech_muted():
            return None
        return original(*args, **kwargs)
    wrapped._linux_rdaccess_original = original
    return wrapped

if "old_speak" in globals() and not hasattr(old_speak, "_linux_rdaccess_original"):
    _linux_rdaccess_saved_old_speak = (
        globals().get("_linux_rdaccess_saved_old_speak", old_speak)
        if old_speak is globals().get("_linux_rdaccess_muted_old_speak") else old_speak)
    _linux_rdaccess_muted_old_speak = _linux_rdaccess_wrap_local_speech(_linux_rdaccess_saved_old_speak)
    old_speak = _linux_rdaccess_muted_old_speak
if "old_speakCharacter" in globals() and not hasattr(old_speakCharacter, "_linux_rdaccess_original"):
    _linux_rdaccess_saved_old_speak_character = (
        globals().get("_linux_rdaccess_saved_old_speak_character", old_speakCharacter)
        if old_speakCharacter is globals().get("_linux_rdaccess_muted_old_speak_character") else old_speakCharacter)
    _linux_rdaccess_muted_old_speak_character = _linux_rdaccess_wrap_local_speech(_linux_rdaccess_saved_old_speak_character)
    old_speakCharacter = _linux_rdaccess_muted_old_speak_character
"""



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


def _write_private_text(path: Path, text: str) -> None:
    """Publish secret-bearing text from a file private from its creation."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_config(config: RemoteAccessConfig, path: Path = DEFAULT_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_private_text(path, json.dumps(asdict(config), indent=2) + "\n")


def _module_stores(tree, name):
    """Assignments in module control flow, excluding separate local scopes."""
    found = []
    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name:
            found.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(tree)
    return found


def _replace_configuration_values(text: str, replacements: dict[str, str], *, role: str | None = None) -> str:
    """Edit real Python values, rejecting missing/ambiguous assignments."""
    try:
        tree = ast.parse(text, feature_version=(3, 10))
    except SyntaxError:
        raise ValueError("legacy configuration is invalid Python") from None
    edits = []
    for name, value in replacements.items():
        assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                       and any(isinstance(target, ast.Name) and target.id == name
                               for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))]
        if len(assignments) != 1 or assignments[0].value is None:
            raise ValueError(f"expected one top-level assignment for {name}")
        if isinstance(assignments[0], ast.Assign) and len(assignments[0].targets) != 1:
            raise ValueError(f"chained assignment is unsupported for {name}")
        target = assignments[0].targets[0] if isinstance(assignments[0], ast.Assign) else assignments[0].target
        if _module_stores(tree, name) != [target]:
            raise ValueError(f"unsupported additional assignment for {name}")
        edits.append((assignments[0].value, value))
    if role is not None:
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and any(keyword.arg == "connection_type" for keyword in node.keywords)
                 and not (isinstance(node.func, ast.Attribute) and node.func.attr == "reconnect"
                          and isinstance(node.func.value, ast.Name) and node.func.value.id == "transport")]
        direct = [node.value for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]
        if any(call not in direct or not (
                getattr(call.func, "id", None) == "RelayTransport"
                or getattr(call.func, "attr", None) == "RelayTransport") for call in calls):
            raise ValueError("unsupported nested or indirect transport constructor")
        roles = [keyword.value for call in calls for keyword in call.keywords
                 if keyword.arg == "connection_type"]
        if not roles:
            assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                     and any(isinstance(target, ast.Name) and target.id == "connection_type"
                             for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))]
            if any(isinstance(node, ast.Assign) and len(node.targets) != 1 for node in assignments):
                raise ValueError("unsupported chained transport role")
            if len(_module_stores(tree, "connection_type")) != len(assignments):
                raise ValueError("unsupported additional transport role assignment")
            roles = [node.value for node in assignments]
        if len(roles) != 1 or not isinstance(roles[0], ast.Constant) or roles[0].value not in ("slave", "master"):
            raise ValueError("expected one supported transport connection_type")
        edits.append((roles[0], json.dumps(role)))
    # AST column offsets are UTF-8 byte offsets, including on Unicode lines.
    lines = text.encode("utf-8").splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    data = text.encode("utf-8")
    spans = [(starts[node.lineno - 1] + node.col_offset,
              starts[node.end_lineno - 1] + node.end_col_offset, value.encode("utf-8"))
             for node, value in edits]
    for start, end, value in sorted(spans, reverse=True):
        data = data[:start] + value + data[end:]
    return data.decode("utf-8")


def _patch_legacy_transport_logging(path: Path) -> bool:
    """Remove the verified legacy constructor's connection-key log."""
    text = path.read_text(encoding="utf-8")
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if backup.exists():
        backup.chmod(0o600)
    original = 'log.info("Connecting to %s channel %s" % (address, channel))'
    if original not in text:
        return False
    updated = text.replace(original, 'log.info("Connecting to remote relay %s", address)')
    try:
        compile(updated, str(path), "exec")
    except SyntaxError:
        raise ValueError("updated legacy transport would not compile") from None
    if not backup.exists():
        _write_private_text(backup, text)
    _write_private_text(path, updated)
    return True


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
    text = _replace_configuration_values(text, replacements, role=config.orca_connection_type)
    text = _redact_legacy_logs(text)

    pref_name = "LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH"
    pref_value = "True" if config.mute_local_orca_speech else "False"
    if any(isinstance(node, ast.Name) and node.id == pref_name and isinstance(node.ctx, ast.Store)
           for node in ast.walk(ast.parse(text))):
        text = _replace_configuration_values(text, {pref_name: pref_value})
    else:
        text = text.rstrip("\n") + "\n\n" + pref_name + " = " + pref_value + "\n"

    if text.count(LOCAL_SPEECH_PREF_MARKER) > 1:
        raise ValueError("multiple local speech preference patches")
    previous_hook = next((hook for hook in (_LOCAL_SPEECH_PREF_HOOK_V1, _LOCAL_SPEECH_PREF_HOOK_V2)
                          if hook in text), None)
    if previous_hook is not None:
        text = text.replace(previous_hook, _LOCAL_SPEECH_PREF_HOOK, 1)
    elif _LOCAL_SPEECH_PREF_HOOK not in text:
        if LOCAL_SPEECH_PREF_MARKER in text:
            raise ValueError("unrecognized local speech preference patch")
        text = text.rstrip("\n") + "\n\n" + _LOCAL_SPEECH_PREF_HOOK

    try:
        compile(text, str(path), "exec")
    except SyntaxError:
        raise ValueError("updated legacy configuration would not compile") from None
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if not backup.exists():
        _write_private_text(backup, path.read_text(encoding="utf-8"))
    # Both files can contain an NVDA Remote channel key: the live file has the
    # new key and the one-time backup may contain the previous key.
    for private_path in (backup, path):
        try:
            private_path.chmod(0o600)
        except OSError:
            pass
    _write_private_text(path, text)

    transport_path = path.parent / "orca-scripts" / "transport.py"
    if transport_path.exists():
        try:
            _patch_legacy_transport_logging(transport_path)
        except (ValueError, OSError) as exc:
            print("warning: transport logging patch not applied; repair required", file=sys.stderr)

    callback_path = path.parent / "orca-scripts" / "callback_manager.py"
    if callback_path.exists():
        original = callback_path.read_text(encoding="utf-8")
        updated = _redact_legacy_logs(original).replace('logger.exception(', 'logger.error(')
        if updated != original:
            compile(updated, str(callback_path), "exec")
            backup = callback_path.with_name(callback_path.name + '.linux-rdaccess-backup')
            if not backup.exists():
                _write_private_text(backup, original)
            else:
                backup.chmod(0o600)
            _write_private_text(callback_path, updated)

    remote_controller = path.parent / LEGACY_REMOTE_CONTROLLER_RELATIVE
    if remote_controller.exists():
        # Install the narrow Orca runtime adapter beside the legacy controller
        # so the injected shim can call Orca's active application script rather
        # than duplicating AT-SPI or braille behavior.
        adapter_source = Path(__file__).with_name("orca_adapter.py")
        adapter_target = remote_controller.parent / "linux_rdaccess_orca_adapter.py"
        if adapter_source.exists():
            shutil.copy2(adapter_source, adapter_target)
        # The input shim is an enhancement: a changed upstream layout must not
        # stop the connection settings above from being applied.
        try:
            patch_legacy_orca_remote_controller(remote_controller)
        except (ValueError, OSError) as exc:
            print(
                "warning: NVDA input compatibility patch not applied; repair required",
                file=sys.stderr,
            )
    local_machine = path.parent / LEGACY_LOCAL_MACHINE_RELATIVE
    if local_machine.exists():
        try:
            patch_legacy_orca_local_machine(local_machine)
        except (ValueError, OSError) as exc:
            print(
                "warning: low-latency key injection patch not applied; repair required",
                file=sys.stderr,
            )


LEGACY_REMOTE_CONTROLLER_RELATIVE = Path("orca-scripts/remote_controller.py")
LEGACY_COMPAT_MARKER_V1 = "# linux-rdaccess NVDA/Orca input compatibility"
LEGACY_COMPAT_MARKER_V2 = "# linux-rdaccess NVDA/Orca input compatibility v2"
LEGACY_COMPAT_MARKER_V3 = "# linux-rdaccess NVDA/Orca input compatibility v3"
LEGACY_COMPAT_MARKER_V4 = "# linux-rdaccess NVDA/Orca input compatibility v4"
LEGACY_COMPAT_MARKER_V7 = "# linux-rdaccess NVDA/Orca input compatibility v7"
LEGACY_COMPAT_MARKER_V8 = "# linux-rdaccess NVDA/Orca input compatibility v8"
LEGACY_COMPAT_MARKER_V9 = "# linux-rdaccess NVDA/Orca input compatibility v9"
LEGACY_COMPAT_MARKER_V10 = "# linux-rdaccess NVDA/Orca input compatibility v10"
LEGACY_COMPAT_MARKER_V11 = "# linux-rdaccess NVDA/Orca input compatibility v11"
LEGACY_COMPAT_MARKER_V12 = "# linux-rdaccess NVDA/Orca input compatibility v12"
LEGACY_COMPAT_MARKER_V13 = "# linux-rdaccess NVDA/Orca input compatibility v13"
LEGACY_COMPAT_MARKER_V14 = "# linux-rdaccess NVDA/Orca input compatibility v14"
LEGACY_COMPAT_MARKER_V15 = "# linux-rdaccess NVDA/Orca input compatibility v15"
LEGACY_COMPAT_MARKER_V16 = "# linux-rdaccess NVDA/Orca input compatibility v16"
LEGACY_COMPAT_MARKER_V17 = "# linux-rdaccess NVDA/Orca input compatibility v17"
LEGACY_COMPAT_MARKER_V18 = "# linux-rdaccess NVDA/Orca input compatibility v18"
LEGACY_COMPAT_MARKER_V19 = "# linux-rdaccess NVDA/Orca input compatibility v19"
LEGACY_COMPAT_MARKER_V20 = "# linux-rdaccess NVDA/Orca input compatibility v20"
LEGACY_COMPAT_MARKER_V21 = "# linux-rdaccess NVDA/Orca input compatibility v21"
LEGACY_COMPAT_MARKER_V22 = "# linux-rdaccess NVDA/Orca input compatibility v22"
LEGACY_COMPAT_MARKER_V23 = "# linux-rdaccess NVDA/Orca input compatibility v23"
LEGACY_COMPAT_MARKER_V24 = "# linux-rdaccess NVDA/Orca input compatibility v24"
LEGACY_COMPAT_MARKER_V25 = "# linux-rdaccess NVDA/Orca input compatibility v25"
LEGACY_COMPAT_MARKER_V26 = "# linux-rdaccess NVDA/Orca input compatibility v26"
LEGACY_COMPAT_MARKER_V27 = "# linux-rdaccess NVDA/Orca input compatibility v27"
LEGACY_COMPAT_MARKER_V28 = "# linux-rdaccess NVDA/Orca input compatibility v28"
LEGACY_COMPAT_MARKER_V29 = "# linux-rdaccess NVDA/Orca input compatibility v29"
LEGACY_COMPAT_MARKER_V30 = "# linux-rdaccess NVDA/Orca input compatibility v30"
LEGACY_COMPAT_MARKER = "# linux-rdaccess NVDA/Orca input compatibility v31"
# v1 is a prefix of every later marker, so any older patch is detected by it.

_LEGACY_HELPERS = '''\
    ''' + LEGACY_COMPAT_MARKER + '''
    # Helpers injected by linux-rdaccess. They never log key names, braille
    # dots, speech text or connection keys.
    _LRD_INPUT_LOCK = __import__("threading").RLock()
    _LRD_CTRL_VKS = (0x11, 0xA2, 0xA3)
    _LRD_MODIFIER_VKS = (
        0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5,
        0x5B, 0x5C, 0x2D, 0x14,
    )  # Shift, Ctrl, Alt, Win, Insert, CapsLock (NVDA modifier keys)
    _LRD_BRAILLE_ACTIONS = {
        "braille_scrollBack": "pan_back",
        "braille_scrollForward": "pan_forward",
        "braille_routeTo": "route",
        "braille_toFocus": "to_focus",
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
    _LRD_ACTION_CHORDS = {
        0x09: "where_am_i",                          # NVDA+Tab
        0x23: "status_bar",                          # NVDA+End
        0x54: "title",                               # NVDA+T
        0x71: "pass_next",                           # NVDA+F2
        0x76: "elements_list",                       # NVDA+F7
    }
    _LRD_SHIFT_VKS = (0x10, 0xA0, 0xA1)
    _LRD_NVDA_VKS = (0x2D, 0x14)
    # Key: (vk, Shift held). Value: (extended-required, Orca key name, target
    # vk, drop NVDA modifier, press count, drop Shift). Orca matches the
    # modifier state exactly, so Shift is released around the key when Orca's
    # binding has none (verified against Orca 42 key matching).
    _LRD_CHORDS = {
    }

    def _linux_rdaccess_stop_local_speech(self):
        """Stop Linux-side speech on Orca's main loop, never on the network thread.

        Orca's speech-dispatcher client is not thread-safe and a stop blocks
        until speech-dispatcher answers. Doing that on the thread that receives
        keys stalled all key forwarding whenever Orca was busy (Firefox), which
        looked like a freeze. Requests are coalesced: at most one is pending.
        """
        if getattr(self, "_lrd_local_stop_pending", False):
            return
        self._lrd_local_stop_pending = True

        def run():
            self._lrd_local_stop_pending = False
            try:
                self.local_machine.cancel_speech()
            except Exception:
                log.error("linux-rdaccess: failed to cancel speech")

        if self._linux_rdaccess_run_main(run) is False:
            self._lrd_local_stop_pending = False

    def _linux_rdaccess_stop_nvda_speech(self):
        """Tell the controlling NVDA to stop speaking *now*.

        Orca's own stop only silences Linux; upstream defers the NVDA cancel
        until the next utterance, so Ctrl with no speech after it never
        reached Windows. Send the protocol "cancel" message immediately.
        """
        try:
            transport = getattr(self, "transport", None)
            if (
                transport is not None
                and getattr(transport, "connected", False)
                and getattr(transport, "connection_type", None) == "slave"
            ):
                transport.send(type="cancel")
        except Exception:
            log.error("linux-rdaccess: failed to send cancel to NVDA")

    @staticmethod
    def _linux_rdaccess_key_identity(vk_code, extended, key_name=None):
        return (vk_code if vk_code is not None else key_name, bool(extended))

    def _linux_rdaccess_forward_key(self, **kwargs):
        """Own successful forwards, retaining the original release payload."""
        held = self._linux_rdaccess_key_identity(
            kwargs.get("vk_code"), kwargs.get("extended"), kwargs.get("key_name"))
        forwarded = getattr(self, "_lrd_forwarded", None)
        if forwarded is None:
            forwarded = self._lrd_forwarded = {}
        pressed = bool(kwargs.get("pressed"))
        if not pressed and held not in forwarded:
            return False
        payload = dict(forwarded[held], pressed=pressed) if held in forwarded else kwargs
        result = self.local_machine.send_key(**payload)
        if result is not False:
            if pressed:
                forwarded[held] = dict(payload)
            else:
                forwarded.pop(held, None)
        return result

    def _linux_rdaccess_reset_keys(self):
        """Release forwarded held keys and clear compatibility state.

        Remote disconnects/control hand-offs can lose key-up events. Only
        successful forwards acquire release ownership; failed releases remain
        owned so a later reset can retry them.
        """
        forwarded = getattr(self, "_lrd_forwarded", {})
        send = getattr(getattr(self, "local_machine", None), "send_key", None)
        if callable(send):
            order = lambda item: (isinstance(item[0], str), str(item[0]) if isinstance(item[0], str) else item[0] or 0, item[1])
            for held in sorted(list(forwarded), key=order):
                try:
                    release = dict(forwarded[held], pressed=False)
                    if send(**release) is not False:
                        forwarded.pop(held, None)
                except Exception:
                    log.error("linux-rdaccess: failed to release held key on reset")
        self._lrd_down = set()
        self._lrd_nvda_down = False
        self._lrd_swapped = set()
        self._lrd_nvda_key = None
        self._lrd_caps_pending = None
        self._lrd_caps_used = False
        self._lrd_bypass_next = False
        self._lrd_generation = getattr(self, "_lrd_generation", 0) + 1
        self._lrd_local_stop_pending = False
        marker = globals().get("_LRD_D")
        if isinstance(marker, dict):
            marker["ts"] = 0.0
            marker["swapped"] = False
            marker["modifiers"] = 0
            marker["code"] = None

    def _linux_rdaccess_flush_pending_caps(self):
        """Forward a deferred CapsLock press when it was not an NVDA command."""
        held = getattr(self, "_lrd_caps_pending", None)
        if held is None:
            return
        self._lrd_caps_pending = None
        self._lrd_caps_used = False
        try:
            self._linux_rdaccess_forward_key(
                key_name=None, pressed=True, modifiers=None,
                vk_code=held[0], scan_code=0, extended=held[1])
        except Exception:
            log.error("linux-rdaccess: failed to forward deferred CapsLock")

    def _linux_rdaccess_sync_state(self):
        """Initialize/change the input generation for either input channel."""
        state = (
            getattr(self, "control_state", None),
            bool(getattr(getattr(self, "transport", None), "connected", True)),
            getattr(getattr(self, "transport", None), "connection_type", None),
            id(getattr(self, "transport", None)),
        )
        if getattr(self, "_lrd_state", None) != state:
            # Control moved local/remote or the transport reconnected. Release
            # keys that were actually forwarded before forgetting state; a
            # missing remote key-up must never leave Linux with a stuck arrow
            # or modifier after reconnect.
            self._linux_rdaccess_reset_keys()
            self._lrd_state = state

    def _linux_rdaccess_filter_key(self, pressed, vk_code, extended, modifiers,
                                   key_name=None, scan_code=None):
        """Return True when the event was fully handled here."""
        self._linux_rdaccess_sync_state()
        pressed = bool(pressed)
        held = self._linux_rdaccess_key_identity(vk_code, extended, key_name)
        repeat = pressed and held in self._lrd_down
        if pressed:
            self._lrd_down.add(held)
        else:
            self._lrd_down.discard(held)
        if vk_code in self._LRD_NVDA_VKS:
            nvda_keys = sorted(
                (k for k in self._lrd_down if k[0] in self._LRD_NVDA_VKS),
                key=lambda k: (k[0] == 0x14, k[0], k[1]),
            )
            self._lrd_nvda_down = bool(nvda_keys)
            # Prefer Insert when both configured NVDA modifiers are held. It
            # can be temporarily released for Orca commands that require no
            # modifier; CapsLock cannot be safely released/re-pressed because
            # doing so would toggle the lock state.
            self._lrd_nvda_key = nvda_keys[0] if nvda_keys else None
            if (
                pressed
                and vk_code != 0x14
                and vk_code in self._LRD_NVDA_VKS
                and getattr(self, "_lrd_caps_pending", None) is not None
            ):
                self._lrd_caps_used = True

        # CapsLock can be configured as the NVDA modifier. Forwarding its press
        # immediately toggles Linux Caps Lock before we know whether this is a
        # translated NVDA command, so defer it until the gesture is known.
        if vk_code == 0x14:
            pending = getattr(self, "_lrd_caps_pending", None)
            if pressed:
                if not repeat:
                    self._lrd_caps_pending = held
                    self._lrd_caps_used = any(
                        k != held and k[0] in self._LRD_NVDA_VKS
                        for k in self._lrd_down
                    )
                return True
            if pending == held:
                used = bool(getattr(self, "_lrd_caps_used", False))
                if used:
                    self._lrd_caps_pending = None
                    self._lrd_caps_used = False
                    return True
                self._linux_rdaccess_flush_pending_caps()
                return False

        # Interrupt stale speech on a real action, as NVDA does. Plain
        # modifier keys (and their auto-repeat) must not cut off speech that
        # a chord such as NVDA+Down started; Ctrl itself does interrupt.
        if pressed and (
            vk_code not in self._LRD_MODIFIER_VKS
            or (vk_code in self._LRD_CTRL_VKS and not repeat)
        ):
            # Auto-repeat re-cancels at most every 150 ms: Orca's own new
            # speech interrupts per item anyway, and a cancel per repeat event
            # floods the speech server during held arrow keys.
            _now = __import__("time").monotonic()
            if not repeat or _now - getattr(self, "_lrd_last_cancel", 0.0) >= 0.15:
                self._lrd_last_cancel = _now
                # Local Orca speech is stopped on Orca's main loop, never on this
                # network thread (see _linux_rdaccess_stop_local_speech).
                self._linux_rdaccess_stop_local_speech()
                # Ctrl is the explicit NVDA "stop speech" gesture. Local Orca
                # cancellation alone cannot remove speech already queued on the
                # Windows NVDA side, so send the NVDA Remote cancel message too.
                # Restrict the protocol cancel to Ctrl to avoid adding a network
                # round-trip to every ordinary navigation key.
                if vk_code in self._LRD_CTRL_VKS and not repeat:
                    self._linux_rdaccess_stop_nvda_speech()

        # Consumed presses retain ownership of their repeat/release even if
        # pass-next has just been armed (notably the F2 which armed it).
        if held in self._lrd_swapped:
            if not pressed:
                self._lrd_swapped.discard(held)
            return True

        # Orca's bypass flag is cleared by its keyboard-event processing. Arm
        # a local latch when scheduling NVDA+F2 as well: the receive thread can
        # see the next key before the GLib callback has set Orca's flag.
        bypass = getattr(self, "_lrd_bypass_next", False)
        try:
            from orca import orca_state as _state
            bypass = bypass or bool(getattr(_state, "bypassNextCommand", False))
        except ImportError:
            pass
        if bypass:
            if pressed and vk_code not in self._LRD_MODIFIER_VKS:
                self._lrd_bypass_next = False
                self._linux_rdaccess_flush_pending_caps()
            return False

        # Remember that a plain (or Shift) D came from the remote session, so the
        # Orca-side hook below can turn it into the landmark key in browse mode
        # only. Nothing is translated here; the key is forwarded unchanged.
        if pressed and vk_code == 0x44 and not self._lrd_nvda_down and not any(
                k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in (0x10, 0xA0, 0xA1)
                for k in self._lrd_down):
            _LRD_D["ts"] = __import__("time").monotonic()

        # NVDA+Down has an exact Orca Say All method. Only the extended
        # navigation Down key is NVDA's gesture; the non-extended VK form is
        # the numeric keypad key and must continue to pass through unchanged.
        if (
            pressed
            and self._lrd_nvda_down
            and not repeat
            and vk_code == 0x28
            and bool(extended)
            and not any(k[0] in self._LRD_SHIFT_VKS for k in self._lrd_down)
            and not any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down)
        ):
            self._lrd_swapped.add(held)
            if getattr(self, "_lrd_caps_pending", None) is not None:
                self._lrd_caps_used = True
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call("sayAll"))
            return True

        # NVDA+Space and NVDA+Shift+Space have exact Orca APIs. Calling
        # them directly avoids assuming the Windows NVDA modifier (Insert or
        # CapsLock) is also configured as Orca's physical modifier.
        if pressed and self._lrd_nvda_down and not repeat and vk_code == 0x20:
            shifts = [k for k in self._lrd_down if k[0] in self._LRD_SHIFT_VKS]
            if not any(
                k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
                for k in self._lrd_down
            ):
                self._lrd_swapped.add(held)
                if getattr(self, "_lrd_caps_pending", None) is not None:
                    self._lrd_caps_used = True
                if shifts:
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call(
                            "toggleStructuralNavigation"))
                else:
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call(
                            "togglePresentationMode"))
                return True

        # NVDA-only actions that do not map cleanly to one Orca key.
        if pressed and self._lrd_nvda_down and not repeat:
            action = self._LRD_ACTION_CHORDS.get(vk_code)
            if (
                action is not None
                and not any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down)
                and not (action == "status_bar" and not bool(extended))
            ):
                self._lrd_swapped.add(held)
                if getattr(self, "_lrd_caps_pending", None) is not None:
                    self._lrd_caps_used = True
                if action == "elements_list":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_show_elements_list(modifiers))
                elif action == "pass_next":
                    self._lrd_bypass_next = True
                    if self._linux_rdaccess_run_main(
                            self._linux_rdaccess_activate_bypass) is False:
                        self._lrd_bypass_next = False
                elif action == "where_am_i":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("whereAmI"))
                elif action == "title":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("presentTitle"))
                elif action == "status_bar":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("presentStatusBar"))
                return True

        # NVDA chords -> Orca commands (see _LRD_CHORDS). Only the first press
        # with the NVDA modifier held and no Shift/Ctrl/Alt/Win is translated;
        # auto-repeat is consumed, and a release is consumed only for a
        # translated press, so a normally forwarded key is never left stuck.
        if pressed:
            if held in self._lrd_swapped:
                return True  # auto-repeat of this translated physical key
            shifts = [k for k in self._lrd_down if k[0] in self._LRD_SHIFT_VKS]
            chord = self._LRD_CHORDS.get((vk_code, bool(shifts)))
            if (
                chord is None
                or repeat
                or not self._lrd_nvda_down
                or any(k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
                       for k in self._lrd_down)
                or bool(extended) != chord[0]
            ):
                if (
                    not repeat
                    and vk_code not in self._LRD_MODIFIER_VKS
                    and getattr(self, "_lrd_caps_pending", None) is not None
                ):
                    self._linux_rdaccess_flush_pending_caps()
                return False
            need_ext, name, target_vk, drop, count, drop_shift = chord
            nvda = self._lrd_nvda_key
            if drop and (nvda is None or nvda[0] == 0x14):
                # Re-pressing CapsLock would toggle the lock state.
                return False
            self._lrd_swapped.add(held)
            if getattr(self, "_lrd_caps_pending", None) is not None:
                self._lrd_caps_used = True
            send = self.local_machine.send_key
            if drop:
                send(key_name=None, pressed=False, modifiers=modifiers,
                     vk_code=nvda[0], scan_code=0, extended=nvda[1])
            if drop_shift:
                for held_vk, held_ext in shifts:
                    send(key_name=None, pressed=False, modifiers=modifiers,
                         vk_code=held_vk, scan_code=0, extended=held_ext)
            for _ in range(count):
                for down in (True, False):
                    send(key_name=name, pressed=down, modifiers=modifiers,
                         vk_code=target_vk, scan_code=0, extended=False)
            if drop_shift:
                for held_vk, held_ext in shifts:
                    send(key_name=None, pressed=True, modifiers=modifiers,
                         vk_code=held_vk, scan_code=0, extended=held_ext)
            if drop:
                send(key_name=None, pressed=True, modifiers=modifiers,
                     vk_code=nvda[0], scan_code=0, extended=nvda[1])
            return True
        if held in self._lrd_swapped:
            self._lrd_swapped.discard(held)
            return True
        return False

    def _linux_rdaccess_activate_bypass(self):
        if self._linux_rdaccess_script_call("bypassNextCommand") is False:
            self._lrd_bypass_next = False

    def _linux_rdaccess_classify_braille(self, kwargs):
        """Validate protocol shapes; persist only canonical command metadata."""
        invalid = (None, {"redacted": "invalid-braille-input"})
        identifiers = kwargs.get("identifiers", [])
        gesture_id = kwargs.get("id")
        if not isinstance(identifiers, (list, tuple)) or not all(
                isinstance(item, str) for item in identifiers):
            return invalid
        if gesture_id is not None and not isinstance(gesture_id, str):
            return invalid
        script = kwargs.get("scriptPath")
        if "scriptPath" in kwargs and (
                not isinstance(script, (list, tuple)) or len(script) != 3
                or not all(isinstance(part, str) and part for part in script)):
            return invalid
        name = script[-1] if script else ""
        if name.startswith("script_"):
            name = name[len("script_"):]
        dots, space = kwargs.get("dots", 0), kwargs.get("space", False)
        if (not isinstance(dots, int) or not 0 <= dots <= 255
                or not isinstance(space, (bool, int)) or space < 0):
            return invalid
        ids = ([gesture_id] if gesture_id else []) + list(identifiers)

        def is_input(value):
            import re as _re
            tokens = _re.split(r"[^a-z0-9]+", value.lower())
            return (value.lower().startswith("bk:") or "space" in tokens
                    or any(token in ("dot1", "dot2", "dot3", "dot4",
                                     "dot5", "dot6", "dot7", "dot8")
                           for token in tokens))

        if dots or space or any(is_input(value) for value in ids) or name.startswith("kb:") or name == "braille_dots":
            return "keyboard", {"redacted": "braille-keyboard-input"}
        action = (self._LRD_BRAILLE_ACTIONS.get(name)
                  if script and tuple(script[:2]) == ("globalCommands", "GlobalCommands")
                  else None)
        if action is None and "scriptPath" not in kwargs and (
                "routingIndex" in kwargs or "cellIndexes" in kwargs):
            action = "route"
        if action is None:
            return None, {"redacted": "unknown-braille-input"}
        # Driver ids, identifiers, model/source and unknown script paths can
        # encode characters. They are never persisted, even with trace enabled.
        record = {"action": action}
        if script:
            record["scriptPath"] = ["globalCommands", "GlobalCommands", name]
        return action, record

    def _linux_rdaccess_trace_braille(self, record):
        import json as _json
        import os as _os
        if _os.environ.get("LINUX_RDACCESS_BRAILLE_TRACE") != "1":
            return
        path = _os.path.expanduser(
            "~/.local/share/orca/orca-remote-braille-input.log")
        try:
            # An existing trace may predate private creation permissions.
            # Protect it before rotation, including the resulting .1 file.
            _os.chmod(path, 0o600)
            if _os.path.getsize(path) > self._LRD_TRACE_MAX_BYTES:
                _os.replace(path, path + ".1")
        except OSError:
            pass
        fd = _os.open(path, _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT, 0o600)
        try:
            handle = _os.fdopen(fd, "a", encoding="utf-8")
        except BaseException:
            _os.close(fd)
            raise
        with handle:
            _os.fchmod(handle.fileno(), 0o600)
            handle.write(_json.dumps(record, sort_keys=True) + "\\n")
        try:
            _os.chmod(path, 0o600)
        except OSError:
            pass

    def _linux_rdaccess_run_main(self, func):
        self._linux_rdaccess_sync_state()
        generation = getattr(self, "_lrd_generation", 0)

        def invoke():
            self._linux_rdaccess_sync_state()
            # A disconnected controller's queued command must not operate on
            # the new session/focus, or cancel speech started after handoff.
            if generation == getattr(self, "_lrd_generation", 0):
                try:
                    func()
                except Exception:
                    log.error("linux-rdaccess: queued Orca operation failed")
            return False

        try:
            from gi.repository import GLib
        except Exception:
            invoke()
            return True
        try:
            source = GLib.idle_add(invoke)
            if source == 0:
                raise RuntimeError("idle source was not registered")
        except Exception:
            log.error("linux-rdaccess: failed to schedule Orca operation")
            return False
        return True

    def _linux_rdaccess_handle_braille_input(self, kwargs):
        self._linux_rdaccess_sync_state()
        action, record = self._linux_rdaccess_classify_braille(kwargs)
        try:
            self._linux_rdaccess_trace_braille(record)
        except Exception:
            log.error("linux-rdaccess: failed to trace braille input")
        if action in ("pan_back", "pan_forward"):
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call(
                    "panBrailleLeft" if action == "pan_back" else "panBrailleRight"))
        elif action == "to_focus":
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call("goBrailleHome"))
        elif action == "route":
            index = kwargs.get("routingIndex")
            if "cellIndexes" in kwargs:
                cell_indexes = kwargs["cellIndexes"]
                if not isinstance(cell_indexes, (list, tuple)) or len(cell_indexes) != 1:
                    return
                cell = cell_indexes[0]
                if isinstance(cell, bool) or not isinstance(cell, int):
                    return
                # Modern metadata must be unambiguous even when a legacy
                # field is also supplied. Never turn a multi-cell selection
                # or conflicting positions into a single routing action.
                if index is not None and (isinstance(index, bool) or not isinstance(index, int) or index != cell):
                    return
                index = cell
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 1024:
                return
            import types as _types
            event = _types.SimpleNamespace(event={"argument": index})
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call("processRoutingKey", event))

    def _linux_rdaccess_send_structural_list(self, key, modifiers):
        """Ask Orca to show one of its native structural-navigation lists.

        Legacy LocalMachine.send_key accepts a modifiers argument but does not
        apply it during injection. Press Alt and Shift as real key events so
        Orca receives the actual Alt+Shift+letter binding.
        """
        vk = ord(str(key)[0].upper())
        # A synthetic release must not release a remotely held letter.
        if (vk, False) in getattr(self, "_lrd_forwarded", {}):
            return
        send = self._linux_rdaccess_forward_key
        held_modifiers = (
            ("Shift_L", 0xA0, False),
            ("Alt_L", 0xA4, False),
        )
        pressed_modifiers = []
        try:
            for name, mod_vk, mod_ext in held_modifiers:
                # Upstream maps generic Shift/Alt and their left VKs to the
                # same Linux keys. Borrow either alias instead of releasing
                # a modifier held by the Windows controller.
                generic_vk = 0x10 if mod_vk == 0xA0 else 0x12
                if any(held_vk == mod_vk or (held_vk == generic_vk and not held_ext)
                       for held_vk, held_ext in getattr(self, "_lrd_forwarded", {})):
                    continue
                if send(
                    key_name=name, pressed=True, modifiers=None,
                    vk_code=mod_vk, scan_code=0, extended=mod_ext) is False:
                    return
                pressed_modifiers.append((name, mod_vk, mod_ext))
            for down in (True, False):
                if send(
                    key_name=str(key).lower(),
                    pressed=down,
                    modifiers=None,
                    vk_code=vk,
                    scan_code=0,
                    extended=False,
                ) is False:
                    return
        finally:
            # A failed letter release must be retried before modifier cleanup.
            if (vk, False) in getattr(self, "_lrd_forwarded", {}):
                try:
                    send(key_name=str(key).lower(), pressed=False, modifiers=None,
                         vk_code=vk, scan_code=0, extended=False)
                except Exception:
                    log.error("linux-rdaccess: failed to release structural-list key")
            for name, mod_vk, mod_ext in reversed(pressed_modifiers):
                try:
                    send(
                        key_name=name, pressed=False, modifiers=None,
                        vk_code=mod_vk, scan_code=0, extended=mod_ext)
                except Exception:
                    log.error(
                        "linux-rdaccess: failed to release structural-list modifier")

    def _linux_rdaccess_open_structural_list(self, key, modifiers):
        """Prefer Orca's native structural-list API; retain key fallback."""
        try:
            from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter as _adapter
            if _adapter.show_structural_list(key):
                return
        except ImportError:
            pass
        except Exception:
            log.error("linux-rdaccess: native structural list failed")

        # Adapter unavailable or this Orca version does not expose the object.
        # Fall back to the verified Orca 42 Alt+Shift+letter binding.
        self._linux_rdaccess_send_structural_list(key, modifiers)

    def _linux_rdaccess_show_elements_list(self, modifiers):
        self._linux_rdaccess_sync_state()
        generation = getattr(self, "_lrd_generation", 0)

        def open_list(key):
            # Gtk.Dialog.run() processes a nested main loop. Recheck ownership
            # after it returns, just as for a queued top-level command.
            self._linux_rdaccess_sync_state()
            if generation == getattr(self, "_lrd_generation", 0):
                self._linux_rdaccess_open_structural_list(key, modifiers)

        try:
            from linux_rdaccess_orca_adapter import show_elements_list as _show
            result = _show(open_list)
            if result is not None:
                # True: category selected and delegated to Orca.
                # False: the dialog was intentionally cancelled/Escaped.
                return
        except Exception:
            log.error("linux-rdaccess: elements list failed")

        # Safe fallback only when the chooser could not be presented.
        open_list("h")

    @staticmethod
    def _linux_rdaccess_script_call(method, *args):
        """Run an Orca operation through the linux-rdaccess Orca API adapter.

        The adapter keeps Orca-version compatibility in one place and delegates
        to the active application script, preserving Orca's GTK/web/terminal
        semantics. A direct fallback keeps older installs functional if the
        adapter file cannot be imported.
        """
        def unavailable():
            log.error("linux-rdaccess: unavailable Orca operation: %s", method)
            return False

        try:
            from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter as _adapter
            handlers = {
                "panBrailleLeft": "pan_braille_left",
                "panBrailleRight": "pan_braille_right",
                "processRoutingKey": "route_braille",
                "goBrailleHome": "to_braille_focus",
                "bypassNextCommand": "bypass_next_command",
                "whereAmI": "where_am_i",
                "presentTitle": "present_title",
                "presentStatusBar": "present_status_bar",
                "togglePresentationMode": "toggle_presentation_mode",
                "toggleStructuralNavigation": "toggle_structural_navigation",
                "sayAll": "say_all",
            }
            adapter_method = handlers.get(method)
            adapter_args = args
            if method == "processRoutingKey" and args:
                adapter_args = (args[0].event["argument"],)
            if adapter_method:
                handler = getattr(_adapter, adapter_method, None)
                if callable(handler) and handler(*adapter_args):
                    return True
            elif _adapter.call_script(method, *args, default_event=not args):
                return True
            # False denotes no supported adapter operation, not an invocation.
            # Try the verified legacy API instead of stopping at module import.
        except ImportError:
            pass
        except Exception:
            # An exception can contain application text. Do not persist it or
            # retry a handler which may already have performed part of its work.
            log.error("linux-rdaccess: Orca adapter operation failed: %s", method)
            return False

        try:
            from orca import orca_state as _state
            script = getattr(_state, "activeScript", None)
            if script is None:
                script = getattr(_state, "active_script", None)
            if script is None:
                return unavailable()
            if method == "toggleStructuralNavigation":
                nav = getattr(script, "structuralNavigation", None)
                if nav is None:
                    nav = getattr(script, "structural_navigation", None)
                handler = getattr(nav, "toggleStructuralNavigation", None) if nav is not None else None
                if not callable(handler) and nav is not None:
                    handler = getattr(nav, "toggle_structural_navigation", None)
                if callable(handler):
                    return handler(script, None) is not False
                return unavailable()
            if method == "whereAmI":
                handler = None
                for name in (
                    "whereAmIBasic", "where_am_i_basic",
                    "whereAmI", "where_am_i",
                    "presentCurrentObject", "present_current_object",
                ):
                    candidate = getattr(script, name, None)
                    if callable(candidate):
                        handler = candidate
                        break
                if handler is not None:
                    return handler(None) is not False
                return unavailable()
            handler = getattr(script, method, None)
            if handler is None:
                return unavailable()
            if not args:
                # Orca 42 requires inputEvent for sayAll, presentTitle,
                # presentStatusBar and togglePresentationMode. The adapter
                # supplies None; the fallback must use the same signature.
                return handler(None) is not False
            else:
                return handler(*args) is not False
        except Exception:
            log.error("linux-rdaccess: Orca operation failed: %s", method)
            return False

'''

_LEGACY_ORCA_D_HOOK = '''
''' + LEGACY_COMPAT_MARKER + '''
# NVDA's D (landmark) is Orca's M; Orca's own D is "live region". Translate only
# for a D that arrived from the remote session AND only where Orca itself would
# use structural navigation (web document, browse mode). Everywhere else D is
# left alone, so typing "d" in a field, the address bar or focus mode is never
# remapped. Runs on Orca's main thread inside KeyboardEvent.shouldConsume (Orca
# captures the key handler there, before consumesKeyboardEvent), then restores
# hw_code so echo, double-click detection and release matching see the real key.
# Opt out with LINUX_RDACCESS_NVDA_D_LANDMARK=0.
_LRD_D = {"ts": 0.0, "swapped": False, "modifiers": 0, "code": None}
_LRD_D_WINDOW = 1.0


def _lrd_maybe_swap_d(event, keybindings):
    """Return the original hw_code if the event was swapped to M, else None."""
    if __import__("os").environ.get("LINUX_RDACCESS_NVDA_D_LANDMARK") == "0":
        return None
    if getattr(event, "event_string", None) not in ("d", "D"):
        return None
    pressed = event.isPressedKey()
    if not pressed:
        if not _LRD_D["swapped"]:
            return None
        # A translated key-up must follow the identity chosen for its key-down.
        # Do not re-evaluate Ctrl/Alt/Orca modifiers or browse/focus mode here:
        # those can legitimately change while D is held, and sending D-up after
        # an M-down creates an unmatched structural-navigation key sequence.
        code = _LRD_D.get("code")
        if not code:
            _LRD_D["swapped"] = False
            _LRD_D["modifiers"] = 0
            _LRD_D["code"] = None
            return None
        original = (event.hw_code, event.modifiers)
        event.hw_code = code
        event.modifiers = _LRD_D.get("modifiers", 0)
        _LRD_D["swapped"] = False
        _LRD_D["modifiers"] = 0
        _LRD_D["code"] = None
        return original

    # The marker belongs to exactly one D that Orca evaluates, whether or
    # not it ends up translated; otherwise a refused remote D (focus mode)
    # would leak into a later local D.
    fresh = __import__("time").monotonic() - _LRD_D["ts"] <= _LRD_D_WINDOW
    _LRD_D["ts"] = 0.0
    _LRD_D["swapped"] = False
    if not fresh:
        return None
    blocked = (keybindings.CTRL_MODIFIER_MASK | keybindings.ALT_MODIFIER_MASK
               | keybindings.ORCA_MODIFIER_MASK)
    if event.modifiers & blocked:
        return None
    script = getattr(event, "_script", None)
    nav = getattr(script, "structuralNavigation", None)
    gate = getattr(script, "useStructuralNavigationModel", None)
    if nav is None or gate is None:
        return None
    if pressed and not gate():
        return None
    code = keybindings.getKeycode("m")
    if not code:
        return None
    original = (event.hw_code, event.modifiers)
    event.hw_code = code
    handler = script.keyBindings.getInputHandler(event)
    if handler is None or handler.function not in nav.functions:
        event.hw_code, event.modifiers = original
        return None
    if pressed:
        _LRD_D["ts"] = 0.0
        _LRD_D["swapped"] = True
        _LRD_D["modifiers"] = event.modifiers
        _LRD_D["code"] = code
    else:
        _LRD_D["swapped"] = False
        _LRD_D["modifiers"] = 0
        _LRD_D["code"] = None
    return original


def _lrd_install_orca_hook():
    try:
        from orca import input_event, keybindings
    except Exception:
        return False
    cls = input_event.KeyboardEvent
    if getattr(cls, "_lrd_d_hooked", False):
        return True
    original = cls.shouldConsume

    def shouldConsume(self):
        restore = None
        try:
            restore = _lrd_maybe_swap_d(self, keybindings)
        except Exception:
            log.error("linux-rdaccess: D landmark translation failed")
        try:
            return original(self)
        finally:
            if restore is not None:
                self.hw_code, self.modifiers = restore

    cls.shouldConsume = shouldConsume
    cls._lrd_d_hooked = True
    return True


def _lrd_schedule_orca_hook():
    try:
        from gi.repository import GLib
        GLib.idle_add(lambda: (_lrd_install_orca_hook(), False)[1])
    except Exception:
        pass


_lrd_schedule_orca_hook()
'''

_LEGACY_SLOW_EVENT_HOOK = (
    LEGACY_COMPAT_MARKER + "\n"
    "# With LINUX_RDACCESS_DEBUG=1, log when handling one inbound key stalls the\n"
    "# receive thread. Only the duration and press/release are recorded, never\n"
    "# which key, so typed passwords cannot leak.\n"
    "_lrd_original_on_key = RemoteController._on_remote_key\n"
    "\n"
    "def _lrd_timed_on_key(self, *args, **kwargs):\n"
    "    if not __import__(\"os\").environ.get(\"LINUX_RDACCESS_DEBUG\"):\n"
    "        return _lrd_original_on_key(self, *args, **kwargs)\n"
    "    _t = __import__(\"time\").monotonic()\n"
    "    try:\n"
    "        return _lrd_original_on_key(self, *args, **kwargs)\n"
    "    finally:\n"
    "        _ms = (__import__(\"time\").monotonic() - _t) * 1000\n"
    "        if _ms > 20:\n"
    "            try:\n"
    "                _p = __import__(\"os\").path.expanduser(\n"
    "                    \"~/.local/share/orca/orca-remote-slow-events.log\")\n"
    "                _os = __import__(\"os\")\n"
    "                _fd = _os.open(_p, _os.O_WRONLY | _os.O_APPEND | _os.O_CREAT, 0o600)\n"
    "                try:\n"
    "                    _f = _os.fdopen(_fd, \"a\", encoding=\"utf-8\")\n"
    "                except BaseException:\n"
    "                    _os.close(_fd)\n"
    "                    raise\n"
    "                with _f:\n"
    "                    _os.fchmod(_f.fileno(), 0o600)\n"
    "                    _f.write(\"%.3f key-event handling took %.0f ms (%s)\\n\" % (\n"
    "                        __import__(\"time\").time(), _ms,\n"
    "                        \"press\" if kwargs.get(\"pressed\") else \"release\"))\n"
    "            except Exception:\n"
    "                pass\n"
    "\n"
    "_lrd_timed_on_key.__name__ = _lrd_original_on_key.__name__\n"
    "RemoteController._on_remote_key = _lrd_timed_on_key\n"
)

_LEGACY_RESET_HOOKS = (
    LEGACY_COMPAT_MARKER + "\n"
    "# Control hand-over and reconnects forget held-key state, even when no key\n"
    "# event arrives in between.\n"
    "def _linux_rdaccess_wrap_input(name):\n"
    "    original = getattr(RemoteController, name)\n"
    "    def wrapper(self, *args, **kwargs):\n"
    "        with self._LRD_INPUT_LOCK:\n"
    "            try:\n"
    "                return original(self, *args, **kwargs)\n"
    "            except Exception:\n"
    "                if name != \"_on_remote_key\":\n"
    "                    raise\n"
    "                # The upstream callback manager logs uncaught tracebacks.\n"
    "                log.error(\"linux-rdaccess: remote key injection failed\")\n"
    "    wrapper.__name__ = original.__name__\n"
    "    setattr(RemoteController, name, wrapper)\n"
    "\n"
    "for _lrd_name in (\"_on_remote_key\", \"_linux_rdaccess_reset_keys\",\n"
    "                  \"_linux_rdaccess_send_structural_list\"):\n"
    "    _linux_rdaccess_wrap_input(_lrd_name)\n"
    "\n"
    "def _linux_rdaccess_wrap_reset(name):\n"
    "    original = getattr(RemoteController, name, None)\n"
    "    if original is None:\n"
    "        return\n"
    "    def wrapper(self, *args, **kwargs):\n"
    "        with self._LRD_INPUT_LOCK:\n"
    "            try:\n"
    "                self._linux_rdaccess_reset_keys()\n"
    "            finally:\n"
    "                self._lrd_state = None\n"
    "            return original(self, *args, **kwargs)\n"
    "    wrapper.__name__ = original.__name__\n"
    "    setattr(RemoteController, name, wrapper)\n"
    "\n\n"
    "for _lrd_name in (\"toggle_control\", \"disconnect\",\n"
    "                  \"_on_transport_connected\", \"_on_transport_disconnected\"):\n"
    "    _linux_rdaccess_wrap_reset(_lrd_name)\n"
    "\n"
    "_lrd_original_client_left = getattr(RemoteController, \"_on_client_left\", None)\n"
    "if _lrd_original_client_left is not None:\n"
    "    def _lrd_on_client_left(self, client=None, **kwargs):\n"
    "        # A reconnect can start a new receiver before the old one exits.\n"
    "        with self._LRD_INPUT_LOCK:\n"
    "            if isinstance(client, dict):\n"
    "                known = getattr(self, \"connected_clients\", {}).get(client.get(\"id\"), {})\n"
    "                role = client.get(\"connection_type\") or known.get(\"connection_type\")\n"
    "                if role == \"master\":\n"
    "                    self._linux_rdaccess_reset_keys()\n"
    "                    self._lrd_state = None\n"
    "            return _lrd_original_client_left(self, client=client, **kwargs)\n"
    "    RemoteController._on_client_left = _lrd_on_client_left\n"
    "\n"
    "_lrd_original_clipboard = getattr(RemoteController, \"_on_remote_clipboard\", None)\n"
    "if _lrd_original_clipboard is not None:\n"
    "    def _lrd_on_remote_clipboard(self, *args, **kwargs):\n"
    "        self._linux_rdaccess_run_main(\n"
    "            lambda: _lrd_original_clipboard(self, *args, **kwargs))\n"
    "    RemoteController._on_remote_clipboard = _lrd_on_remote_clipboard\n"
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
    "            log.error(\"linux-rdaccess: braille input handling failed\")\n"
)


LOCAL_MACHINE_MARKER_V1 = "# linux-rdaccess low-latency XTest key injection"
LOCAL_MACHINE_MARKER_V2 = LOCAL_MACHINE_MARKER_V1 + " v2"
LOCAL_MACHINE_MARKER_V3 = LOCAL_MACHINE_MARKER_V1 + " v3"
LOCAL_MACHINE_MARKER_V4 = LOCAL_MACHINE_MARKER_V1 + " v4"
LOCAL_MACHINE_MARKER_V5 = LOCAL_MACHINE_MARKER_V1 + " v5"
LOCAL_MACHINE_MARKER_V6 = LOCAL_MACHINE_MARKER_V1 + " v6"
LOCAL_MACHINE_MARKER_V7 = LOCAL_MACHINE_MARKER_V1 + " v7"
LOCAL_MACHINE_MARKER = LOCAL_MACHINE_MARKER_V1 + " v8"
LEGACY_LOCAL_MACHINE_RELATIVE = Path("orca-scripts/local_machine.py")

# Upstream writes every key name (including typed passwords) to a debug log,
# opening the file twice per key event. This path is never safe to persist.
# LINUX_RDACCESS_DEBUG controls the separate timing-only logger.
_DBG_RE = re.compile(r"^def _dbg\(msg\):\n", re.MULTILINE)
_DBG_GUARD = (
    "    return  # linux-rdaccess: raw input logging disabled\n"
)


def _silence_dbg(text: str) -> str:
    # Backend exceptions can contain speech, clipboard or subprocess arguments.
    # Preserve their fixed diagnostic message without persisting the traceback.
    text = text.replace("log.exception(", "log.error(")
    match = _DBG_RE.search(text)
    if match is None or _DBG_GUARD in text:
        return text
    return text[:match.end()] + _DBG_GUARD + text[match.end():]


def _redact_legacy_logs(text: str) -> str:
    """Keep fixed upstream diagnostics without evaluating remote payloads."""
    text = text.replace('log.info("Joined channel: %s" % channel)',
                        'log.info("Joined remote channel")')
    try:
        tree = ast.parse(text, feature_version=(3, 10))
    except SyntaxError:
        raise ValueError("legacy diagnostics source is invalid Python") from None
    lines = text.encode('utf-8').splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    edits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name) and node.func.id == 'print' and any(
                    not isinstance(arg, ast.Constant) for arg in node.args)
                or isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'traceback' and node.func.attr == 'print_exc'):
            edits.append((starts[node.lineno - 1] + node.col_offset,
                          starts[node.end_lineno - 1] + node.end_col_offset,
                          b'print("Orca Remote: diagnostic details redacted")'))
            continue
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id in ('log', 'logger')
                and node.func.attr in ('debug', 'info', 'warning', 'error', 'exception')):
            continue
        fixed = (len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                 and isinstance(node.args[0].value, str) and not node.keywords)
        if fixed:
            continue
        level = 'error' if node.func.attr == 'exception' else node.func.attr
        replacement = f'{node.func.value.id}.{level}("linux-rdaccess: legacy diagnostic details redacted")'.encode()
        edits.append((starts[node.lineno - 1] + node.col_offset,
                      starts[node.end_lineno - 1] + node.end_col_offset, replacement))
    data = text.encode('utf-8')
    for start, end, replacement in sorted(edits, reverse=True):
        data = data[:start] + replacement + data[end:]
    return data.decode('utf-8')


_XTEST_HELPER = '''

''' + LOCAL_MACHINE_MARKER + '''
# Windows navigation VKs identify the keypad when extended=False. Preserve
# that identity before choosing XTest or any upstream injection fallback.
_LRD_KEYPAD_NAMES = {
    0x0C: "KP_Begin", 0x21: "KP_Prior", 0x22: "KP_Next",
    0x23: "KP_End", 0x24: "KP_Home", 0x25: "KP_Left",
    0x26: "KP_Up", 0x27: "KP_Right", 0x28: "KP_Down",
    0x2D: "KP_Insert", 0x2E: "KP_Delete",
}

# Upstream starts one `xdotool` process per key event (~38 ms each, measured),
# serially on the receive thread, so key bursts queue up and NVDA feels
# "chunky". Inject through XTest in-process instead (~0.004 ms); fall back to
# upstream's xdotool path for anything we cannot map.
class _LrdXTest:
    def __init__(self):
        self._lock = __import__("threading").RLock()
        self._x11 = None
        self._xt = None
        self._dpy = None
        self._down_codes = {}
        self._fallback_down = set()
        self._failed = False
        self._failed_environment = None

    def _open(self):
        import ctypes
        import ctypes.util
        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        xt = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        xt.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            raise OSError("cannot open X display")
        self._x11, self._xt, self._dpy = x11, xt, dpy

    def _fall_back(self, name, pressed):
        if pressed:
            self._fallback_down.add(name)
        else:
            self._fallback_down.discard(name)
            self._down_codes.pop(name, None)
        return False

    def key(self, name, pressed):
        """Return True for injection or an already-owned failed repeat."""
        if not name:
            return False
        with self._lock:
            import os
            environment = (os.environ.get("DISPLAY"), os.environ.get("XAUTHORITY"))
            if self._failed:
                # An initial open failure owns no live connection. Retry once
                # when session credentials change, without polling/blocking.
                if self._dpy is not None or environment == self._failed_environment:
                    return self._fall_back(name, pressed)
                self._failed = False
            if name in self._fallback_down:
                return self._fall_back(name, pressed)
            injected = False
            try:
                if self._dpy is None:
                    self._open()
                # Keep one resolved keycode only for the lifetime of a
                # held key. This preserves matching down/up events if the XKB
                # layout changes while the key is held, while the next fresh
                # press is resolved against the new layout.
                code = self._down_codes.get(name)
                if code is None:
                    try:
                        encoded_name = str(name).encode("ascii")
                    except UnicodeEncodeError:
                        # Let upstream xdotool/other backends handle names Xlib's
                        # ASCII XStringToKeysym path cannot represent. One such
                        # key must not disable XTest for the rest of the session.
                        return self._fall_back(name, pressed)
                    sym = self._x11.XStringToKeysym(encoded_name)
                    code = self._x11.XKeysymToKeycode(self._dpy, sym) if sym else 0
                if not code:
                    return self._fall_back(name, pressed)
                if not self._xt.XTestFakeKeyEvent(self._dpy, code, 1 if pressed else 0, 0):
                    if pressed and name in self._down_codes:
                        # The original press remains down. Drop this rejected
                        # repeat instead of giving its release to another backend.
                        return True
                    if not pressed:
                        # Upstream fallback will handle this release; forget
                        # the held mapping so the next fresh press can resolve
                        # against the current keyboard layout.
                        self._down_codes.pop(name, None)
                    return self._fall_back(name, pressed)
                injected = True
                if pressed:
                    self._down_codes[name] = code
                else:
                    self._down_codes.pop(name, None)
                self._x11.XFlush(self._dpy)
                return True
            except Exception:
                if injected:
                    # The event has already been queued. Replaying it through
                    # xdotool can double-toggle a lock or duplicate text input.
                    return True
                if pressed and name in self._down_codes:
                    return True
                if self._dpy is None:
                    self._failed = True
                    self._failed_environment = environment
                return self._fall_back(name, pressed)


_LRD_XTEST = _LrdXTest()


def _lrd_wrap_local_key_results(original):
    import inspect
    signature = inspect.signature(original)
    if "vk_code" not in signature.parameters:
        return original

    def send_key(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        pressed = bound.arguments.get("pressed")
        if pressed is None:
            return original(self, *args, **kwargs)
        key = self._resolve_key(bound.arguments.get("key_name"),
                                bound.arguments.get("vk_code"),
                                bound.arguments.get("extended"))
        # XTest's False only selects fallback: it does not confirm that the
        # complete upstream backend chain actually injected the event. Keep
        # its ownership changes transactional through that final result.
        helper = _LRD_XTEST
        with helper._lock:
            code = helper._down_codes.get(key)
            fallback = key in helper._fallback_down
            succeeded = False
            try:
                succeeded = original(self, *args, **kwargs) is True
                return succeeded
            finally:
                if not succeeded:
                    if code is None:
                        helper._down_codes.pop(key, None)
                    else:
                        helper._down_codes[key] = code
                    if fallback:
                        helper._fallback_down.add(key)
                    else:
                        helper._fallback_down.discard(key)

    return send_key


if hasattr(LocalMachine, "send_key") and hasattr(LocalMachine, "_resolve_key"):
    LocalMachine.send_key = _lrd_wrap_local_key_results(LocalMachine.send_key)


def _lrd_call_on_main(func, *args, **kwargs):
    """Run func on the GLib main loop (GTK is not thread-safe)."""
    try:
        from gi.repository import GLib
    except Exception:
        return func(*args, **kwargs)
    GLib.idle_add(lambda: (func(*args, **kwargs), False)[1])
'''

_XDOTOOL_DEF_RE = re.compile(r"^    def _send_key_xdotool\(self, key, pressed\):\n", re.MULTILINE)
_RESOLVE_KEY_DEF_RE = re.compile(
    r"^    def _resolve_key\(key_name, vk_code, extended\):\n", re.MULTILINE)
_RESOLVE_KEY_HOOK = (
    "        if not key_name and extended is not None and not extended:\n"
    "            keypad_name = _LRD_KEYPAD_NAMES.get(vk_code)\n"
    "            if keypad_name is not None:\n"
    "                return keypad_name\n"
)
_CLIPBOARD_DEF_RE = re.compile(
    r"^    def set_clipboard_text\(self, text=None, \*\*kwargs\):\n", re.MULTILINE)
_CLIPBOARD_HOOK = (
    "        if __import__(\"threading\").current_thread() is not __import__(\"threading\").main_thread():\n"
    "            # Gtk.Clipboard from the network thread can deadlock Orca.\n"
    "            _lrd_call_on_main(self.set_clipboard_text, text=text, **kwargs)\n"
    "            return\n"
)
_XDOTOOL_HOOK = (
    "        if _LRD_XTEST.key(key, pressed):  " + LOCAL_MACHINE_MARKER + "\n"
    "            return True\n"
)


def _valid_patch_python(text: str) -> bool:
    try:
        ast.parse(text, feature_version=(3, 10))
        compile(text, "<legacy patch>", "exec")
    except (SyntaxError, ValueError):
        return False
    return True


def _patch_local_key_results(text: str) -> str:
    """Expose backend results only for source control flow we can establish."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise ValueError("legacy local-machine source is invalid Python") from None
    methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == "LocalMachine"
               for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "send_key"
               and any(arg.arg == "vk_code" for arg in node.args.args)]
    if not methods:
        return text  # Key-name-only implementations do not have this API.
    if len(methods) != 1:
        raise ValueError("ambiguous legacy send_key implementation")
    method = methods[0]
    if method.decorator_list or method.body[0].lineno == method.lineno:
        raise ValueError("unsupported decorated or inline legacy send_key")
    nodes = list(ast.walk(method))
    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    backend_names = {"_send_key_xdotool", "_send_key_portal", "_send_key_ydotool"}

    def backend_call(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
                and node.func.attr in backend_names)

    def backend_test(node):
        return (backend_call(node) or (isinstance(node, ast.BoolOp)
                and isinstance(node.op, ast.Or) and all(backend_call(value) for value in node.values)))

    def always_returns(body):
        for node in body:
            if isinstance(node, ast.Return):
                return True
            if isinstance(node, ast.If) and always_returns(node.body) and always_returns(node.orelse):
                return True
        return False

    for node in nodes:
        if isinstance(node, ast.stmt) and node is not method and not isinstance(
                node, (ast.If, ast.Return, ast.Assign, ast.AnnAssign, ast.Expr, ast.Pass)):
            raise ValueError("unsupported legacy send_key control flow")
        if backend_call(node):
            parent = parents[node]
            if isinstance(parent, ast.BoolOp):
                parent = parents[parent]
            if not isinstance(parent, ast.If) or not backend_test(parent.test):
                raise ValueError("unverified legacy backend result use")
            if not always_returns(parent.body):
                raise ValueError("legacy backend success can fall through without a result")
        # An unknown helper could itself inject input. Do not label its result
        # as failure merely because its name differs from the known backends.
        if isinstance(node, ast.Call) and not backend_call(node):
            func = node.func
            allowed = (isinstance(func, ast.Name) and func.id == "_dbg") or (
                isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and ((func.value.id == "self" and func.attr in (
                    "_resolve_key", "_is_wayland_session", "_portal_denied", "_warn_no_key_backend"))
                     or (func.value.id == "log" and func.attr in ("debug", "info", "warning", "error"))))
            if not allowed:
                raise ValueError("unverified helper in legacy send_key")

    lines = text.encode("utf-8").splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    marker = "# linux-rdaccess: report injection results"
    method_text = ast.get_source_segment(text, method) or ""
    current = marker in method_text
    edits = []
    for node in nodes:
        if not isinstance(node, ast.Return):
            continue
        succeeded = False
        child = node
        while child is not method:
            parent = parents[child]
            if isinstance(parent, ast.If) and child in parent.body and backend_test(parent.test):
                succeeded = True
            child = parent
        value = node.value
        if value is not None and (not isinstance(value, ast.Constant)
                                  or value.value is not None and type(value.value) is not bool):
            raise ValueError("unsupported legacy send_key return value")
        if value is not None and type(value.value) is bool and value.value != succeeded:
            raise ValueError("legacy send_key return disagrees with backend ownership")
        if current:
            if value is None or type(value.value) is not bool:
                raise ValueError("incomplete legacy backend result patch")
            continue
        edits.append((starts[node.lineno - 1] + node.col_offset,
                      starts[node.end_lineno - 1] + node.end_col_offset,
                      ("return " + str(succeeded)).encode("utf-8")))
    if current:
        return text
    data = text.encode("utf-8")
    for begin, end, value in sorted(edits, reverse=True):
        data = data[:begin] + value + data[end:]
    result = data.decode("utf-8").splitlines(keepends=True)
    # Value edits preserve line counts. Keep the actual indentation and avoid
    # deleting conditions/comments on lines containing an inline return.
    first = method.body[0].lineno - 1
    indent = result[first][:len(result[first]) - len(result[first].lstrip())]
    result.insert(method.end_lineno, indent + "return False\n")
    result.insert(first, indent + marker + "\n")
    return "".join(result)


def _ast_equal(left, right) -> bool:
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def _binding_count(body, name):
    tree = ast.Module(body=body, type_ignores=[])
    count = len(_module_stores(tree, name))
    def definitions(node):
        nonlocal count
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += node.name == name
            return
        for child in ast.iter_child_nodes(node):
            definitions(child)
    definitions(tree)
    return count


def _unique_class(tree, name):
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    return matches[0] if len(matches) == 1 and _binding_count(tree.body, name) == 1 else None


def _unique_method(cls, name):
    matches = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name]
    return matches[0] if len(matches) == 1 and _binding_count(cls.body, name) == 1 else None


def _patch_tail_matches(tree, source) -> bool:
    expected = ast.parse(textwrap.dedent(source)).body
    actual = tree.body[-len(expected):]
    return len(actual) == len(expected) and all(_ast_equal(a, b) for a, b in zip(actual, expected))


def _debug_path_disabled(tree) -> bool:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_dbg"]
    if not functions:
        return not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "_dbg" for node in ast.walk(tree))
    return (len(functions) == 1 and _binding_count(tree.body, "_dbg") == 1
            and isinstance(functions[0].body[0], ast.Return)
            and functions[0].body[0].value is None)


def legacy_local_machine_patch_current(text: str) -> bool:
    if (not _valid_patch_python(text) or "log.exception(" in text
            or not all(part in text for part in (_XTEST_HELPER, _XDOTOOL_HOOK))):
        return False
    tree = ast.parse(text)
    cls = _unique_class(tree, "LocalMachine")
    if cls is None or not _debug_path_disabled(tree) or not _patch_tail_matches(tree, _XTEST_HELPER):
        return False
    for name, hook, required in (
        ("_send_key_xdotool", _XDOTOOL_HOOK, True),
        ("_resolve_key", _RESOLVE_KEY_HOOK, False),
        ("set_clipboard_text", _CLIPBOARD_HOOK, False),
    ):
        method = _unique_method(cls, name)
        if method is None:
            if required or any(isinstance(node, ast.FunctionDef) and node.name == name for node in cls.body):
                return False
            continue
        expected = ast.parse(textwrap.dedent(hook)).body
        if len(method.body) < len(expected) or not all(
                _ast_equal(a, b) for a, b in zip(method.body, expected)):
            return False
    try:
        if _patch_local_key_results(text) != text:
            return False
    except ValueError:
        return False
    return True


def legacy_controller_patch_current(text: str) -> bool:
    if (not _valid_patch_python(text) or "log.exception(" in text
            or not all(part in text for part in (
                _LEGACY_HELPERS, _LEGACY_KEY_CALL, _LEGACY_BRAILLE_HANDLER,
                _LEGACY_RESET_HOOKS, _LEGACY_SLOW_EVENT_HOOK, _LEGACY_ORCA_D_HOOK.strip("\n")))):
        return False
    tree = ast.parse(text)
    cls = _unique_class(tree, "RemoteController")
    tail = _LEGACY_RESET_HOOKS + "\n" + _LEGACY_SLOW_EVENT_HOOK + "\n" + _LEGACY_ORCA_D_HOOK
    if cls is None or not _debug_path_disabled(tree) or not _patch_tail_matches(tree, tail):
        return False
    expected_helpers = ast.parse("class _Expected:\n" + _LEGACY_HELPERS).body[0]
    for expected in expected_helpers.body:
        if isinstance(expected, ast.FunctionDef):
            actual = _unique_method(cls, expected.name)
            if actual is None or not _ast_equal(actual, expected):
                return False
        else:
            if sum(_ast_equal(actual, expected) for actual in cls.body) != 1:
                return False
            if isinstance(expected, ast.Assign) and any(
                    isinstance(target, ast.Name) and _binding_count(cls.body, target.id) != 1
                    for target in expected.targets):
                return False
    braille = _unique_method(cls, "_on_remote_braille_input")
    expected_braille = ast.parse("class _Expected:\n" + _LEGACY_BRAILLE_HANDLER).body[0].body[0]
    if braille is None or not _ast_equal(braille, expected_braille):
        return False
    key = _unique_method(cls, "_on_remote_key")
    if key is None:
        return False
    expected_filter = ast.parse(textwrap.dedent(_LEGACY_KEY_CALL)).body[0]
    expected_forward = ast.parse("self._linux_rdaccess_forward_key(key_name=key_name, pressed=pressed, "
                                 "modifiers=modifiers, vk_code=vk_code, scan_code=scan_code, extended=extended)").body[0]
    if len(key.body) < 2 or not _ast_equal(key.body[-2], expected_filter) or not _ast_equal(key.body[-1], expected_forward):
        return False
    # Only the verified None guard, no-op _dbg calls and a docstring can precede
    # the filter. In particular an early unconditional return cannot disable it.
    for node in key.body[:-2]:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "_dbg":
            continue
        if (isinstance(node, ast.If) and not node.orelse
                and _ast_equal(node.test, ast.parse("pressed is None", mode="eval").body)
                and isinstance(node.body[-1], ast.Return) and node.body[-1].value is None
                and all(isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                        and isinstance(child.value.func, ast.Name) and child.value.func.id == "_dbg"
                        for child in node.body[:-1])):
            continue
        return False
    return True


def patch_legacy_orca_local_machine(path: Path) -> bool:
    """Make key injection low-latency and stop per-keypress file logging.

    Idempotent; one-time backup; verified to compile; atomic write.
    """
    text = path.read_text(encoding="utf-8")
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if backup.exists():
        backup.chmod(0o600)
    if LOCAL_MACHINE_MARKER in text:
        if legacy_local_machine_patch_current(text):
            return False
        raise ValueError("current local-machine marker has an incomplete patch")
    if LOCAL_MACHINE_MARKER_V1 in text:
        if not backup.exists():
            raise ValueError(f"older patch found but backup is missing: {backup}")
        text = backup.read_text(encoding="utf-8")
    text = _redact_legacy_logs(text)
    text = _patch_local_key_results(text)
    match = _XDOTOOL_DEF_RE.search(text)
    if match is None:
        raise ValueError(f"legacy _send_key_xdotool was not found in {path}")
    text = text[:match.end()] + _XDOTOOL_HOOK + text[match.end():]
    resolve = _RESOLVE_KEY_DEF_RE.search(text)
    if resolve is not None:
        text = text[:resolve.end()] + _RESOLVE_KEY_HOOK + text[resolve.end():]
    clip = _CLIPBOARD_DEF_RE.search(text)
    if clip is not None:
        text = text[:clip.end()] + _CLIPBOARD_HOOK + text[clip.end():]
    text = _silence_dbg(text)
    text = text.rstrip("\n") + "\n" + _XTEST_HELPER
    try:
        compile(text, str(path), "exec")
    except SyntaxError:
        raise ValueError(f"patched {path} would not compile") from None
    if not backup.exists():
        _write_private_text(backup, path.read_text(encoding="utf-8"))
    _write_private_text(path, text)
    return True


def patch_legacy_orca_remote_controller(path: Path) -> bool:
    """Patch legacy Orca Remote input handling for NVDA compatibility.

    Returns True when the file changed. The patch is idempotent, replaces an
    earlier patch from the one-time .linux-rdaccess-backup, verifies the
    result compiles before writing, and writes atomically.
    """
    text = path.read_text(encoding="utf-8")
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if backup.exists():
        backup.chmod(0o600)
    if LEGACY_COMPAT_MARKER in text:
        if legacy_controller_patch_current(text):
            return False
        raise ValueError("current controller marker has an incomplete patch")
    old_marker = next(
        (
            marker
            for marker in (
                LEGACY_COMPAT_MARKER_V30,
                LEGACY_COMPAT_MARKER_V29,
                LEGACY_COMPAT_MARKER_V28,
                LEGACY_COMPAT_MARKER_V27,
                LEGACY_COMPAT_MARKER_V26,
                LEGACY_COMPAT_MARKER_V25,
                LEGACY_COMPAT_MARKER_V24,
                LEGACY_COMPAT_MARKER_V23,
                LEGACY_COMPAT_MARKER_V22,
                LEGACY_COMPAT_MARKER_V21,
                LEGACY_COMPAT_MARKER_V20,
                LEGACY_COMPAT_MARKER_V19,
                LEGACY_COMPAT_MARKER_V18,
                LEGACY_COMPAT_MARKER_V17,
                LEGACY_COMPAT_MARKER_V16,
                LEGACY_COMPAT_MARKER_V15,
                LEGACY_COMPAT_MARKER_V14,
                LEGACY_COMPAT_MARKER_V13,
                LEGACY_COMPAT_MARKER_V12,
                LEGACY_COMPAT_MARKER_V11,
                LEGACY_COMPAT_MARKER_V10,
                LEGACY_COMPAT_MARKER_V9,
                LEGACY_COMPAT_MARKER_V8,
                LEGACY_COMPAT_MARKER_V7,
                LEGACY_COMPAT_MARKER_V4,
                LEGACY_COMPAT_MARKER_V3,
                LEGACY_COMPAT_MARKER_V2,
                LEGACY_COMPAT_MARKER_V1,
            )
            if marker in text
        ),
        None,
    )
    if old_marker is not None:
        if not backup.exists():
            raise ValueError(f"older compatibility patch found but backup is missing: {backup}")
        text = backup.read_text(encoding="utf-8")

    text = _redact_legacy_logs(text)
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
    text = (text[:anchor_at] + _LEGACY_KEY_CALL
            + text[anchor_at:].replace(key_anchor,
                "        self._linux_rdaccess_forward_key(\n", 1))
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
    text = text.rstrip("\n") + "\n\n\n" + _LEGACY_SLOW_EVENT_HOOK
    text = text.rstrip("\n") + "\n\n\n" + _LEGACY_ORCA_D_HOOK.strip("\n") + "\n"
    text = _silence_dbg(text)
    # NVDA Remote's channel is the connection key, not a public identifier.
    text = text.replace(
        'log.info("Joined channel: %s" % channel)',
        'log.info("Joined remote channel")',
    )

    try:
        compile(text, str(path), "exec")
    except SyntaxError:
        raise ValueError(f"patched {path} would not compile") from None

    if not backup.exists():
        _write_private_text(backup, path.read_text(encoding="utf-8"))
    _write_private_text(path, text)
    return True


def disable_legacy_orca_connection(path: Path) -> None:
    """Disable legacy Orca Remote auto-connect without deleting saved linux-rdaccess settings."""
    text = path.read_text(encoding="utf-8")
    replacements = {
        "YOUR_NVDAREMOTE_SERVER_ADDRESS": json.dumps("host"),
        "YOUR_NVDAREMOTE_KEY": json.dumps("key"),
    }
    text = _replace_configuration_values(text, replacements)
    _write_private_text(path, text)

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
