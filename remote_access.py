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

_LOCAL_SPEECH_PREF_HOOK_V3 = """# linux-rdaccess local Orca speech preference
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

_LOCAL_SPEECH_PREF_HOOK = _LOCAL_SPEECH_PREF_HOOK_V3.replace(
    "        if _linux_rdaccess_local_speech_muted():\n            return None\n",
    "        if _linux_rdaccess_local_speech_muted():\n"
    "            if callable(kwargs.get(\"callback\")):\n"
    "                helper = globals().get(\"_linux_rdaccess_silent_callback_speech\")\n"
    "                if callable(helper):\n"
    "                    return helper(original, *args, **kwargs)\n"
    "            return None\n",
)

CUSTOMIZATION_EVENT_API_MARKER = "# linux-rdaccess Orca keyboard-event API compatibility v1"
_CUSTOMIZATION_EVENT_API_HOOK = CUSTOMIZATION_EVENT_API_MARKER + '''
# Orca 42 exposes isPressedKey; newer Orca Remote uses is_pressed_key.
# Keep the legacy process wrapper's native-handler and injection-marker paths.
def _linux_rdaccess_event_is_pressed(event):
    method = getattr(event, "isPressedKey", None)
    if not callable(method):
        method = getattr(event, "is_pressed_key", None)
    if not callable(method):
        raise AttributeError("unsupported Orca keyboard-event API")
    return bool(method())
'''
_CUSTOMIZATION_EVENT_FUNCTIONS = (
    "_patched_process_key", "_should_run_shortcut_directly", "_run_direct_shortcut",
)

CUSTOMIZATION_SPEECH_SEQUENCE_MARKER = "# linux-rdaccess NVDA speech sequence compatibility v1"
_CUSTOMIZATION_SPEECH_SEQUENCE_HOOK = CUSTOMIZATION_SPEECH_SEQUENCE_MARKER + '''
def _linux_rdaccess_speech_sequence(text):
    # NVDA's decoder iterates sequence; a scalar string becomes characters.
    # Preserve a sequence already supplied by a compatible upstream caller.
    return [text] if isinstance(text, str) else text
'''
_CUSTOMIZATION_SPEECH_FORWARD_SOURCE = '''
def my_speak(self, text, acss, **kw):
    global _want_cancel
    if text and transport.connected and transport.connection_type == "slave":
        if _want_cancel:
            transport.send(type="cancel")
            _want_cancel = False
        transport.send(type="speak", sequence=text)
        return None
    return old_speak(self, text, acss, **kw)
'''
_CUSTOMIZATION_SPEECH_CALLBACK_SOURCE = _CUSTOMIZATION_SPEECH_FORWARD_SOURCE.replace(
    "        return None\n", "        if not callable(kw.get(\"callback\")):\n            return None\n")

CUSTOMIZATION_SAY_ALL_CALLBACK_MARKER = "# linux-rdaccess native Say All callbacks v1"
_CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK = CUSTOMIZATION_SAY_ALL_CALLBACK_MARKER + '''
def _linux_rdaccess_silent_callback_speech(original, *args, **kwargs):
    # Obtain genuine native synthesis events while Windows speaks the text.
    # Timing follows the local synthesizer; it is not a Windows completion ACK.
    import threading as _threading
    if (not callable(kwargs.get("callback")) or not args
            or _threading.current_thread() is not _threading.main_thread()
            or not isinstance(args[0], SpeechServer)
            or getattr(original, "__module__", None) != "orca.speechdispatcherfactory"
            or getattr(original, "__name__", None) != "_speak"):
        return None
    server = args[0]
    send = getattr(server, "_send_command", None)
    properties = getattr(server, "_current_voice_properties", None)
    if not callable(send) or not isinstance(properties, dict) or not hasattr(server, "__dict__"):
        return None
    owned_send = "_send_command" in server.__dict__
    previous_send = server.__dict__.get("_send_command")
    clients = {}
    intercepted = False

    def client():
        current = getattr(server, "_client", None)
        if not all(callable(getattr(current, name, None))
                   for name in ("get_volume", "set_volume", "speak")):
            raise RuntimeError("native callback backend unavailable")
        if id(current) not in clients:
            volume = current.get_volume()
            if isinstance(volume, bool) or not isinstance(volume, (str, int)):
                raise ValueError("native volume unavailable")
            volume = int(volume)
            if not -100 <= volume <= 100:
                raise ValueError("native volume out of range")
            clients[id(current)] = (current, volume)
            # Orca gain=0 maps to -35, so force the native backend's mute value.
            current.set_volume(-100)
        return current

    def muted_send(command, *command_args, **command_kwargs):
        current = client()
        for known, _volume in clients.values():
            if command == known.set_volume:
                return known.set_volume(-100)
            if command == known.speak:
                # Also cover cached ACSS gain, which may skip a volume command.
                known.set_volume(-100)
                break
        return send(command, *command_args, **command_kwargs)

    try:
        client()
        server._send_command = muted_send
        intercepted = True
        return original(*args, **kwargs)
    except Exception:
        # Never fall back to audible local speech or invent synthesis events.
        return None
    finally:
        if intercepted:
            if owned_send:
                server._send_command = previous_send
            else:
                server.__dict__.pop("_send_command", None)
        for known, volume in clients.values():
            try:
                known.set_volume(volume)
            except Exception:
                pass
        # Restoration may differ from the native gain cache after an ACSS
        # change or a reconnect. Force the next real utterance to set its gain.
        current_properties = getattr(server, "_current_voice_properties", None)
        if isinstance(current_properties, dict) and clients:
            current_properties.pop("gain", None)
'''


def _customization_speech_functions(tree):
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
            and node.name == "my_speak"]


def legacy_customization_speech_sequence_patch_current(text: str) -> bool:
    """Verify the wire-shape helper and the actual outbound speech wrapper."""
    if text.count(CUSTOMIZATION_SPEECH_SEQUENCE_MARKER) != 1:
        return False
    try:
        tree = ast.parse(text, feature_version=(3, 10))
    except SyntaxError:
        return False
    expected_helper = ast.parse(_CUSTOMIZATION_SPEECH_SEQUENCE_HOOK).body[0]
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == expected_helper.name]
    expected = [ast.parse(source.replace(
        "sequence=text", "sequence=_linux_rdaccess_speech_sequence(text)")).body[0]
        for source in (_CUSTOMIZATION_SPEECH_FORWARD_SOURCE, _CUSTOMIZATION_SPEECH_CALLBACK_SOURCE)]
    wrappers = _customization_speech_functions(tree)
    return (len(helpers) == 1 and _binding_count(tree.body, expected_helper.name) == 1
            and _ast_equal(helpers[0], expected_helper)
            and len(wrappers) == 1 and wrappers[0] in tree.body
            and _binding_count(tree.body, "my_speak") == 1
            and any(_ast_equal(wrappers[0], shape) for shape in expected))


def _patch_legacy_customization_speech_sequence(text: str) -> str:
    if CUSTOMIZATION_SPEECH_SEQUENCE_MARKER in text:
        if not legacy_customization_speech_sequence_patch_current(text):
            raise ValueError("incomplete NVDA speech sequence patch")
        return text
    tree = ast.parse(text, feature_version=(3, 10))
    wrappers = _customization_speech_functions(tree)
    if not wrappers:
        return text
    expected = ast.parse(_CUSTOMIZATION_SPEECH_FORWARD_SOURCE).body[0]
    already_wrapped = ast.parse(_CUSTOMIZATION_SPEECH_FORWARD_SOURCE.replace(
        "sequence=text", "sequence=[text]")).body[0]
    if (len(wrappers) != 1 or wrappers[0] not in tree.body
            or _binding_count(tree.body, "my_speak") != 1
            or not any(_ast_equal(wrappers[0], shape) for shape in (expected, already_wrapped))):
        raise ValueError("unsupported legacy outbound speech wrapper")
    if _binding_count(tree.body, "_linux_rdaccess_speech_sequence"):
        raise ValueError("conflicting NVDA speech sequence helper")
    keyword = next(keyword for node in ast.walk(wrappers[0]) if isinstance(node, ast.Call)
                   for keyword in node.keywords if keyword.arg == "sequence")
    data = text.encode("utf-8")
    starts = [0]
    for line in data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    value = keyword.value
    start = starts[value.lineno - 1] + value.col_offset
    end = starts[value.end_lineno - 1] + value.end_col_offset
    result = (data[:start] + b"_linux_rdaccess_speech_sequence(text)" + data[end:]).decode("utf-8")
    result = result.rstrip("\n") + "\n\n" + _CUSTOMIZATION_SPEECH_SEQUENCE_HOOK
    if not legacy_customization_speech_sequence_patch_current(result):
        raise ValueError("updated NVDA speech sequence patch is incomplete")
    return result


def legacy_customization_say_all_callback_patch_current(text: str) -> bool:
    if text.count(CUSTOMIZATION_SAY_ALL_CALLBACK_MARKER) != 1 or _LOCAL_SPEECH_PREF_HOOK not in text:
        return False
    try:
        tree = ast.parse(text, feature_version=(3, 10))
    except SyntaxError:
        return False
    expected_helper = ast.parse(_CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK).body[0]
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == expected_helper.name]
    wrappers = _customization_speech_functions(tree)
    expected_wrapper = ast.parse(_CUSTOMIZATION_SPEECH_CALLBACK_SOURCE.replace(
        "sequence=text", "sequence=_linux_rdaccess_speech_sequence(text)")).body[0]
    return (len(helpers) == 1 and _binding_count(tree.body, expected_helper.name) == 1
            and _ast_equal(helpers[0], expected_helper)
            and _binding_count(tree.body, "_linux_rdaccess_wrap_local_speech") == 1
            and _binding_count(tree.body, "my_speak") == 1
            and len(wrappers) == 1 and wrappers[0] in tree.body
            and _ast_equal(wrappers[0], expected_wrapper)
            and legacy_customization_speech_sequence_patch_current(text))


def _patch_legacy_customization_say_all_callbacks(text: str) -> str:
    if CUSTOMIZATION_SAY_ALL_CALLBACK_MARKER in text:
        if not legacy_customization_say_all_callback_patch_current(text):
            raise ValueError("incomplete native Say All callback patch")
        return text
    tree = ast.parse(text, feature_version=(3, 10))
    wrappers = _customization_speech_functions(tree)
    if not wrappers:
        return text
    expected = ast.parse(_CUSTOMIZATION_SPEECH_FORWARD_SOURCE.replace(
        "sequence=text", "sequence=_linux_rdaccess_speech_sequence(text)")).body[0]
    if len(wrappers) != 1 or not _ast_equal(wrappers[0], expected):
        raise ValueError("unsupported legacy Say All speech wrapper")
    helper_name = "_linux_rdaccess_silent_callback_speech"
    if _binding_count(tree.body, helper_name):
        raise ValueError("conflicting native Say All callback helper")
    returned = next(node for node in ast.walk(wrappers[0]) if isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Constant) and node.value.value is None)
    data = text.encode("utf-8")
    starts = [0]
    for line in data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    start = starts[returned.lineno - 1] + returned.col_offset
    end = starts[returned.end_lineno - 1] + returned.end_col_offset
    replacement = b'if not callable(kw.get("callback")):\n            return None'
    result = (data[:start] + replacement + data[end:]).decode("utf-8")
    result = result.rstrip("\n") + "\n\n" + _CUSTOMIZATION_SAY_ALL_CALLBACK_HOOK
    if not legacy_customization_say_all_callback_patch_current(result):
        raise ValueError("updated native Say All callback patch is incomplete")
    return result

CUSTOMIZATION_RECONNECT_MARKER = "# linux-rdaccess automatic relay reconnect v1"
_CUSTOMIZATION_RECONNECT_HOOK = CUSTOMIZATION_RECONNECT_MARKER + '''
if _has_config:
    # Use the transport's existing retry worker. close() stops this worker,
    # and manual reconnect() creates its replacement; do not add a second loop.
    t = transport.reconnector_thread
    if not t.is_alive():
        t.start()
'''
_CUSTOMIZATION_ONESHOT_START = '''
if _has_config:
    def try_run_thread():
        try:
            transport.run()
        except Exception:
            print("Error in thread")
            print("Orca Remote: diagnostic details redacted")
    t = threading.Thread(target=try_run_thread)
    t.daemon = True
    t.start()
'''


def _customization_startup_blocks(tree):
    return [node for node in tree.body if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name) and node.test.id == "_has_config"]


def legacy_customization_reconnect_patch_current(text: str) -> bool:
    """Verify that automatic startup uses the native cancellable retry worker."""
    if text.count(CUSTOMIZATION_RECONNECT_MARKER) != 1:
        return False
    try:
        blocks = _customization_startup_blocks(ast.parse(text, feature_version=(3, 10)))
    except SyntaxError:
        return False
    expected = ast.parse(_CUSTOMIZATION_RECONNECT_HOOK).body[0]
    return len(blocks) == 1 and _ast_equal(blocks[0], expected)


def _patch_legacy_customization_reconnect(text: str) -> str:
    if CUSTOMIZATION_RECONNECT_MARKER in text:
        if not legacy_customization_reconnect_patch_current(text):
            raise ValueError("incomplete automatic relay reconnect patch")
        return text
    tree = ast.parse(text, feature_version=(3, 10))
    blocks = _customization_startup_blocks(tree)
    if not blocks:
        # Minimal configuration templates have no automatic startup to repair.
        return text
    expected = ast.parse(_CUSTOMIZATION_ONESHOT_START).body[0]
    if len(blocks) != 1 or not _ast_equal(blocks[0], expected):
        raise ValueError("unsupported legacy automatic relay startup")
    block = blocks[0]
    data = text.encode("utf-8")
    starts = [0]
    for line in data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    start = starts[block.lineno - 1] + block.col_offset
    end = starts[block.end_lineno - 1] + block.end_col_offset
    result = (data[:start] + _CUSTOMIZATION_RECONNECT_HOOK.rstrip("\n").encode("utf-8")
              + data[end:]).decode("utf-8")
    if not legacy_customization_reconnect_patch_current(result):
        raise ValueError("updated automatic relay reconnect patch is incomplete")
    return result



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


def _customization_event_functions(tree):
    functions = []
    for name in _CUSTOMIZATION_EVENT_FUNCTIONS:
        matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and node.name == name]
        if len(matches) > 1:
            raise ValueError("ambiguous legacy keyboard-event hook")
        functions.extend(matches)
    return functions


def _customization_event_helper_shadowed(function):
    name = "_linux_rdaccess_event_is_pressed"
    for node in ast.walk(function):
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name
                or isinstance(node, ast.arg) and node.arg == name
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
                or isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name
                or isinstance(node, ast.ExceptHandler) and node.name == name
                or isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name == name
                or isinstance(node, ast.MatchMapping) and node.rest == name):
            return True
    return False


def legacy_customization_event_api_patch_current(text: str) -> bool:
    """Verify the actual helper and all owned legacy keyboard-event calls."""
    if text.count(CUSTOMIZATION_EVENT_API_MARKER) != 1 or _CUSTOMIZATION_EVENT_API_HOOK not in text:
        return False
    try:
        tree = ast.parse(text, feature_version=(3, 10))
        functions = _customization_event_functions(tree)
    except (SyntaxError, ValueError):
        return False
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "_linux_rdaccess_event_is_pressed"]
    expected = ast.parse(_CUSTOMIZATION_EVENT_API_HOOK).body[0]
    if (len(helpers) != 1 or _binding_count(tree.body, expected.name) != 1
            or not _ast_equal(helpers[0], expected) or not _debug_path_disabled(tree)):
        return False
    if any(_customization_event_helper_shadowed(function) for function in functions):
        return False
    return not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "event_self"
        and node.func.attr in ("is_pressed_key", "isPressedKey")
        for function in functions for node in ast.walk(function)
    )


def _patch_legacy_customization_event_api(text: str) -> str:
    # Fixing the wrapper makes its raw-key debug calls reachable on Orca 42.
    # Keep that upstream file logger disabled before enabling those paths.
    text = _silence_dbg(text)
    if CUSTOMIZATION_EVENT_API_MARKER in text:
        if not legacy_customization_event_api_patch_current(text):
            raise ValueError("incomplete legacy keyboard-event API patch")
        return text
    tree = ast.parse(text, feature_version=(3, 10))
    if _binding_count(tree.body, "_linux_rdaccess_event_is_pressed"):
        raise ValueError("conflicting legacy keyboard-event API helper")
    edits = []
    for function in _customization_event_functions(tree):
        if _customization_event_helper_shadowed(function):
            raise ValueError("shadowed legacy keyboard-event API helper")
        for node in ast.walk(function):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "event_self"
                    and node.func.attr in ("is_pressed_key", "isPressedKey")):
                continue
            if node.args or node.keywords:
                raise ValueError("unsupported legacy keyboard-event call")
            edits.append(node)
    # AST positions are UTF-8 byte offsets; avoid changing comments or strings.
    data = text.encode("utf-8")
    starts = [0]
    for line in data.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    for node in sorted(edits, key=lambda item: (item.lineno, item.col_offset), reverse=True):
        start = starts[node.lineno - 1] + node.col_offset
        end = starts[node.end_lineno - 1] + node.end_col_offset
        data = data[:start] + b"_linux_rdaccess_event_is_pressed(event_self)" + data[end:]
    result = data.decode("utf-8").rstrip("\n") + "\n\n" + _CUSTOMIZATION_EVENT_API_HOOK
    if not legacy_customization_event_api_patch_current(result):
        raise ValueError("updated legacy keyboard-event API patch is incomplete")
    return result


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


_TRANSPORT_RECEIVER_V6 = '''
def handle_server_data(self):
    buffSize = 16384
    current_socket = self.server_sock
    received = current_socket.recv(buffSize)
    if self.server_sock is not current_socket:
        return
    if not received:
        self.buffer = b''
        self._disconnect()
        return
    data = self.buffer + received
    self.buffer = b''
    if b'\\n' not in data:
        self.buffer += data
        return
    while b'\\n' in data:
        line, sep, data = data.partition(b'\\n')
        self.parse(line)
        if self.server_sock is not current_socket:
            return
    self.buffer += data
'''

_TRANSPORT_RECEIVER_V7 = _TRANSPORT_RECEIVER_V6.replace(
    """    if b'\\n' not in data:
        self.buffer += data
        return
""",
    """    if b'\\n' not in data:
        if len(data) > 1 << 20:
            self.buffer = b''
            self._disconnect()
            return
        self.buffer += data
        return
""",
).replace(
    """        line, sep, data = data.partition(b'\\n')
        self.parse(line)
""",
    """        line, sep, data = data.partition(b'\\n')
        if len(line) > 1 << 20:
            self.buffer = b''
            self._disconnect()
            return
        self.parse(line)
""",
)


def legacy_transport_cleanup_patch_current(text: str) -> bool:
    """Whether the legacy transport safely cleans resources before reconnect."""
    if TRANSPORT_CLEANUP_MARKER not in text:
        return False
    try:
        tree = ast.parse(text, feature_version=(3, 10))
    except SyntaxError:
        return False
    tcp = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"),
        None,
    )
    if tcp is None:
        return False
    methods = {
        node.name: node for node in tcp.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    disconnect = methods.get("_disconnect")
    run = methods.get("run")
    send_queue = methods.get("send_queue")
    if disconnect is None or run is None or send_queue is None:
        return False
    disconnect_source = ast.get_source_segment(text, disconnect) or ""
    run_source = ast.get_source_segment(text, run) or ""
    send_source = ast.get_source_segment(text, send_queue) or ""
    receiver = methods.get("handle_server_data")
    receiver_source = ast.get_source_segment(text, receiver) if receiver is not None else ""
    eof_safe = (".recv(" not in receiver_source or _ast_equal(
        receiver, ast.parse(_TRANSPORT_RECEIVER_V7).body[0]))
    shutdown = disconnect_source.find("self.server_sock.shutdown(socket.SHUT_RDWR)")
    join = disconnect_source.find("self.queue_thread.join()")
    receive = run_source.split("self.handle_server_data()", 1)
    receive_safe = len(receive) == 2 and "except Exception:" in receive[1].split("self.connected = False", 1)[0]
    select_safe = (
        "except (socket.error, ValueError):" in run_source
        or "except (OSError, ValueError):" in run_source
    )
    run_owned = (
        "current_socket = self.server_sock" in run_source
        and "current_socket.connect(self.address)" in run_source
        and "while self.server_sock is current_socket:" in run_source
        and run_source.count("if self.server_sock is not current_socket:") >= 3
        and run_source.count("if self.server_sock is not None and self.server_sock is not current_socket:") >= 2
    )
    return (
        "if self.server_sock is None and self.queue_thread is None:" in disconnect_source
        and "self.connected = False" in disconnect_source
        and "self.buffer = b''" in disconnect_source
        and shutdown >= 0
        and join > shutdown
        and "except Exception:" in run_source
        and "self._disconnect()" in run_source.split("except Exception:", 1)[1].split("raise", 1)[0]
        and receive_safe
        and select_safe
        and "self.server_sock.shutdown(socket.SHUT_RDWR)" in send_source
        and eof_safe
        and run_owned
    )


def _patch_legacy_transport_cleanup(text: str) -> str:
    """Fix stale resources and receive failures in the verified Orca Remote transport."""
    if TRANSPORT_CLEANUP_MARKER in text:
        if legacy_transport_cleanup_patch_current(text):
            return text
        raise ValueError("current transport cleanup marker has an incomplete patch")

    upgrading_v1 = TRANSPORT_CLEANUP_MARKER_V1 in text
    upgrading_v2 = TRANSPORT_CLEANUP_MARKER_V2 in text
    upgrading_v3 = TRANSPORT_CLEANUP_MARKER_V3 in text
    upgrading_v4 = TRANSPORT_CLEANUP_MARKER_V4 in text
    upgrading_v5 = TRANSPORT_CLEANUP_MARKER_V5 in text
    upgrading_v6 = TRANSPORT_CLEANUP_MARKER_V6 in text
    if upgrading_v1:
        text = text.replace(TRANSPORT_CLEANUP_MARKER_V1, "", 1).rstrip("\n") + "\n"
    elif upgrading_v2:
        text = text.replace(TRANSPORT_CLEANUP_MARKER_V2, "", 1).rstrip("\n") + "\n"
    elif upgrading_v3:
        text = text.replace(TRANSPORT_CLEANUP_MARKER_V3, "", 1).rstrip("\n") + "\n"
    elif upgrading_v4:
        text = text.replace(TRANSPORT_CLEANUP_MARKER_V4, "", 1).rstrip("\n") + "\n"
    elif upgrading_v5:
        text = text.replace(TRANSPORT_CLEANUP_MARKER_V5, "", 1).rstrip("\n") + "\n"
    elif upgrading_v6:
        text = text.replace(TRANSPORT_CLEANUP_MARKER_V6, "", 1).rstrip("\n") + "\n"

    try:
        tree = ast.parse(text, feature_version=(3, 10))
    except SyntaxError:
        raise ValueError("legacy transport source is invalid Python") from None
    tcp = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"),
        None,
    )
    if tcp is None:
        return text
    methods = {
        node.name: node for node in tcp.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    disconnect = methods.get("_disconnect")
    run = methods.get("run")
    if disconnect is None or run is None:
        raise ValueError("unsupported legacy TCPTransport layout")

    if not (upgrading_v1 or upgrading_v2 or upgrading_v3 or upgrading_v4 or upgrading_v5 or upgrading_v6 or upgrading_v6 or upgrading_v6 or upgrading_v6):
        disconnect_source = ast.get_source_segment(text, disconnect) or ""
        updated_disconnect, count = re.subn(
            r"(?m)^([ \t]*)if not self\.connected:[ \t]*$",
            r"\1if self.server_sock is None and self.queue_thread is None:",
            disconnect_source,
            count=1,
        )
        if count != 1:
            raise ValueError("unsupported legacy transport disconnect guard")
        text = text.replace(disconnect_source, updated_disconnect, 1)

        # Reparse after the source edit so line/column spans remain exact.
        tree = ast.parse(text, feature_version=(3, 10))
        tcp = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"
        )
        run = next(
            node for node in tcp.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
        )
        run_source = ast.get_source_segment(text, run) or ""
        pattern = (
            r"(?m)^([ \t]*)except Exception:[ \t]*\n"
            r"([ \t]*)(self\.callback_manager\.call_callbacks\("
            r"['\"]transport_connection_failed['\"]\))"
        )
        updated_run, count = re.subn(
            pattern,
            lambda match: (
                match.group(1) + "except Exception:\n"
                + match.group(2) + "self._disconnect()\n"
                + match.group(2) + match.group(3)
            ),
            run_source,
            count=1,
        )
        if count != 1:
            raise ValueError("unsupported legacy transport connection-failure path")
        text = text.replace(run_source, updated_run, 1)

    if not (upgrading_v2 or upgrading_v3 or upgrading_v4 or upgrading_v5 or upgrading_v6 or upgrading_v6 or upgrading_v6):
        # Shut down the socket before joining the sender. A sender blocked in
        # sendall() otherwise prevents _disconnect() and reconnect from completing.
        tree = ast.parse(text, feature_version=(3, 10))
        tcp = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"
        )
        disconnect = next(
            node for node in tcp.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_disconnect"
        )
        disconnect_source = ast.get_source_segment(text, disconnect) or ""
        queue_pattern = r"(?m)^([ \t]*)if self\.queue_thread is not None:[ \t]*$"

        def add_shutdown(match):
            indent = match.group(1)
            unit = "\t" if "\t" in indent else "    "
            return (
                indent + "if self.server_sock is not None:\n"
                + indent + unit + "try:\n"
                + indent + unit + unit + "self.server_sock.shutdown(socket.SHUT_RDWR)\n"
                + indent + unit + "except (OSError, AttributeError):\n"
                + indent + unit + unit + "pass\n"
                + indent + "if self.queue_thread is not None:"
            )

        updated_disconnect, count = re.subn(
            queue_pattern, add_shutdown, disconnect_source, count=1)
        if count != 1:
            raise ValueError("unsupported legacy transport send-thread cleanup")

        close_pattern = (
            r"(?m)^([ \t]*)self\.server_sock\.close\(\)[ \t]*\n"
            r"\1self\.server_sock = None[ \t]*$"
        )

        def guard_close(match):
            indent = match.group(1)
            unit = "\t" if "\t" in indent else "    "
            return (
                indent + "if self.server_sock is not None:\n"
                + indent + unit + "self.server_sock.close()\n"
                + indent + unit + "self.server_sock = None"
            )

        updated_disconnect, count = re.subn(
            close_pattern, guard_close, updated_disconnect, count=1)
        if count != 1:
            raise ValueError("unsupported legacy transport socket close")
        text = text.replace(disconnect_source, updated_disconnect, 1)

    if not (upgrading_v3 or upgrading_v4 or upgrading_v5 or upgrading_v6 or upgrading_v6):
        # A malformed relay frame raises JSONDecodeError/ValueError, not socket.error.
        # Treat any ordinary receive/parse exception as a broken connection so the
        # native connector loop survives and retries. BaseException still propagates.
        tree = ast.parse(text, feature_version=(3, 10))
        tcp = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"
        )
        run = next(
            node for node in tcp.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
        )
        run_source = ast.get_source_segment(text, run) or ""
        receive_pattern = (
            r"(self\.handle_server_data\(\)[ \t]*\n"
            r"([ \t]*)except )socket\.error(:)"
        )
        updated_run, count = re.subn(
            receive_pattern,
            lambda match: match.group(1) + "Exception" + match.group(3),
            run_source,
            count=1,
        )
        if count != 1:
            raise ValueError("unsupported legacy transport receive-failure path")
        text = text.replace(run_source, updated_run, 1)

    if not (upgrading_v4 or upgrading_v5 or upgrading_v6):
        # Concurrent close can invalidate the descriptor between the while guard and
        # select(). Python reports that as ValueError, not OSError/socket.error.
        tree = ast.parse(text, feature_version=(3, 10))
        tcp = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"
        )
        run = next(
            node for node in tcp.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
        )
        run_source = ast.get_source_segment(text, run) or ""
        select_pattern = (
            r"(select\.select\([^\n]*\n(?:[^\n]*\n)*?"
            r"([ \t]*)except )socket\.error(:)"
        )
        updated_run, count = re.subn(
            select_pattern,
            lambda match: match.group(1) + "(socket.error, ValueError)" + match.group(3),
            run_source,
            count=1,
        )
        if count != 1:
            raise ValueError("unsupported legacy transport select-failure path")
        text = text.replace(run_source, updated_run, 1)

    # A write-side socket failure used to terminate only the sender thread,
    # leaving the transport marked connected and future messages queued forever.
    # Shut down the socket so run()/select wakes and the normal reconnect path runs.
    tree = ast.parse(text, feature_version=(3, 10))
    tcp = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TCPTransport"
    )
    send_queue = next(
        node for node in tcp.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "send_queue"
    )
    send_source = ast.get_source_segment(text, send_queue) or ""
    send_pattern = (
        r"(?m)^([ \t]*)except socket\.error:[ \t]*\n"
        r"([ \t]*)return[ \t]*$"
    )

    def wake_receiver(match):
        indent = match.group(1)
        body = match.group(2)
        unit = "\t" if "\t" in body else "    "
        return (
            indent + "except socket.error:\n"
            + body + "try:\n"
            + body + unit + "if self.server_sock is not None:\n"
            + body + unit + unit + "self.server_sock.shutdown(socket.SHUT_RDWR)\n"
            + body + "except (OSError, AttributeError):\n"
            + body + unit + "pass\n"
            + body + "return"
        )

    if not (upgrading_v5 or upgrading_v6):
        updated_send, count = re.subn(send_pattern, wake_receiver, send_source, count=1)
        if count != 1:
            raise ValueError("unsupported legacy transport send-failure path")
        text = text.replace(send_source, updated_send, 1)

    # EOF must be tested on the new read, before adding a partial JSON frame.
    # Otherwise an incomplete cached line makes EOF look nonempty forever,
    # select() keeps waking, and the native connector never reconnects.
    tree = ast.parse(text, feature_version=(3, 10))
    tcp = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "TCPTransport")
    receiver = next((node for node in tcp.body if isinstance(node, ast.FunctionDef)
                     and node.name == "handle_server_data"), None)
    receiver_source = ast.get_source_segment(text, receiver) if receiver is not None else ""
    if "self.server_sock.recv(" in receiver_source:
        receive_pattern = (
            r"(?m)^([ \t]*)data = self\.buffer \+ self\.server_sock\.recv\(buffSize\)[ \t]*\n"
            r"\1self\.buffer = b''[ \t]*\n"
            r"\1if not data:[ \t]*\n"
            r"([ \t]*)self\._disconnect\(\)[ \t]*\n"
            r"\2return[ \t]*$"
        )

        def check_eof(match):
            indent, body = match.group(1), match.group(2)
            return (indent + "current_socket = self.server_sock\n"
                    + indent + "received = current_socket.recv(buffSize)\n"
                    + indent + "if self.server_sock is not current_socket:\n"
                    + body + "return\n"
                    + indent + "if not received:\n"
                    + body + "self.buffer = b''\n"
                    + body + "self._disconnect()\n"
                    + body + "return\n"
                    + indent + "data = self.buffer + received\n"
                    + indent + "self.buffer = b''")

        updated_receiver, count = re.subn(receive_pattern, check_eof, receiver_source, count=1)
        if count != 1:
            raise ValueError("unsupported legacy transport EOF handling")
        # A callback can close or replace the connection while a single read
        # still contains later key/braille messages. Never deliver those old
        # records or append their tail to the replacement session's buffer.
        def guard_parse(match):
            indent = match.group(1)
            unit = "\t" if "\t" in indent else "    "
            return (indent + "self.parse(line)\n"
                    + indent + "if self.server_sock is not current_socket:\n"
                    + indent + unit + "return")

        updated_receiver, count = re.subn(
            r"(?m)^([ \t]*)self\.parse\(line\)[ \t]*$", guard_parse, updated_receiver, count=1)
        if count != 1 or not _ast_equal(
            ast.parse(updated_receiver).body[0], ast.parse(_TRANSPORT_RECEIVER_V6).body[0]
        ):
            raise ValueError("unsupported legacy transport receive ownership")
        text = text.replace(receiver_source, updated_receiver, 1)

    # A peer can otherwise send an unterminated JSON record forever and grow
    # self.buffer without bound. Normalize all supported versions to the
    # verified v6 receiver first, then add a bounded pending-frame policy.
    tree = ast.parse(text, feature_version=(3, 10))
    tcp = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "TCPTransport")
    receiver = next((node for node in tcp.body if isinstance(node, ast.FunctionDef)
                     and node.name == "handle_server_data"), None)
    receiver_source = ast.get_source_segment(text, receiver) if receiver is not None else ""
    if ".recv(" in receiver_source:
        if receiver is None or not _ast_equal(
                receiver, ast.parse(_TRANSPORT_RECEIVER_V6).body[0]):
            raise ValueError("unsupported legacy transport pending-frame layout")
        pending_pattern = (
            r"(?m)^([ \t]*)if b'\\n' not in data:[ \t]*\n"
            r"([ \t]*)self\.buffer \+= data[ \t]*\n"
            r"\2return[ \t]*$"
        )

        def bound_pending_frame(match):
            indent, body = match.group(1), match.group(2)
            unit = body[len(indent):] if body.startswith(indent) else ""
            if not unit:
                unit = "\t" if "\t" in body else "    "
            nested = body + unit
            return (
                indent + "if b'\\n' not in data:\n"
                + body + "if len(data) > 1 << 20:\n"
                + nested + "self.buffer = b''\n"
                + nested + "self._disconnect()\n"
                + nested + "return\n"
                + body + "self.buffer += data\n"
                + body + "return"
            )

        bounded_receiver, count = re.subn(
            pending_pattern, bound_pending_frame, receiver_source, count=1)
        if count != 1:
            raise ValueError("unsupported legacy transport pending-frame guard")

        line_pattern = (
            r"(?m)^([ \t]*)line, sep, data = data\.partition\(b'\\n'\)[ \t]*\n"
            r"\1self\.parse\(line\)[ \t]*$"
        )

        def bound_complete_frame(match):
            indent = match.group(1)
            unit = "\t" if "\t" in indent else "    "
            body = indent + unit
            return (
                indent + "line, sep, data = data.partition(b'\\n')\n"
                + indent + "if len(line) > 1 << 20:\n"
                + body + "self.buffer = b''\n"
                + body + "self._disconnect()\n"
                + body + "return\n"
                + indent + "self.parse(line)"
            )

        bounded_receiver, line_count = re.subn(
            line_pattern, bound_complete_frame, bounded_receiver, count=1)
        if line_count != 1 or not _ast_equal(
                ast.parse(bounded_receiver).body[0],
                ast.parse(_TRANSPORT_RECEIVER_V7).body[0]):
            raise ValueError("unsupported legacy transport frame-size guard")
        text = text.replace(receiver_source, bounded_receiver, 1)

    # close() may run before run() reaches its final connected=False assignment.
    # Invalidate the advertised state now so speech and input are not queued
    # for a dead channel, and no incomplete frame survives that session.
    tree = ast.parse(text, feature_version=(3, 10))
    tcp = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "TCPTransport")
    disconnect = next(node for node in tcp.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_disconnect")
    disconnect_source = ast.get_source_segment(text, disconnect) or ""
    updated_disconnect, count = re.subn(
        r"(?m)^([ \t]*)if self\.server_sock is None and self\.queue_thread is None:[ \t]*$",
        lambda match: (match.group(1) + "self.connected = False\n"
                       + match.group(1) + "self.buffer = b''\n"
                       + match.group(0)),
        disconnect_source, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport disconnect state")
    text = text.replace(disconnect_source, updated_disconnect, 1)

    # Native reconnect() starts a replacement ConnectorThread on this same
    # object. The old run must not select, notify, or clean up that new session
    # after a callback replaces its socket.
    tree = ast.parse(text, feature_version=(3, 10))
    tcp = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "TCPTransport")
    run = next(node for node in tcp.body if isinstance(node, ast.FunctionDef)
               and node.name == "run")
    run_source = ast.get_source_segment(text, run) or ""
    updated_run, count = re.subn(
        r"(?m)^([ \t]*)try:[ \t]*$",
        lambda match: match.group(1) + "current_socket = None\n" + match.group(0),
        run_source, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport connection scope")
    updated_run, count = re.subn(
        r"(?m)^([ \t]*)self\.server_sock\.connect\(self\.address\)[ \t]*$",
        lambda match: (match.group(1) + "current_socket = self.server_sock\n"
                       + match.group(1) + "current_socket.connect(self.address)"),
        updated_run, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport connection ownership")

    def guard_connected(match):
        indent = match.group(1)
        unit = "\t" if "\t" in indent else "    "
        guard = (indent + "if self.server_sock is not current_socket:\n"
                 + indent + unit + "return\n")
        return guard + match.group(0) + "\n" + guard.rstrip("\n")

    updated_run, count = re.subn(
        r"(?m)^([ \t]*)(?:self\.transport_connected\(\)|self\.connected = True)[ \t]*$",
        guard_connected, updated_run, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport connected callback")
    updated_run, count = re.subn(
        r"while self\.server_sock is not None:",
        "while self.server_sock is current_socket:", updated_run, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport receive loop")
    updated_run = updated_run.replace("[self.server_sock]", "[current_socket]")

    def guard_selected(match):
        indent = match.group(1)
        unit = "\t" if "\t" in indent else "    "
        return (indent + "if self.server_sock is not current_socket:\n"
                + indent + unit + "break\n" + match.group(0))

    updated_run, count = re.subn(
        r"(?m)^([ \t]*)if self\.server_sock in error:[ \t]*$",
        guard_selected, updated_run, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport select ownership")

    def guard_teardown(match):
        indent = match.group(1)
        unit = "\t" if "\t" in indent else "    "
        return (indent + "if self.server_sock is not None and self.server_sock is not current_socket:\n"
                + indent + unit + "return\n" + match.group(0))

    updated_run, count = re.subn(
        r"(?m)^([ \t]*)self\.connected = False[ \t]*$",
        guard_teardown, updated_run, count=1)
    if count != 1:
        raise ValueError("unsupported legacy transport disconnected callback")
    updated_run, count = re.subn(
        r"(?m)^([ \t]*)self\._disconnect\(\)[ \t]*$",
        guard_teardown, updated_run, count=2)
    if count != 2:
        raise ValueError("unsupported legacy transport cleanup ownership")
    text = text.replace(run_source, updated_run, 1)

    text = text.rstrip("\n") + "\n\n" + TRANSPORT_CLEANUP_MARKER + "\n"
    if not legacy_transport_cleanup_patch_current(text):
        raise ValueError("transport cleanup patch validation failed")
    return text


def _patch_legacy_transport_logging(path: Path) -> bool:
    """Redact the relay key log and repair verified legacy transport cleanup."""
    text = path.read_text(encoding="utf-8")
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if backup.exists():
        backup.chmod(0o600)
    updated = text
    original = 'log.info("Connecting to %s channel %s" % (address, channel))'
    if original in updated:
        updated = updated.replace(
            original, 'log.info("Connecting to remote relay %s", address)')
    updated = _patch_legacy_transport_cleanup(updated)
    if updated == text:
        return False
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
    previous_hook = next((hook for hook in (_LOCAL_SPEECH_PREF_HOOK_V1, _LOCAL_SPEECH_PREF_HOOK_V2,
                                          _LOCAL_SPEECH_PREF_HOOK_V3)
                          if hook in text), None)
    if previous_hook is not None:
        text = text.replace(previous_hook, _LOCAL_SPEECH_PREF_HOOK, 1)
    elif _LOCAL_SPEECH_PREF_HOOK not in text:
        if LOCAL_SPEECH_PREF_MARKER in text:
            raise ValueError("unrecognized local speech preference patch")
        text = text.rstrip("\n") + "\n\n" + _LOCAL_SPEECH_PREF_HOOK

    text = _patch_legacy_customization_event_api(text)
    text = _patch_legacy_customization_speech_sequence(text)
    text = _patch_legacy_customization_say_all_callbacks(text)
    text = _patch_legacy_customization_reconnect(text)

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

    transport_path = path.parent / LEGACY_TRANSPORT_RELATIVE
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
LEGACY_TRANSPORT_RELATIVE = Path("orca-scripts/transport.py")
TRANSPORT_CLEANUP_MARKER_V1 = "# linux-rdaccess transport cleanup v1"
TRANSPORT_CLEANUP_MARKER_V2 = "# linux-rdaccess transport cleanup v2"
TRANSPORT_CLEANUP_MARKER_V3 = "# linux-rdaccess transport cleanup v3"
TRANSPORT_CLEANUP_MARKER_V4 = "# linux-rdaccess transport cleanup v4"
TRANSPORT_CLEANUP_MARKER_V5 = "# linux-rdaccess transport cleanup v5"
TRANSPORT_CLEANUP_MARKER_V6 = "# linux-rdaccess transport cleanup v6"
TRANSPORT_CLEANUP_MARKER = "# linux-rdaccess transport cleanup v7"
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
LEGACY_COMPAT_MARKER_V31 = "# linux-rdaccess NVDA/Orca input compatibility v31"
LEGACY_COMPAT_MARKER_V32 = "# linux-rdaccess NVDA/Orca input compatibility v32"
LEGACY_COMPAT_MARKER_V33 = "# linux-rdaccess NVDA/Orca input compatibility v33"
LEGACY_COMPAT_MARKER_V34 = "# linux-rdaccess NVDA/Orca input compatibility v34"
LEGACY_COMPAT_MARKER_V35 = "# linux-rdaccess NVDA/Orca input compatibility v35"
LEGACY_COMPAT_MARKER_V36 = "# linux-rdaccess NVDA/Orca input compatibility v36"
LEGACY_COMPAT_MARKER_V37 = "# linux-rdaccess NVDA/Orca input compatibility v37"
LEGACY_COMPAT_MARKER_V38 = "# linux-rdaccess NVDA/Orca input compatibility v38"
LEGACY_COMPAT_MARKER_V39 = "# linux-rdaccess NVDA/Orca input compatibility v39"
LEGACY_COMPAT_MARKER_V40 = "# linux-rdaccess NVDA/Orca input compatibility v40"
LEGACY_COMPAT_MARKER_V41 = "# linux-rdaccess NVDA/Orca input compatibility v41"
LEGACY_COMPAT_MARKER_V42 = "# linux-rdaccess NVDA/Orca input compatibility v42"
LEGACY_COMPAT_MARKER_V43 = "# linux-rdaccess NVDA/Orca input compatibility v43"
LEGACY_COMPAT_MARKER_V44 = "# linux-rdaccess NVDA/Orca input compatibility v44"
LEGACY_COMPAT_MARKER_V45 = "# linux-rdaccess NVDA/Orca input compatibility v45"
LEGACY_COMPAT_MARKER_V46 = "# linux-rdaccess NVDA/Orca input compatibility v46"
LEGACY_COMPAT_MARKER_V47 = "# linux-rdaccess NVDA/Orca input compatibility v47"
LEGACY_COMPAT_MARKER_V48 = "# linux-rdaccess NVDA/Orca input compatibility v48"
LEGACY_COMPAT_MARKER_V49 = "# linux-rdaccess NVDA/Orca input compatibility v49"
LEGACY_COMPAT_MARKER_V50 = "# linux-rdaccess NVDA/Orca input compatibility v50"
LEGACY_COMPAT_MARKER_V51 = "# linux-rdaccess NVDA/Orca input compatibility v51"
LEGACY_COMPAT_MARKER_V52 = "# linux-rdaccess NVDA/Orca input compatibility v52"
LEGACY_COMPAT_MARKER_V53 = "# linux-rdaccess NVDA/Orca input compatibility v53"
LEGACY_COMPAT_MARKER_V54 = "# linux-rdaccess NVDA/Orca input compatibility v54"
LEGACY_COMPAT_MARKER_V55 = "# linux-rdaccess NVDA/Orca input compatibility v55"
LEGACY_COMPAT_MARKER_V56 = "# linux-rdaccess NVDA/Orca input compatibility v56"
LEGACY_COMPAT_MARKER_V57 = "# linux-rdaccess NVDA/Orca input compatibility v57"
LEGACY_COMPAT_MARKER_V58 = "# linux-rdaccess NVDA/Orca input compatibility v58"
LEGACY_COMPAT_MARKER_V59 = "# linux-rdaccess NVDA/Orca input compatibility v59"
LEGACY_COMPAT_MARKER_V60 = "# linux-rdaccess NVDA/Orca input compatibility v60"
LEGACY_COMPAT_MARKER_V61 = "# linux-rdaccess NVDA/Orca input compatibility v61"
LEGACY_COMPAT_MARKER_V62 = "# linux-rdaccess NVDA/Orca input compatibility v62"
LEGACY_COMPAT_MARKER_V63 = "# linux-rdaccess NVDA/Orca input compatibility v63"
LEGACY_COMPAT_MARKER_V64 = "# linux-rdaccess NVDA/Orca input compatibility v64"
LEGACY_COMPAT_MARKER_V65 = "# linux-rdaccess NVDA/Orca input compatibility v65"
LEGACY_COMPAT_MARKER_V66 = "# linux-rdaccess NVDA/Orca input compatibility v66"
LEGACY_COMPAT_MARKER_V67 = "# linux-rdaccess NVDA/Orca input compatibility v67"
LEGACY_COMPAT_MARKER_V68 = "# linux-rdaccess NVDA/Orca input compatibility v68"
LEGACY_COMPAT_MARKER_V69 = "# linux-rdaccess NVDA/Orca input compatibility v69"
LEGACY_COMPAT_MARKER_V70 = "# linux-rdaccess NVDA/Orca input compatibility v70"
LEGACY_COMPAT_MARKER_V71 = "# linux-rdaccess NVDA/Orca input compatibility v71"
LEGACY_COMPAT_MARKER_V72 = "# linux-rdaccess NVDA/Orca input compatibility v72"
LEGACY_COMPAT_MARKER_V73 = "# linux-rdaccess NVDA/Orca input compatibility v73"
LEGACY_COMPAT_MARKER_V74 = "# linux-rdaccess NVDA/Orca input compatibility v74"
LEGACY_COMPAT_MARKER_V75 = "# linux-rdaccess NVDA/Orca input compatibility v75"
LEGACY_COMPAT_MARKER_V76 = "# linux-rdaccess NVDA/Orca input compatibility v76"
LEGACY_COMPAT_MARKER_V77 = "# linux-rdaccess NVDA/Orca input compatibility v77"
LEGACY_COMPAT_MARKER_V78 = "# linux-rdaccess NVDA/Orca input compatibility v78"
LEGACY_COMPAT_MARKER_V79 = "# linux-rdaccess NVDA/Orca input compatibility v79"
LEGACY_COMPAT_MARKER_V80 = "# linux-rdaccess NVDA/Orca input compatibility v80"
LEGACY_COMPAT_MARKER_V81 = "# linux-rdaccess NVDA/Orca input compatibility v81"
LEGACY_COMPAT_MARKER_V82 = "# linux-rdaccess NVDA/Orca input compatibility v82"
LEGACY_COMPAT_MARKER_V83 = "# linux-rdaccess NVDA/Orca input compatibility v83"
LEGACY_COMPAT_MARKER_V84 = "# linux-rdaccess NVDA/Orca input compatibility v84"
LEGACY_COMPAT_MARKER_V85 = "# linux-rdaccess NVDA/Orca input compatibility v85"
LEGACY_COMPAT_MARKER_V86 = "# linux-rdaccess NVDA/Orca input compatibility v86"
LEGACY_COMPAT_MARKER_V87 = "# linux-rdaccess NVDA/Orca input compatibility v87"
LEGACY_COMPAT_MARKER_V88 = "# linux-rdaccess NVDA/Orca input compatibility v88"
LEGACY_COMPAT_MARKER_V89 = "# linux-rdaccess NVDA/Orca input compatibility v89"
LEGACY_COMPAT_MARKER_V90 = "# linux-rdaccess NVDA/Orca input compatibility v90"
LEGACY_COMPAT_MARKER_V91 = "# linux-rdaccess NVDA/Orca input compatibility v91"
LEGACY_COMPAT_MARKER_V92 = "# linux-rdaccess NVDA/Orca input compatibility v92"
LEGACY_COMPAT_MARKER_V93 = "# linux-rdaccess NVDA/Orca input compatibility v93"
LEGACY_COMPAT_MARKER = "# linux-rdaccess NVDA/Orca input compatibility v94"
# v1 is a prefix of every later marker, so any older patch is detected by it.

_LEGACY_HELPERS = '''\
    ''' + LEGACY_COMPAT_MARKER + '''
    # Helpers injected by linux-rdaccess. They never log key names, braille
    # dots, speech text or connection keys.
    _LRD_INPUT_LOCK = __import__("threading").RLock()
    _LRD_CTRL_VKS = (0x11, 0xA2, 0xA3)
    _LRD_LOCK_VKS = (0x14, 0x90, 0x91)  # Caps Lock, Num Lock, Scroll Lock
    _LRD_REPEAT_TOGGLE_VKS = (0x90, 0x91)  # repeated key-down would re-toggle
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
    # Display keys NVDA binds to "kb:<key>" emulation scripts. Only keys that
    # cannot type a character are forwarded; "kb:a", "kb:space" and any unknown
    # name stay redacted braille-keyboard input. name: (X key, vk, extended).
    _LRD_BRAILLE_KEYS = {
        "upArrow": ("Up", 0x26, True), "downArrow": ("Down", 0x28, True),
        "leftArrow": ("Left", 0x25, True), "rightArrow": ("Right", 0x27, True),
        "home": ("Home", 0x24, True), "end": ("End", 0x23, True),
        "pageUp": ("Prior", 0x21, True), "pageDown": ("Next", 0x22, True),
        "enter": ("Return", 0x0D, False), "tab": ("Tab", 0x09, False),
        "escape": ("Escape", 0x1B, False), "backspace": ("BackSpace", 0x08, False),
        "delete": ("Delete", 0x2E, True),
    }
    _LRD_BRAILLE_MODIFIERS = {
        "shift": ("Shift_L", 0xA0), "control": ("Control_L", 0xA2),
        "alt": ("Alt_L", 0xA4),
    }
    _LRD_TRACE_MAX_BYTES = 262144
    # Metadata-only input trace (LINUX_RDACCESS_TRACE=1). Only keys in this
    # fixed vocabulary are ever identified; a character key is recorded as
    # "char" with no identity, so typed text and passwords cannot be rebuilt.
    _LRD_TRACE_NAMES = {
        0x10: "Shift", 0xA0: "LShift", 0xA1: "RShift",
        0x11: "Ctrl", 0xA2: "LCtrl", 0xA3: "RCtrl",
        0x12: "Alt", 0xA4: "LAlt", 0xA5: "RAlt",
        0x5B: "LWin", 0x5C: "RWin", 0x14: "CapsLock", 0x90: "NumLock",
        0x91: "ScrollLock", 0x2D: "Insert", 0x2E: "Delete", 0x24: "Home",
        0x23: "End", 0x21: "PageUp", 0x22: "PageDown", 0x25: "Left",
        0x26: "Up", 0x27: "Right", 0x28: "Down", 0x1B: "Escape",
        0x09: "Tab", 0x0D: "Enter", 0x08: "Backspace", 0x5D: "Apps",
        0x0C: "Clear",
    }
    # Navigation-cluster VKs are ambiguous between the keypad and the dedicated
    # cluster, so the extended bit is reported verbatim and never interpreted.
    _LRD_TRACE_AMBIGUOUS_VKS = (
        0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x0D, 0x0C,
    )
    _LRD_TRACE_HELD_VKS = (
        0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5, 0x5B, 0x5C,
        0x2D, 0x14, 0x90, 0x91,
    )
    _LRD_TRACE_CLAIMS = {
        "_LRD_D": ("letter", False),
        "_LRD_BROWSE_UNSUPPORTED": ("letter", False),
        "_LRD_NVDA_BROWSE": ("nvda_browse", True),
        "_LRD_T": ("table_arrow", True),
        "_LRD_TABLE_EDGE": ("table_edge", True),
    }
    _LRD_OTHER_MOD_VKS = (
        0x10, 0xA0, 0xA1, 0x11, 0xA2, 0xA3, 0x12, 0xA4, 0xA5, 0x5B, 0x5C,
    )
    # Low-level Windows scan codes for physical numpad navigation keys.
    # NVDA Remote forwards KBDLLHOOKSTRUCT.scanCode verbatim, so these let us
    # distinguish a proven numpad key from a legacy non-extended navigation VK.
    _LRD_NUMPAD_SCAN_VKS = {
        0x4F: 0x23,  # Numpad1 -> End
        0x50: 0x28,  # Numpad2 -> Down
        0x51: 0x22,  # Numpad3 -> PageDown
        0x4B: 0x25,  # Numpad4 -> Left
        0x4C: 0x0C,  # Numpad5 -> Clear
        0x4D: 0x27,  # Numpad6 -> Right
        0x47: 0x24,  # Numpad7 -> Home
        0x48: 0x26,  # Numpad8 -> Up
        0x49: 0x21,  # Numpad9 -> PageUp
        0x53: 0x2E,  # NumpadDelete -> Delete
    }
    # NVDA chord -> Orca command, checked against the Orca 42 desktop keymap.
    # Report the caret line through Orca's script rather than entering flat
    # review with KP_Up. Other review commands still retain their native keys.
    #   vk: (extended-required, Orca key name, target vk, drop NVDA modifier,
    #        press count)
    # "drop" is needed where Orca binds the key with NO Orca modifier.
    _LRD_ACTION_CHORDS = {
        0x31: "input_help",                          # NVDA+1
        0x50: "punctuation",                         # NVDA+P
        0x4D: "mouse_review",                        # NVDA+M
        0x55: "progress_output",                     # NVDA+U
        0x09: "where_am_i",                          # NVDA+Tab
        0x23: "status_bar",                          # NVDA+End
        0x26: "current_line",                        # desktop NVDA+Up
        0x54: "title",                               # NVDA+T
        0x71: "pass_next",                           # NVDA+F2
        0x76: "elements_list",                       # NVDA+F7
        0x7B: "date_time",                           # NVDA+F12
    }
    _LRD_SHIFT_VKS = (0x10, 0xA0, 0xA1)
    _LRD_NVDA_VKS = (0x2D, 0x14)
    # Key: (vk, Shift held). Value: (extended-required, Orca key name, target
    # vk, drop NVDA modifier, press count, drop Shift). Orca matches the
    # modifier state exactly, so Shift is released around the key when Orca's
    # binding has none (verified against Orca 42 key matching).
    _LRD_CHORDS = {
    }

    @staticmethod
    def _linux_rdaccess_trace_enabled():
        return __import__("os").environ.get("LINUX_RDACCESS_TRACE") == "1"

    def _linux_rdaccess_trace(self, kind, **fields):
        """Record one metadata-only diagnostic event; never affects input."""
        if not self._linux_rdaccess_trace_enabled():
            return
        writer = globals().get("_lrd_trace_write")
        if writer is None:
            return
        try:
            writer(kind, gen=getattr(self, "_lrd_generation", 0), **fields)
        except Exception:
            pass

    @classmethod
    def _linux_rdaccess_trace_label(cls, vk_code, extended):
        """Fixed-vocabulary identity of a non-character key, else None."""
        if isinstance(vk_code, bool) or not isinstance(vk_code, int):
            return None
        name = cls._LRD_TRACE_NAMES.get(vk_code)
        if name is None and 0x70 <= vk_code <= 0x87:
            name = "F%d" % (vk_code - 0x6F)
        if name is None:
            return None
        if vk_code in cls._LRD_TRACE_AMBIGUOUS_VKS:
            name += "/ext" if extended else "/nonext"
        return name

    def _linux_rdaccess_trace_ownership(self):
        """Modifier ownership: keys received, keys injected, NVDA modifier."""
        label = self._linux_rdaccess_trace_label
        held_vks = self._LRD_TRACE_HELD_VKS
        down = getattr(self, "_lrd_down", set())
        forwarded = getattr(self, "_lrd_forwarded", {})
        nvda = getattr(self, "_lrd_nvda_key", None)
        return {
            "down": sorted(label(k[0], k[1]) for k in down if k[0] in held_vks),
            "fwd": sorted(label(k[0], k[1]) for k in forwarded if k[0] in held_vks),
            "nvda": label(nvda[0], nvda[1]) if nvda else None,
            "caps_pending": getattr(self, "_lrd_caps_pending", None) is not None,
            "insert_pending": getattr(self, "_lrd_insert_pending", None) is not None,
            "other_down": sum(1 for k in down if k[0] not in held_vks),
            "other_fwd": sum(1 for k in forwarded if k[0] not in held_vks),
        }

    def _linux_rdaccess_nvda_layout(self):
        """Return the configured Windows NVDA keyboard layout."""
        value = __import__("os").environ.get(
            "LINUX_RDACCESS_NVDA_LAYOUT", "desktop").strip().lower()
        return value if value in ("desktop", "laptop") else "desktop"

    @classmethod
    def _linux_rdaccess_proven_nvda_keypad(cls, vk_code, extended, scan_code, shift):
        """Whether scan metadata proves an NVDA object/review numpad gesture."""
        if bool(extended) or isinstance(scan_code, bool) or not isinstance(scan_code, int):
            return False
        if cls._LRD_NUMPAD_SCAN_VKS.get(scan_code) != vk_code:
            return False
        # NVDA 2026.2 object/review navigation uses NVDA+Numpad1..9 and
        # NVDA+NumpadDelete. Of these, only NumpadDelete also has a Shift form.
        return not shift or vk_code == 0x2E

    def _linux_rdaccess_plain_shift_numpad_unimplemented(
            self, vk_code, extended, scan_code=None):
        """Whether an exact plain Shift+numpad NVDA command is unsupported."""
        down = getattr(self, "_lrd_down", set())
        shift = any(k[0] in self._LRD_SHIFT_VKS for k in down)
        other = any(
            k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
            for k in down
        )
        if not shift or other or self._lrd_nvda_down:
            return False
        # NVDA 2026.2 binds these review commands with plain "kb:"
        # gestures, so the physical numpad bindings apply in both layouts.
        if (vk_code, scan_code) in {
            (0x23, 0x4F),  # Shift+Numpad1: start of review line
            (0x22, 0x51),  # Shift+Numpad3: end of review line
            (0x24, 0x47),  # Shift+Numpad7: top of review
            (0x21, 0x49),  # Shift+Numpad9: bottom of review
        } and not bool(extended):
            return True
        # These are unambiguous keypad VKs. Orca 42 treats Divide/Multiply as
        # clicks, whereas NVDA uses Shift+them to toggle mouse-button lock.
        return (
            (vk_code == 0x6F and bool(extended))
            or (vk_code == 0x6A and not bool(extended))
        )

    def _linux_rdaccess_desktop_unimplemented(self, vk_code, extended, scan_code=None):
        """Whether an exact NVDA desktop keypad object/review gesture is unsupported."""
        down = getattr(self, "_lrd_down", set())
        shift = any(k[0] in self._LRD_SHIFT_VKS for k in down)
        ctrl = any(k[0] in self._LRD_CTRL_VKS for k in down)
        alt_win = any(k[0] in (0x12, 0xA4, 0xA5, 0x5B, 0x5C) for k in down)
        if ctrl or alt_win:
            return False
        gesture = (vk_code, shift, bool(extended))
        # With a matching low-level scan code, NVDA Remote has proven that a
        # non-extended navigation VK came from the physical numpad. Consume
        # those unsupported NVDA object/review commands instead of leaking them
        # into the Linux application. Legacy packets without that evidence
        # retain the previous fail-open behavior.
        if self._linux_rdaccess_proven_nvda_keypad(
                vk_code, extended, scan_code, shift):
            return True
        return gesture in {
            (0x0C, False, False),  # NVDA+Numpad5 (VK_CLEAR): current navigator object
            (0x6D, False, False),  # NVDA+NumpadMinus: navigator to focus
            (0x6D, True, False),   # NVDA+Shift+NumpadMinus: focus/caret to navigator
            (0x6F, False, True),   # NVDA+NumpadDivide: mouse to navigator
            (0x6A, False, False),  # NVDA+NumpadMultiply: navigator to mouse
            (0x0D, False, True),   # NVDA+NumpadEnter: activate navigator object
        }

    def _linux_rdaccess_laptop_unimplemented(self, vk_code, extended, scan_code=None):
        """Whether an exact NVDA laptop object/review gesture is known but unsupported."""
        down = getattr(self, "_lrd_down", set())
        shift = any(k[0] in self._LRD_SHIFT_VKS for k in down)
        ctrl = any(k[0] in self._LRD_CTRL_VKS for k in down)
        alt_win = any(k[0] in (0x12, 0xA4, 0xA5, 0x5B, 0x5C) for k in down)
        if alt_win:
            return False
        # Exact NVDA 2026.2 laptop gestures whose semantics are navigator/review
        # operations, not ordinary application input. Keep these intercepted
        # until an Orca-42 API is proven equivalent.
        gestures = {
            (0x0D, False, False),  # NVDA+Enter: activate navigator object
            (0x08, False, False),  # NVDA+Backspace: navigator to focus
            (0x08, True, False),   # NVDA+Shift+Backspace: focus to navigator
            (0x4F, True, False),   # NVDA+Shift+O: report navigator object
            (0x4D, True, False),   # NVDA+Shift+M: mouse to navigator
            (0x4E, True, False),   # NVDA+Shift+N: navigator to mouse
            (0xDB, False, False),  # NVDA+[: left click
            (0xDD, False, False),  # NVDA+]: right click
            (0x21, False, True),   # NVDA+PageUp: next review mode
            (0x22, False, True),   # NVDA+PageDown: previous review mode
            (0x2E, False, True),   # NVDA+Delete: caret/focus location
            (0x2E, True, True),    # NVDA+Shift+Delete: review/object location
            (0x26, True, True),    # NVDA+Shift+Up: parent object
            (0x27, True, True),    # NVDA+Shift+Right: next object
            (0x25, True, True),    # NVDA+Shift+Left: previous object
            (0x28, True, True),    # NVDA+Shift+Down: first child
            (0x24, False, True),   # NVDA+Home: review line start
            (0x25, False, True),   # NVDA+Left: previous review character
            (0x27, False, True),   # NVDA+Right: next review character
            (0xBE, False, False),  # NVDA+Period: current review character
            (0xBE, True, False),   # NVDA+Shift+Period: current review line
            (0x21, True, True),    # NVDA+Shift+PageUp: previous review page
            (0x22, True, True),    # NVDA+Shift+PageDown: next review page
            (0x41, True, False),   # NVDA+Shift+A: review Say All
            # NVDA 2026.2 binds these with plain "kb:" gestures, so they work in
            # the laptop layout too. Identities are NVDA's own vkCodes entries
            # (VK_CLEAR, VK_SUBTRACT, VK_MULTIPLY, VK_DIVIDE, extended Enter);
            # navigation-cluster VKs are still never guessed to be the keypad.
            (0x0C, False, False),  # NVDA+Numpad5: current navigator object
            (0x6D, False, False),  # NVDA+NumpadMinus: navigator to focus
            (0x6D, True, False),   # NVDA+Shift+NumpadMinus: focus to navigator
            (0x6F, False, True),   # NVDA+NumpadDivide: mouse to navigator
            (0x6A, False, False),  # NVDA+NumpadMultiply: navigator to mouse
            (0x0D, False, True),   # NVDA+NumpadEnter: activate navigator object
        }
        # The physical numpad object/review bindings remain active regardless
        # of NVDA keyboard layout. Require scan-code proof so dedicated laptop
        # navigation keys are never mistaken for numpad input.
        if not ctrl and self._linux_rdaccess_proven_nvda_keypad(
                vk_code, extended, scan_code, shift):
            return True
        # Ctrl review commands are distinct from the plain/Shift gestures above.
        if ctrl:
            ctrl_gestures = {
                (0x24, False, True), (0x23, False, True),
                (0x25, False, True), (0x27, False, True),
                (0xBE, False, False),
                (0xDB, False, False), (0xDD, False, False),
            }
            return (vk_code, shift, bool(extended)) in ctrl_gestures
        return (vk_code, shift, bool(extended)) in gestures

    def _linux_rdaccess_known_unimplemented(self, vk_code, extended):
        """Whether this exact documented NVDA command is not yet emulated."""
        down = getattr(self, "_lrd_down", set())
        layout = self._linux_rdaccess_nvda_layout()
        shift = any(k[0] in self._LRD_SHIFT_VKS for k in down)
        ctrl = any(k[0] in self._LRD_CTRL_VKS for k in down)
        alt = any(k[0] in (0x12, 0xA4, 0xA5) for k in down)
        win = any(k[0] in (0x5B, 0x5C) for k in down)
        if win:
            return False
        gesture = (vk_code, shift, ctrl, alt, bool(extended))
        return gesture in {
            (0x4E, False, False, False, False),  # NVDA+N: NVDA menu
            (0x51, False, False, False, False),  # NVDA+Q: quit NVDA
            (0x43, False, False, False, False),  # NVDA+C: clipboard report
            (0x52, False, False, False, False),  # NVDA+R: OCR
            (0x58, False, False, False, False),  # NVDA+X: repeat last speech
            (0x58, False, True,  False, False),  # NVDA+Ctrl+X: copy last speech
            (0x78, False, False, False, False),  # NVDA+F9: review mark
            (0x78, True,  False, False, False),  # NVDA+Shift+F9
            (0x79, False, False, False, False),  # NVDA+F10: select/copy review
            (0x72, False, True,  False, False),  # NVDA+Ctrl+F3: reload plugins
            (0x1B, False, True,  False, False),  # NVDA+Ctrl+Escape: screen curtain
            (0x57, True,  False, False, False),  # NVDA+Shift+W: magnifier
            (0xBB, True,  False, False, False),  # NVDA+Shift+=: zoom in
            (0xBD, True,  False, False, False),  # NVDA+Shift+-: zoom out
            (0x49, True,  False, False, False),  # NVDA+Shift+I: color filter
            (0x4C, True,  False, False, False),  # NVDA+Shift+L: overview
            (0x53, False, False, True,  False),  # NVDA+Alt+S: sound split
            (0x52, False, False, True,  False),  # NVDA+Alt+R: Remote connect
            (0x09, False, False, True,  False),  # NVDA+Alt+Tab: Remote key control
            (0x25, False, False, True,  True),   # NVDA+Alt+Arrow: magnifier pan
            (0x27, False, False, True,  True),
            (0x26, False, False, True,  True),
            (0x28, False, False, True,  True),
            (0x25, True,  False, True,  True),   # NVDA+Shift+Alt+Arrow: edge pan
            (0x27, True,  False, True,  True),
            (0x26, True,  False, True,  True),
            (0x28, True,  False, True,  True),
            (0x54, False, True,  True,  False),  # NVDA+Ctrl+Alt+T
            (0x70, False, False, False, False),  # NVDA+F1
            (0x70, False, True,  False, False),  # NVDA+Ctrl+F1
            (0x70, True,  True,  False, False),  # NVDA+Ctrl+Shift+F1
            (0x44, True,  False, False, False),  # NVDA+Shift+D: audio ducking
            (0x4B, False, False, True,  False),  # NVDA+Alt+K: braille autoscroll
            (0x4C, False, False, True,  False),  # NVDA+Alt+L: braille scroll faster
            (0x4A, False, False, True,  False),  # NVDA+Alt+J: braille scroll slower
            (0x46, True,  False, False, False),  # NVDA+Shift+F: review formatting
            (0x44, False, False, False, False),  # NVDA+D: annotation details
            (0x54, False, False, True,  False),  # NVDA+Alt+T: braille mode
            (0x4D, False, False, True,  False),  # NVDA+Alt+M: math interaction
            (0x24, False, False, True,  True),   # NVDA+Alt+Home: review selection start
            (0x23, False, False, True,  True),   # NVDA+Alt+End: review selection end
            (0x25, False, True,  True,  True),   # NVDA+Ctrl+Alt+Left: speak row
            (0x27, False, True,  True,  True),   # NVDA+Ctrl+Alt+Right: say row
            (0x26, False, True,  True,  True),   # NVDA+Ctrl+Alt+Up: speak column
            (0x28, False, True,  True,  True),   # NVDA+Ctrl+Alt+Down: say column
        } or (
            layout == "desktop"
            and gesture in {
                (0x53, True,  False, False, False),  # NVDA+Shift+S: app sleep
                (0x26, False, True,  False, True),   # synth ring
                (0x28, False, True,  False, True),
                (0x25, False, True,  False, True),
                (0x27, False, True,  False, True),
                (0x21, False, True,  False, True),
                (0x22, False, True,  False, True),
                (0x71, False, True,  False, False),  # NVDA+Ctrl+F2: display model
                (0x63, False, False, False, False),  # VK_NUMPAD3 (NVDA: numLockNumpad3, unbound); NVDA's next-in-flow is the non-extended PageDown identity, which is never guessed
                (0x69, False, False, False, False),  # VK_NUMPAD9 (NVDA: numLockNumpad9, unbound); previous-in-flow is the non-extended PageUp identity
                (0x21, False, False, False, True),  # NVDA+PageUp: previous review page
                (0x22, False, False, False, True),  # NVDA+PageDown: next review page
            }
        ) or (
            layout == "laptop"
            and gesture in {
                (0x5A, True,  False, False, False),  # NVDA+Shift+Z: app sleep
                (0x26, True,  True,  False, True),   # synth ring
                (0x28, True,  True,  False, True),
                (0x25, True,  True,  False, True),
                (0x27, True,  True,  False, True),
                (0x21, True,  True,  False, True),
                (0x22, True,  True,  False, True),
                (0xDB, True,  False, False, False),  # Shift+NVDA+[: previous in flow
                (0xDD, True,  False, False, False),  # Shift+NVDA+]: next in flow
            }
        )

    def _linux_rdaccess_clock_command(self):
        """Select time/date for consecutive complete NVDA+F12 gestures."""
        now = __import__("time").monotonic()
        generation = getattr(self, "_lrd_generation", 0)
        previous = getattr(self, "_lrd_last_clock_press", None)
        repeated = (previous is not None and previous[0] == generation
                    and 0 <= now - previous[1] <= 0.5)
        self._lrd_last_clock_press = (generation, now)
        return "presentDate" if repeated else "presentTime"

    def _linux_rdaccess_stop_local_speech(self):
        """Stop Linux-side speech on Orca's main loop, never on the network thread.

        Orca's speech-dispatcher client is not thread-safe and a stop blocks
        until speech-dispatcher answers. Doing that on the thread that receives
        keys stalled all key forwarding whenever Orca was busy (Firefox), which
        looked like a freeze. Requests are coalesced: at most one is pending.
        """
        if getattr(self, "_lrd_local_stop_pending", False):
            self._linux_rdaccess_trace("speech", what="local_stop_coalesced")
            return
        self._lrd_local_stop_pending = True
        self._linux_rdaccess_trace("speech", what="local_stop_requested")

        def run():
            self._lrd_local_stop_pending = False
            self._linux_rdaccess_trace("speech", what="local_stop_ran")
            try:
                self.local_machine.cancel_speech()
            except Exception:
                log.error("linux-rdaccess: failed to cancel speech")

        if self._linux_rdaccess_run_main(run) is False:
            self._lrd_local_stop_pending = False
            self._linux_rdaccess_trace("speech", what="local_stop_unscheduled")

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
                self._linux_rdaccess_trace("speech", what="nvda_cancel_sent")
            else:
                self._linux_rdaccess_trace("speech", what="nvda_cancel_not_applicable")
        except Exception:
            self._linux_rdaccess_trace("speech", what="nvda_cancel_failed")
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
        tracing = self._linux_rdaccess_trace_enabled()
        lock_vk = payload.get("vk_code") if payload.get("vk_code") in self._LRD_LOCK_VKS else None
        lock_before = (self._linux_rdaccess_read_lock_state(lock_vk)
                       if tracing and lock_vk is not None else None)
        candidate = getattr(self, "_lrd_navigation_marker", None)
        self._lrd_navigation_marker = None
        marker = token = None
        if pressed and candidate is not None and candidate[2] == held:
            marker = globals().get(candidate[0])
            if isinstance(marker, dict):
                # Publish before dispatch: XTest can reach Orca's thread before
                # send_key returns. A rejected injection owns no marker.
                token = _lrd_publish_navigation_marker(marker, candidate[1])
        native_request = getattr(self, "_lrd_bypass_dispatch", None)
        try:
            native_name = (getattr(self, "_lrd_bypass_name", None) if native_request is not None
                           else self._linux_rdaccess_bypass_key_name(payload))
        except Exception:
            native_name = None
        native_token = (_lrd_publish_bypass_key(native_name, pressed, native_request)
                        if native_name else None)
        try:
            result = self.local_machine.send_key(**payload)
        except BaseException:
            if token is not None:
                _lrd_remove_navigation_marker(marker, token)
            if native_token is not None:
                _lrd_remove_bypass_key(native_token)
            if tracing:
                self._linux_rdaccess_trace(
                    "forward", id=self._linux_rdaccess_trace_label(
                        payload.get("vk_code"), payload.get("extended")) or "char",
                    down=pressed, result="raised")
            raise
        if result is False and token is not None:
            _lrd_remove_navigation_marker(marker, token)
        if result is False and native_token is not None:
            _lrd_remove_bypass_key(native_token)
        if tracing:
            self._linux_rdaccess_trace(
                "forward", id=self._linux_rdaccess_trace_label(
                    payload.get("vk_code"), payload.get("extended")) or "char",
                down=pressed, result="rejected" if result is False else "ok",
                owned=held in forwarded or (result is not False and pressed))
            if lock_vk is not None:
                # XKB lock transition around one injected lock key: exactly one
                # change is expected per physical press, in each direction.
                after = self._linux_rdaccess_read_lock_state(lock_vk)
                self._linux_rdaccess_trace(
                    "lock", id=self._linux_rdaccess_trace_label(lock_vk, False),
                    down=pressed, before=lock_before, after=after,
                    changed=(lock_before != after
                             if type(lock_before) is bool and type(after) is bool
                             else None))
        if result is not False:
            if pressed:
                forwarded[held] = dict(payload)
            else:
                forwarded.pop(held, None)
                vk_code = payload.get("vk_code")
                if vk_code in self._LRD_LOCK_VKS:
                    # XKB can clear an already-on lock only on key-up. Read
                    # after the successful owned release, before another key
                    # can toggle it again, and carry that state to Orca's loop.
                    enabled = self._linux_rdaccess_read_lock_state(vk_code)
                    if type(enabled) is bool:
                        self._linux_rdaccess_run_main(
                            lambda vk=vk_code, state=enabled:
                                self._linux_rdaccess_script_call(
                                    "presentLockState", vk, state))
        return result

    @staticmethod
    def _linux_rdaccess_read_lock_state(vk_code):
        """Snapshot XKB without touching Orca state on the receive thread."""
        try:
            from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter as _adapter
            return _adapter.read_lock_state(vk_code)
        except ImportError:
            return None
        except Exception:
            log.error("linux-rdaccess: lock-state snapshot unavailable")
            return None

    def _linux_rdaccess_reset_keys(self):
        """Release forwarded held keys and clear compatibility state.

        Remote disconnects/control hand-offs can lose key-up events. Only
        successful forwards acquire release ownership; failed releases remain
        owned so a later reset can retry them.
        """
        forwarded = getattr(self, "_lrd_forwarded", {})
        trace_held = sorted(
            self._linux_rdaccess_trace_label(k[0], k[1]) or "char"
            for k in forwarded) if self._linux_rdaccess_trace_enabled() else None
        local_machine = getattr(self, "local_machine", None)
        invalidate = getattr(local_machine, "_linux_rdaccess_invalidate_pending", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                log.error("linux-rdaccess: failed to invalidate queued local work")
        send = getattr(local_machine, "send_key", None)
        if callable(send):
            order = lambda item: (isinstance(item[0], str), str(item[0]) if isinstance(item[0], str) else item[0] or 0, item[1])
            for held in sorted(list(forwarded), key=order):
                try:
                    release = dict(forwarded[held], pressed=False)
                    if send(**release) is not False:
                        forwarded.pop(held, None)
                except Exception:
                    log.error("linux-rdaccess: failed to release held key on reset")
        if trace_held is not None and (trace_held or forwarded):
            self._linux_rdaccess_trace(
                "reset", reason=getattr(self, "_lrd_reset_reason", None),
                held=trace_held,
                failed=sorted(self._linux_rdaccess_trace_label(k[0], k[1]) or "char"
                              for k in forwarded))
        self._lrd_reset_reason = None
        self._lrd_down = set()
        self._lrd_nvda_down = False
        self._lrd_swapped = set()
        self._lrd_nvda_key = None
        self._lrd_caps_pending = None
        self._lrd_caps_used = False
        self._lrd_insert_pending = None
        self._lrd_insert_used = False
        self._lrd_bypass_next = False
        bypass_request = getattr(self, "_lrd_bypass_request", None)
        self._lrd_bypass_request = None
        self._lrd_bypass_keys = {}
        _lrd_clear_bypass_keys()
        if bypass_request is not None:
            _lrd_schedule_bypass_cleanup(bypass_request)
        self._lrd_navigation_marker = None
        self._lrd_generation = getattr(self, "_lrd_generation", 0) + 1
        self._lrd_local_stop_pending = False
        marker = globals().get("_LRD_D")
        if isinstance(marker, dict):
            _lrd_clear_navigation_markers(marker)
            marker["swapped"] = False
            marker["modifiers"] = 0
            marker["code"] = None
        table = globals().get("_LRD_T")
        if isinstance(table, dict):
            _lrd_clear_navigation_markers(table)
            table["held"] = {}
        table_edge = globals().get("_LRD_TABLE_EDGE")
        if isinstance(table_edge, dict):
            _lrd_clear_navigation_markers(table_edge)
            table_edge["held"] = {}
        browse_unsupported = globals().get("_LRD_BROWSE_UNSUPPORTED")
        if isinstance(browse_unsupported, dict):
            _lrd_clear_navigation_markers(browse_unsupported)
            browse_unsupported["held"] = {}
        nvda_browse = globals().get("_LRD_NVDA_BROWSE")
        if isinstance(nvda_browse, dict):
            _lrd_clear_navigation_markers(nvda_browse)
            nvda_browse["held"] = {}

    def _linux_rdaccess_mark_nvda_modifier_used(self):
        """Keep deferred NVDA modifiers out of Linux for a consumed command."""
        if getattr(self, "_lrd_caps_pending", None) is not None:
            self._lrd_caps_used = True
        if getattr(self, "_lrd_insert_pending", None) is not None:
            self._lrd_insert_used = True

    def _linux_rdaccess_flush_pending_caps(self):
        """Forward deferred CapsLock; report whether ordinary input can continue."""
        pending = getattr(self, "_lrd_caps_pending", None)
        if pending is None:
            return True
        _held, payload = pending
        self._lrd_caps_pending = None
        self._lrd_caps_used = False
        try:
            return self._linux_rdaccess_forward_key(**payload) is not False
        except Exception:
            log.error("linux-rdaccess: failed to forward deferred CapsLock")
            return False

    def _linux_rdaccess_flush_pending_insert(self):
        """Forward deferred Insert; report whether ordinary input can continue."""
        pending = getattr(self, "_lrd_insert_pending", None)
        if pending is None:
            return True
        _held, payload = pending
        self._lrd_insert_pending = None
        self._lrd_insert_used = False
        try:
            return self._linux_rdaccess_forward_key(**payload) is not False
        except Exception:
            log.error("linux-rdaccess: failed to forward deferred Insert")
            return False

    def _linux_rdaccess_flush_pending_nvda_modifiers(self):
        """Replay unused deferred modifiers; fail closed for a rejected Insert."""
        # CapsLock is a toggle, not a held application-chord modifier. Preserve
        # the established behavior where a failed CapsLock toggle does not eat
        # the following typing key. Insert must succeed before Insert+key can
        # safely be degraded to ordinary Linux input.
        if not getattr(self, "_lrd_caps_used", False):
            self._linux_rdaccess_flush_pending_caps()
        if not getattr(self, "_lrd_insert_used", False):
            return self._linux_rdaccess_flush_pending_insert()
        return True

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
            self._lrd_reset_reason = "state_change"
            self._linux_rdaccess_reset_keys()
            self._lrd_state = state
            self._linux_rdaccess_trace(
                "session", controlling=bool(state[0]), connected=state[1],
                role=state[2] if state[2] in ("master", "slave") else None)

    def _linux_rdaccess_filter_key(self, pressed, vk_code, extended, modifiers,
                                   key_name=None, scan_code=None):
        """Decide one remote key; trace the metadata of the decision if enabled."""
        # NVDA Remote sends boolean flags and Windows integer key metadata.
        # Do not let malformed flags turn a key-up into a press or change the
        # identity of a deferred modifier before its legitimate release.
        flag = lambda value: type(value) is bool or (type(value) is int and value in (0, 1))
        if (not flag(pressed)
                or (extended is not None and not flag(extended))
                or (vk_code is not None and (type(vk_code) is not int or not 0 <= vk_code <= 255))
                or (scan_code is not None and (type(scan_code) is not int
                                               or not 0 <= scan_code <= 0xFFFFFFFF))
                or (key_name is not None and not isinstance(key_name, str))
                or (vk_code is None
                    and (not isinstance(key_name, str) or not key_name))):
            return True
        if not self._linux_rdaccess_trace_enabled():
            return self._linux_rdaccess_filter_key_impl(
                pressed, vk_code, extended, modifiers, key_name, scan_code)
        self._linux_rdaccess_sync_state()
        held = self._linux_rdaccess_key_identity(vk_code, extended, key_name)
        pressed = bool(pressed)
        before_swapped = held in getattr(self, "_lrd_swapped", set())
        before_nvda = bool(getattr(self, "_lrd_nvda_down", False))
        repeat = pressed and held in getattr(self, "_lrd_down", set())
        scheduled = getattr(self, "_lrd_trace_scheduled", 0)
        self._lrd_trace_why = None
        outcome = "raised"
        result = None
        try:
            result = self._linux_rdaccess_filter_key_impl(
                pressed, vk_code, extended, modifiers, key_name, scan_code)
            outcome = None
            return result
        finally:
            try:
                self._linux_rdaccess_trace_key(
                    outcome, result, pressed, repeat, vk_code, extended,
                    scan_code, held, before_swapped, before_nvda,
                    getattr(self, "_lrd_trace_scheduled", 0) > scheduled)
            except Exception:
                pass

    def _linux_rdaccess_trace_key(self, outcome, result, pressed, repeat, vk_code,
                                  extended, scan_code, held, before_swapped,
                                  before_nvda, scheduled):
        why = getattr(self, "_lrd_trace_why", None)
        if outcome is not None:
            disposition = outcome
        elif not result:
            disposition = "forwarded"
        elif vk_code == 0x14:
            disposition = "caps_deferred"
        elif vk_code == 0x2D and getattr(self, "_lrd_insert_pending", None) is not None:
            disposition = "insert_deferred"
        elif before_swapped:
            disposition = "owned_press" if pressed else "owned_release"
        elif why == "pass_next":
            disposition = "pass_next"
        elif why and why.startswith("translate:"):
            disposition = "translated"
        elif why:
            disposition = "suppressed"
        elif scheduled:
            disposition = "translated"
        else:
            disposition = "suppressed"
        label = self._linux_rdaccess_trace_label(vk_code, extended)
        record = {
            "press": "repeat" if repeat else ("down" if pressed else "up"),
            "disp": disposition,
            "why": why,
            "own": self._linux_rdaccess_trace_ownership(),
        }
        # A character key is a possible password byte: identify it only when
        # it belongs to a fixed non-character vocabulary or an NVDA command.
        if label is not None or before_nvda:
            record["id"] = label
            record["vk"] = vk_code if isinstance(vk_code, int) else None
            record["ext"] = bool(extended)
            record["scan"] = scan_code if isinstance(scan_code, int) else None
        else:
            record["id"] = "char"
        claim = getattr(self, "_lrd_navigation_marker", None)
        if claim is not None and claim[0] in self._LRD_TRACE_CLAIMS:
            kind, named = self._LRD_TRACE_CLAIMS[claim[0]]
            record["claim"] = kind
            if named:
                record["claim_cmd"] = claim[1]
        self._linux_rdaccess_trace("key", **record)

    def _linux_rdaccess_filter_key_impl(self, pressed, vk_code, extended, modifiers,
                                        key_name=None, scan_code=None):
        """Return True when the event was fully handled here."""
        self._linux_rdaccess_sync_state()
        self._lrd_navigation_marker = None
        nvda_layout = self._linux_rdaccess_nvda_layout()
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
            if pressed and not repeat and vk_code in self._LRD_NVDA_VKS:
                if vk_code != 0x14 and getattr(self, "_lrd_caps_pending", None) is not None:
                    self._lrd_caps_used = True
                if vk_code != 0x2D and getattr(self, "_lrd_insert_pending", None) is not None:
                    self._lrd_insert_used = True

        # Only consecutive clock gestures count as a double press. Modifier
        # releases between taps are normal; another action starts a new count.
        if pressed and not repeat and vk_code not in self._LRD_MODIFIER_VKS:
            clock = (vk_code == 0x7B and self._lrd_nvda_down
                     and not any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down))
            if not clock:
                self._lrd_last_clock_press = None

        # Insert is also an NVDA modifier. Forwarding it immediately makes
        # consumed NVDA commands leak a standalone Insert press into Linux
        # applications (for example toggling overwrite mode in an editor).
        # Defer it just like CapsLock, then replay it only for ordinary input.
        if vk_code == 0x2D:
            pending = getattr(self, "_lrd_insert_pending", None)
            if pressed:
                if not repeat and pending is not None and pending[0] != held:
                    # Dedicated Insert and numpad Insert are distinct physical
                    # NVDA modifiers but share VK_INSERT. Do not overwrite the
                    # first deferred press: own the additional modifier until
                    # its release and mark the original as modifier-used.
                    self._lrd_insert_used = True
                    self._lrd_swapped.add(held)
                    return True
                if not repeat:
                    self._lrd_insert_pending = (
                        held,
                        {
                            "key_name": key_name,
                            "pressed": True,
                            "modifiers": modifiers,
                            "vk_code": vk_code,
                            "scan_code": scan_code,
                            "extended": extended,
                        },
                    )
                    self._lrd_insert_used = any(
                        k != held and k[0] in self._LRD_NVDA_VKS
                        for k in self._lrd_down
                    )
                return True
            if pending is not None and pending[0] == held:
                used = bool(getattr(self, "_lrd_insert_used", False))
                if used:
                    self._lrd_insert_pending = None
                    self._lrd_insert_used = False
                    return True
                self._linux_rdaccess_flush_pending_insert()
                return False

        # CapsLock can be configured as the NVDA modifier. Forwarding its press
        # immediately toggles Linux Caps Lock before we know whether this is a
        # translated NVDA command, so defer it until the gesture is known.
        if vk_code == 0x14:
            pending = getattr(self, "_lrd_caps_pending", None)
            if pressed:
                if not repeat:
                    self._lrd_caps_pending = (
                        held,
                        {
                            "key_name": key_name,
                            "pressed": True,
                            "modifiers": modifiers,
                            "vk_code": vk_code,
                            "scan_code": scan_code,
                            "extended": extended,
                        },
                    )
                    self._lrd_caps_used = any(
                        k != held and k[0] in self._LRD_NVDA_VKS
                        for k in self._lrd_down
                    )
                return True
            if pending is not None and pending[0] == held:
                used = bool(getattr(self, "_lrd_caps_used", False))
                if used:
                    self._lrd_caps_pending = None
                    self._lrd_caps_used = False
                    return True
                self._linux_rdaccess_flush_pending_caps()
                return False

        # Lock keys toggle state on key-down. Remote auto-repeat must not
        # re-toggle Linux several times for one physical press. Preserve
        # ordinary repeat behavior and consume only verified lock-toggle repeats.
        if repeat and vk_code in self._LRD_REPEAT_TOGGLE_VKS:
            self._lrd_trace_why = "lock_repeat"
            return True

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
            else:
                self._linux_rdaccess_trace("speech", what="cancel_throttled")

        # Consumed presses retain ownership of their repeat/release even if
        # pass-next has just been armed (notably the F2 which armed it).
        if held in self._lrd_swapped:
            if not pressed:
                self._lrd_swapped.discard(held)
            return True

        # One delivered gesture owns its repeats and release. Receive-side
        # ownership is independent of when Orca processes its native flag.
        bypass_keys = getattr(self, "_lrd_bypass_keys", {})
        request = bypass_keys.get(held)
        if request is not None:
            self._lrd_trace_why = "pass_next"
            result = self._linux_rdaccess_forward_bypass_key(
                request, held, pressed, key_name, modifiers, vk_code, scan_code, extended)
            if not pressed and result is not False:
                bypass_keys.pop(held, None)
            return True
        request = getattr(self, "_lrd_bypass_request", None)
        native_bypass = False
        try:
            from orca import orca_state as _state
            native_bypass = bool(getattr(_state, "bypassNextCommand", False))
        except ImportError:
            pass
        if request is not None and request["used"] and (
                not native_bypass or request.get("complete", False)):
            self._lrd_bypass_request = request = None
        elif (request is not None and request["used"] and not request["external"]
              and _LRD_BYPASS["owner"] is not request):
            # The owned flag has completed; a newly armed local Orca bypass
            # must not be mistaken for the old remote request.
            self._lrd_bypass_request = request = None
        # A flag which our used request has yet to clear does not grant a
        # second remote gesture. A local/native request retains its own path.
        if native_bypass and request is None:
            request = self._lrd_bypass_request = {
                "generation": self._lrd_generation, "used": False,
                "external": True, "codes": {},
            }
        bypass = (request is not None and not request["used"]
                  and (getattr(self, "_lrd_bypass_next", False) or native_bypass))
        if bypass:
            if pressed and vk_code not in self._LRD_MODIFIER_VKS:
                request["used"] = True
                self._lrd_trace_why = "pass_next"
                self._lrd_bypass_next = False
                if not self._linux_rdaccess_flush_pending_nvda_modifiers():
                    # A failed deferred Insert must not turn Insert+key into a
                    # plain bypassed key. Keep the bypass request available for
                    # the next complete gesture and own this key's release.
                    request["used"] = False
                    if not request.get("external", False):
                        self._lrd_bypass_next = True
                    self._lrd_trace_why = "deferred_modifier_rejected"
                    self._lrd_swapped.add(held)
                    return True
                result = self._linux_rdaccess_forward_bypass_key(
                    request, held, pressed, key_name, modifiers, vk_code, scan_code, extended)
                if result is False:
                    request["used"] = False
                    self._lrd_bypass_next = True
                else:
                    if not hasattr(self, "_lrd_bypass_keys"):
                        self._lrd_bypass_keys = {}
                    self._lrd_bypass_keys[held] = request
                return True
            return False

        # NVDA reports the focused object's shortcut independently of review.
        # Orca exposes the exact shortcut utility and speech/braille presenter.
        if pressed and not repeat:
            shift = any(k[0] in self._LRD_SHIFT_VKS for k in self._lrd_down)
            ctrl = any(k[0] in self._LRD_CTRL_VKS for k in self._lrd_down)
            alt_win = any(k[0] in (0x12, 0xA4, 0xA5, 0x5B, 0x5C)
                          for k in self._lrd_down)
            accelerator = (shift and not alt_win and (
                (vk_code == 0x28 and not bool(extended) and scan_code == 0x50
                 and not ctrl and not self._lrd_nvda_down)
                or (nvda_layout == "laptop" and self._lrd_nvda_down
                    and ctrl and vk_code == 0xBE and not bool(extended))))
            if accelerator:
                self._lrd_trace_why = "translate:focus_accelerator"
                self._lrd_swapped.add(held)
                self._linux_rdaccess_mark_nvda_modifier_used()
                self._linux_rdaccess_run_main(
                    lambda: self._linux_rdaccess_script_call("presentFocusAccelerator"))
                return True

        # NVDA's plain keypad mouse buttons click the current pointer. Orca's
        # same keys click a flat-review/focused item, which can be elsewhere.
        # Plain NumpadPlus reads NVDA's review cursor, but Orca's first KP_Add
        # invokes caret Say All. Neither operation has a proven equivalent.
        # Own these exact gestures until an equivalent operation is supported.
        if (pressed and not repeat and not self._lrd_nvda_down
                and not any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down)
                and ((vk_code == 0x6F and bool(extended))
                     or (vk_code in (0x6A, 0x6B) and not bool(extended)))):
            self._lrd_trace_why = ("unsupported_review_say_all" if vk_code == 0x6B
                                   else "unsupported_pointer_click")
            self._lrd_swapped.add(held)
            return True

        # NVDA assigns several plain Shift+numpad gestures to review
        # boundaries and mouse-lock toggles.
        # Orca 42 either has no exact equivalent or gives the same physical
        # key a different meaning. Consume only scan-proven/unambiguous forms
        # instead of leaking an unrelated click or selection into Linux.
        if (
            pressed
            and not repeat
            and self._linux_rdaccess_plain_shift_numpad_unimplemented(
                vk_code, extended, scan_code)
        ):
            self._lrd_trace_why = "unsupported_shift_numpad"
            self._lrd_swapped.add(held)
            return True

        # NVDA and Orca assign different browse-mode meanings to A/M/N/O/W.
        # Mark only a remote plain/Shift letter; the Orca-side hook consumes it
        # only when Orca itself says structural navigation is active.
        if (
            pressed
            and vk_code in (0x41, 0x46, 0x4D, 0x4E, 0x4F, 0x57, 0x37, 0x38, 0x39)
            and not self._lrd_nvda_down
            and not any(
                k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
                for k in self._lrd_down
            )
        ):
            self._lrd_navigation_marker = (
                "_LRD_BROWSE_UNSUPPORTED",
                {0x41: "a", 0x46: "f", 0x4D: "m", 0x4E: "n",
                 0x4F: "o", 0x57: "w", 0x37: "7", 0x38: "8", 0x39: "9"}[vk_code],
                held,
            )

        # Remember that a plain (or Shift) D came from the remote session, so the
        # Orca-side hook below can turn it into the landmark key in browse mode
        # only. Nothing is translated here; the key is forwarded unchanged.
        if pressed and vk_code == 0x44 and not self._lrd_nvda_down and not any(
                k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in (0x10, 0xA0, 0xA1)
                for k in self._lrd_down):
            self._lrd_navigation_marker = ("_LRD_D", "d", held)

        # NVDA's table commands are Ctrl+Alt+Arrow. Mark only an extended arrow
        # with Ctrl and Alt held and no Shift/Win/NVDA key; the Orca-side hook
        # below decides, per key and only in browse mode, whether to translate.
        # The key itself is forwarded unchanged.
        if (
            pressed
            and bool(extended)
            and vk_code in (0x25, 0x26, 0x27, 0x28)
            and not self._lrd_nvda_down
            and any(k[0] in self._LRD_CTRL_VKS for k in self._lrd_down)
            and any(k[0] in (0x12, 0xA4, 0xA5) for k in self._lrd_down)
            and not any(k[0] in self._LRD_SHIFT_VKS + (0x5B, 0x5C)
                        for k in self._lrd_down)
        ):
            self._lrd_navigation_marker = (
                "_LRD_T", {0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down"}[vk_code], held)

        # NVDA and Orca 42 have the same current-selection command but bind
        # it differently by keyboard layout. Call Orca directly so CapsLock-
        # as-NVDA and Insert-as-NVDA behave identically.
        if pressed and self._lrd_nvda_down and not repeat:
            shifts = any(k[0] in self._LRD_SHIFT_VKS for k in self._lrd_down)
            other = any(
                k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
                for k in self._lrd_down
            )
            selection = (
                nvda_layout == "desktop"
                and vk_code == 0x26 and bool(extended) and shifts and not other
            ) or (
                nvda_layout == "laptop"
                and vk_code == 0x53 and not bool(extended) and shifts and not other
            )
            if selection:
                self._lrd_trace_why = "translate:current_selection"
                self._lrd_swapped.add(held)
                self._linux_rdaccess_mark_nvda_modifier_used()
                self._linux_rdaccess_run_main(
                    lambda: self._linux_rdaccess_script_call("whereAmISelection"))
                return True

        if (
            pressed
            and self._lrd_nvda_down
            and not repeat
            and self._linux_rdaccess_known_unimplemented(vk_code, extended)
        ):
            self._lrd_trace_why = "unsupported_nvda_command"
            self._lrd_swapped.add(held)
            self._linux_rdaccess_mark_nvda_modifier_used()
            return True

        # NVDA table edge commands preserve the current column/row. Orca 42
        # has only first/last *table cell* keybindings, so publish a remote
        # provenance claim and let the Orca-side hook use goCell coordinates.
        if (
            pressed
            and bool(extended)
            and vk_code in (0x21, 0x22, 0x23, 0x24)
            and not self._lrd_nvda_down
            and any(k[0] in self._LRD_CTRL_VKS for k in self._lrd_down)
            and any(k[0] in (0x12, 0xA4, 0xA5) for k in self._lrd_down)
            and not any(k[0] in self._LRD_SHIFT_VKS + (0x5B, 0x5C)
                        for k in self._lrd_down)
        ):
            self._lrd_navigation_marker = (
                "_LRD_TABLE_EDGE",
                {0x21: "firstRow", 0x22: "lastRow",
                 0x24: "firstColumn", 0x23: "lastColumn"}[vk_code],
                held,
            )

        # NVDA browse mode assigns Alt+Up/Down to collapse/expand the
        # control at the virtual caret. Orca 42 has no equivalent native API,
        # so mark only the exact remote gesture and decide on Orca's main
        # thread whether browse mode is active.
        if (
            pressed
            and bool(extended)
            and vk_code in (0x26, 0x28)
            and not self._lrd_nvda_down
            and any(k[0] in (0x12, 0xA4, 0xA5) for k in self._lrd_down)
            and not any(
                k[0] in self._LRD_SHIFT_VKS + self._LRD_CTRL_VKS + (0x5B, 0x5C)
                for k in self._lrd_down
            )
        ):
            self._lrd_navigation_marker = (
                "_LRD_NVDA_BROWSE",
                "collapseExpandUp" if vk_code == 0x26 else "collapseExpandDown",
                held,
            )

        # These are NVDA browse-mode commands, not global commands. Defer
        # their context decision to Orca's main-thread keyboard hook. Mark
        # CapsLock-as-NVDA as used so an eventual focus-mode pass-through never
        # toggles the Linux lock merely because the NVDA modifier was CapsLock.
        if pressed and self._lrd_nvda_down and not repeat:
            shifts = [k for k in self._lrd_down if k[0] in self._LRD_SHIFT_VKS]
            ctrl = any(k[0] in self._LRD_CTRL_VKS for k in self._lrd_down)
            alt_win = any(
                k[0] in (0x12, 0xA4, 0xA5, 0x5B, 0x5C)
                for k in self._lrd_down
            )
            browse_action = None
            if vk_code == 0x46 and ctrl and not shifts and not alt_win:   # NVDA+Ctrl+F
                browse_action = "find"
            elif vk_code == 0x56 and not shifts and not ctrl and not alt_win:  # NVDA+V
                browse_action = "layout"
            elif vk_code == 0x72 and not ctrl and not alt_win:            # NVDA+F3/Shift+F3
                browse_action = "findPrevious" if shifts else "findNext"
            elif vk_code == 0x79 and shifts and not ctrl and not alt_win: # NVDA+Shift+F10
                browse_action = "nativeSelection"
            if browse_action is not None:
                self._lrd_navigation_marker = ("_LRD_NVDA_BROWSE", browse_action, held)
                self._linux_rdaccess_mark_nvda_modifier_used()
                return False

        # Some NVDA commands have no proven Orca-42 equivalent but collide
        # with unrelated Orca modifier bindings. Consume those exact remote
        # gestures rather than navigating bookmarks or changing Orca speech
        # state behind the user's back.
        if pressed and self._lrd_nvda_down and not repeat:
            shifts = [k for k in self._lrd_down if k[0] in self._LRD_SHIFT_VKS]
            other = [
                k for k in self._lrd_down
                if k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
            ]
            ctrl = any(k[0] in self._LRD_CTRL_VKS for k in self._lrd_down)
            alt_win = any(k[0] in (0x12, 0xA4, 0xA5, 0x5B, 0x5C)
                          for k in self._lrd_down)
            collision = (
                (vk_code in (0x32, 0x33, 0x34, 0x35, 0x36, 0x37)
                 and not shifts and not other)
                or (vk_code == 0x42 and not other)
                or (vk_code in (0x46, 0x4B, 0x53)
                    and not shifts and not other)
                or (vk_code in (
                        0x47, 0x53, 0x56, 0x41, 0x55, 0x4B, 0x4D, 0x4F,
                        0x42, 0x44, 0x57, 0x43, 0x52, 0x5A, 0x54, 0x50)
                    and ctrl and not shifts and not alt_win)
            )
            if collision:
                self._lrd_trace_why = "nvda_orca_collision"
                self._lrd_swapped.add(held)
                self._linux_rdaccess_mark_nvda_modifier_used()
                return True

        if (
            pressed
            and self._lrd_nvda_down
            and not repeat
            and nvda_layout == "desktop"
            and self._linux_rdaccess_desktop_unimplemented(vk_code, extended, scan_code)
        ):
            self._lrd_trace_why = "unsupported_object_review"
            self._lrd_swapped.add(held)
            self._linux_rdaccess_mark_nvda_modifier_used()
            return True

        if (
            pressed
            and self._lrd_nvda_down
            and not repeat
            and nvda_layout == "laptop"
            and self._linux_rdaccess_laptop_unimplemented(vk_code, extended, scan_code)
        ):
            self._lrd_trace_why = "unsupported_object_review"
            self._lrd_swapped.add(held)
            self._linux_rdaccess_mark_nvda_modifier_used()
            return True

        # NVDA's desktop and laptop layouts reuse several physical gestures
        # for different commands. Select the Windows layout explicitly rather
        # than applying desktop semantics universally.
        if pressed and self._lrd_nvda_down and not repeat and nvda_layout == "laptop":
            shifts = [k for k in self._lrd_down if k[0] in self._LRD_SHIFT_VKS]
            other = [
                k for k in self._lrd_down
                if k[0] in self._LRD_OTHER_MOD_VKS and k[0] not in self._LRD_SHIFT_VKS
            ]
            action = None
            if vk_code == 0x41 and not shifts and not other:          # NVDA+A
                action = "sayAll"
            elif vk_code == 0x4C and not shifts and not other:        # NVDA+L
                action = "presentCurrentLine"
            elif vk_code == 0x23 and bool(extended) and shifts and not other:
                action = "presentStatusBar"                            # NVDA+Shift+End
            elif (
                bool(extended)
                and vk_code in (0x23, 0x26, 0x28)
                and not shifts
                and not other
            ):
                # Laptop NVDA+End/Up/Down are review commands. Orca flat review
                # is not proven equivalent to NVDA review, so consume these
                # instead of running the conflicting desktop command.
                action = "unsupported_review"

            if action is not None:
                self._lrd_trace_why = (
                    "unsupported_object_review" if action == "unsupported_review"
                    else "translate:" + action)
                self._lrd_swapped.add(held)
                self._linux_rdaccess_mark_nvda_modifier_used()
                if action != "unsupported_review":
                    self._linux_rdaccess_run_main(
                        lambda action=action: self._linux_rdaccess_script_call(action))
                return True

        # Desktop NVDA+Down has an exact Orca Say All method. Only the extended
        # navigation Down key is NVDA's gesture; the non-extended VK form is
        # the numeric keypad key and must continue to pass through unchanged.
        if (
            pressed
            and self._lrd_nvda_down
            and nvda_layout == "desktop"
            and not repeat
            and vk_code == 0x28
            and bool(extended)
            and not any(k[0] in self._LRD_SHIFT_VKS for k in self._lrd_down)
            and not any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down)
        ):
            self._lrd_trace_why = "translate:sayAll"
            self._lrd_swapped.add(held)
            self._linux_rdaccess_mark_nvda_modifier_used()
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call("sayAll"))
            return True

        # NVDA+Ctrl+Space moves out of an embedded document in NVDA.
        # Orca 42 instead binds Orca+Ctrl+Space to application preferences.
        # No equivalent Orca-42 API has been proven, so consume the exact NVDA
        # gesture rather than opening a preferences dialog or flushing a
        # deferred CapsLock modifier into the X server.
        if (
            pressed
            and self._lrd_nvda_down
            and not repeat
            and vk_code == 0x20
            and any(k[0] in self._LRD_CTRL_VKS for k in self._lrd_down)
            and not any(
                k[0] in self._LRD_SHIFT_VKS or k[0] in (0x12, 0xA4, 0xA5, 0x5B, 0x5C)
                for k in self._lrd_down
            )
        ):
            self._lrd_trace_why = "unsupported_exit_embedded"
            self._lrd_swapped.add(held)
            self._linux_rdaccess_mark_nvda_modifier_used()
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
                self._lrd_trace_why = (
                    "translate:toggleStructuralNavigation" if shifts
                    else "translate:togglePresentationMode")
                self._lrd_swapped.add(held)
                self._linux_rdaccess_mark_nvda_modifier_used()
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
            if nvda_layout == "laptop" and action in ("status_bar", "current_line"):
                action = None
            if (
                action is not None
                and not any(k[0] in self._LRD_OTHER_MOD_VKS for k in self._lrd_down)
                and not (action in ("status_bar", "current_line") and not bool(extended))
            ):
                self._lrd_trace_why = "translate:" + action
                self._lrd_swapped.add(held)
                self._linux_rdaccess_mark_nvda_modifier_used()
                if action == "input_help":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("toggleInputHelp"))
                elif action == "punctuation":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call(
                            "cycleSpeakingPunctuationLevel"))
                elif action == "mouse_review":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call(
                            "toggleMouseReview"))
                elif action == "progress_output":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call(
                            "cycleProgressBarOutput"))
                elif action == "elements_list":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_show_elements_list(modifiers))
                elif action == "pass_next":
                    self._linux_rdaccess_arm_bypass()
                elif action == "where_am_i":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("whereAmI"))
                elif action == "title":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("presentTitle"))
                elif action == "status_bar":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("presentStatusBar"))
                elif action == "current_line":
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("presentCurrentLine"))
                elif action == "date_time":
                    # Resolve the tap count on receipt; queued callbacks must
                    # retain each gesture's time/date choice independently.
                    method = self._linux_rdaccess_clock_command()
                    self._linux_rdaccess_run_main(
                        lambda method=method: self._linux_rdaccess_script_call(method))
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
                    and (
                        getattr(self, "_lrd_caps_pending", None) is not None
                        or getattr(self, "_lrd_insert_pending", None) is not None
                    )
                    and not self._linux_rdaccess_flush_pending_nvda_modifiers()
                ):
                    # Do not execute the application key without the modifier
                    # the user physically held. Own its release so a rejected
                    # deferred press cannot degrade Insert+key into plain key.
                    self._lrd_trace_why = "deferred_modifier_rejected"
                    self._lrd_swapped.add(held)
                    return True
                return False
            need_ext, name, target_vk, drop, count, drop_shift = chord
            nvda = self._lrd_nvda_key
            if drop and (nvda is None or nvda[0] == 0x14):
                # Re-pressing CapsLock would toggle the lock state.
                return False
            self._lrd_swapped.add(held)
            self._linux_rdaccess_mark_nvda_modifier_used()
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

    def _linux_rdaccess_arm_bypass(self):
        old = getattr(self, "_lrd_bypass_request", None)
        if old is not None:
            _lrd_schedule_bypass_cleanup(old)
        request = self._lrd_bypass_request = {
            "generation": self._lrd_generation, "used": False,
            "external": False, "codes": {},
        }
        self._lrd_bypass_next = True
        if self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_activate_bypass(request)) is False:
            if self._lrd_bypass_request is request:
                self._lrd_bypass_request = None
                self._lrd_bypass_next = False

    def _linux_rdaccess_activate_bypass(self, request=None):
        request = request or getattr(self, "_lrd_bypass_request", None)
        if (request is None or self._lrd_bypass_request is not request
                or request["used"] or request["generation"] != self._lrd_generation):
            return False
        owner = _LRD_BYPASS["owner"]
        if owner is not None and owner is not request:
            _lrd_cleanup_owned_bypass(owner)
        try:
            from orca import orca_state as _state
            if getattr(_state, "bypassNextCommand", False):
                request["external"] = True
                return True
        except ImportError:
            pass
        _LRD_BYPASS["owner"] = request
        if self._linux_rdaccess_script_call("bypassNextCommand") is False:
            self._lrd_bypass_next = False
            if self._lrd_bypass_request is request:
                self._lrd_bypass_request = None
            _lrd_cleanup_owned_bypass(request)
            return False
        # Injection can race this callback while Orca presents its message.
        # It must not leave a native flag armed after the gesture was delivered.
        if request["used"] or self._lrd_bypass_request is not request:
            _lrd_cleanup_owned_bypass(request)
        return True

    def _linux_rdaccess_forward_bypass_key(self, request, held, pressed,
                                          key_name, modifiers, vk_code,
                                          scan_code, extended):
        payload = dict(getattr(self, "_lrd_forwarded", {}).get(held, {
            "key_name": key_name, "modifiers": modifiers, "vk_code": vk_code,
            "scan_code": scan_code, "extended": extended,
        }), pressed=pressed)
        try:
            name = self._linux_rdaccess_bypass_key_name(payload)
        except Exception:
            log.error("linux-rdaccess: bypass key resolution failed")
            return False
        previous = getattr(self, "_lrd_bypass_dispatch", None)
        previous_name = getattr(self, "_lrd_bypass_name", None)
        self._lrd_bypass_dispatch = request
        self._lrd_bypass_name = name
        try:
            return self._linux_rdaccess_forward_key(**payload)
        except Exception:
            return False
        finally:
            self._lrd_bypass_dispatch = previous
            self._lrd_bypass_name = previous_name

    def _linux_rdaccess_bypass_key_name(self, payload):
        resolver = getattr(self.local_machine, "_resolve_key", None)
        if callable(resolver):
            return resolver(payload.get("key_name"), payload.get("vk_code"),
                            payload.get("extended"))
        name = payload.get("key_name")
        vk_code = payload.get("vk_code")
        # Lightweight test/legacy machines need not expose the resolver.
        if not name and isinstance(vk_code, int):
            if 0x41 <= vk_code <= 0x5A:
                name = chr(vk_code).lower()
            elif 0x30 <= vk_code <= 0x39:
                name = chr(vk_code)
            elif 0x70 <= vk_code <= 0x87:
                name = "F%d" % (vk_code - 0x6F)
            else:
                name = {0x20: "space", 0x09: "Tab", 0x0D: "Return",
                        0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down"}.get(vk_code)
        return name

    @classmethod
    def _linux_rdaccess_parse_braille_key(cls, name):
        """Return (modifier names, key name) for an allowlisted kb: gesture."""
        if not isinstance(name, str) or not name.startswith("kb:"):
            return None
        parts = name[3:].lower().split("+")
        key = next((canonical for canonical in cls._LRD_BRAILLE_KEYS
                    if canonical.lower() == parts[-1]), None)
        mods = parts[:-1]
        if key is None or len(set(mods)) != len(mods):
            return None
        if any(mod not in cls._LRD_BRAILLE_MODIFIERS for mod in mods):
            return None
        return tuple(mods), key

    def _linux_rdaccess_send_braille_key(self, name):
        """Inject one display navigation key, borrowing held modifiers."""
        parsed = self._linux_rdaccess_parse_braille_key(name)
        if parsed is None:
            return
        mods, key = parsed
        x_name, vk, extended = self._LRD_BRAILLE_KEYS[key]
        forwarded = getattr(self, "_lrd_forwarded", {})
        # A synthetic release must not release a key the controller holds.
        if (vk, extended) in forwarded:
            return
        send = self._linux_rdaccess_forward_key
        pressed_modifiers = []
        try:
            for mod in mods:
                mod_name, mod_vk = self._LRD_BRAILLE_MODIFIERS[mod]
                generic_vk = {0xA0: 0x10, 0xA2: 0x11, 0xA4: 0x12}[mod_vk]
                if any(held_vk in (mod_vk, generic_vk) and not held_ext
                       for held_vk, held_ext in getattr(self, "_lrd_forwarded", {})):
                    continue
                if send(key_name=mod_name, pressed=True, modifiers=None,
                        vk_code=mod_vk, scan_code=0, extended=False) is False:
                    return
                pressed_modifiers.append((mod_name, mod_vk))
            for down in (True, False):
                if send(key_name=x_name, pressed=down, modifiers=None,
                        vk_code=vk, scan_code=0, extended=extended) is False:
                    return
        finally:
            if (vk, extended) in getattr(self, "_lrd_forwarded", {}):
                try:
                    send(key_name=x_name, pressed=False, modifiers=None,
                         vk_code=vk, scan_code=0, extended=extended)
                except Exception:
                    log.error("linux-rdaccess: failed to release braille key")
            for mod_name, mod_vk in reversed(pressed_modifiers):
                identity = (mod_vk, False)
                for _attempt in range(2):
                    if identity not in getattr(self, "_lrd_forwarded", {}):
                        break
                    try:
                        send(key_name=mod_name, pressed=False, modifiers=None,
                             vk_code=mod_vk, scan_code=0, extended=False)
                    except Exception:
                        pass
                if identity in getattr(self, "_lrd_forwarded", {}):
                    log.error("linux-rdaccess: failed to release braille modifier")

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
        # A display key bound to a non-character emulated key is a command, even
        # when it is a space+dots chord, so it is decided before the typed-input
        # test below. Nothing about the id/identifiers is recorded for it.
        if (script and tuple(script[:2]) == ("globalCommands", "GlobalCommands")
                and self._linux_rdaccess_parse_braille_key(name) is not None):
            mods, key = self._linux_rdaccess_parse_braille_key(name)
            canonical = "kb:" + "+".join(mods + (key,))
            return "key", {"action": "key", "scriptPath": ["globalCommands", "GlobalCommands", canonical]}

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
        self._lrd_trace_scheduled = ticket = getattr(self, "_lrd_trace_scheduled", 0) + 1
        self._linux_rdaccess_trace("main", ticket=ticket, state="scheduled")

        def invoke():
            self._linux_rdaccess_sync_state()
            # A disconnected controller's queued command must not operate on
            # the new session/focus, or cancel speech started after handoff.
            if generation == getattr(self, "_lrd_generation", 0):
                self._linux_rdaccess_trace(
                    "main", ticket=ticket, state="ran", sched_gen=generation)
                try:
                    func()
                except Exception:
                    log.error("linux-rdaccess: queued Orca operation failed")
            else:
                self._linux_rdaccess_trace(
                    "main", ticket=ticket, state="stale_skipped", sched_gen=generation)
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
        if action is not None:
            self._lrd_last_clock_press = None
        if self._linux_rdaccess_trace_enabled():
            # Canonical command names only; dots, space and driver ids are
            # never recorded, so braille keyboard input stays private.
            canonical = record.get("action") or record.get("redacted")
            emulated = None
            if action == "key":
                parsed = self._linux_rdaccess_parse_braille_key(
                    record["scriptPath"][2])
                emulated = {"mods": list(parsed[0]), "key": parsed[1]} if parsed else None
            self._linux_rdaccess_trace(
                "braille", cls=action or "unclassified", record=canonical,
                emulated=emulated)
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
        elif action == "key":
            self._linux_rdaccess_send_braille_key(record["scriptPath"][2])
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
                identity = (mod_vk, mod_ext)
                for _attempt in range(2):
                    if identity not in getattr(self, "_lrd_forwarded", {}):
                        break
                    try:
                        send(
                            key_name=name, pressed=False, modifiers=None,
                            vk_code=mod_vk, scan_code=0, extended=mod_ext)
                    except Exception:
                        pass
                if identity in getattr(self, "_lrd_forwarded", {}):
                    log.error(
                        "linux-rdaccess: failed to release structural-list modifier")

    def _linux_rdaccess_open_structural_list(self, key, modifiers):
        """Prefer Orca's native structural-list API; retain key fallback."""
        try:
            from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter as _adapter
        except ImportError:
            _adapter = None
        except Exception:
            log.error("linux-rdaccess: native structural list failed")
            return

        try:
            handler = getattr(_adapter, "show_structural_list", None)
            if callable(handler) and handler(key) is not None:
                return
        except Exception:
            # The native handler may have already opened or presented a list.
            log.error("linux-rdaccess: native structural list failed")
            return

        # Adapter unavailable or this Orca version does not expose the object.
        # Fall back to the verified Orca 42 Alt+Shift+letter binding.
        self._linux_rdaccess_send_structural_list(key, modifiers)

    def _linux_rdaccess_defer_structural_list(self, key, modifiers, generation,
                                             origin, window, document, request):
        """Wait for the chooser's origin to regain focus before native lookup.

        Orca's list GUI separately captures activeScript and activeWindow.
        Supplying the prior script while the chooser is active is insufficient.
        """
        attempts = 0
        deadline = __import__("time").monotonic() + 2.0

        def open_when_ready():
            nonlocal attempts
            self._linux_rdaccess_sync_state()
            if (generation != getattr(self, "_lrd_generation", 0)
                    or request is not getattr(self, "_lrd_elements_request", None)):
                return False
            if __import__("time").monotonic() >= deadline:
                log.error("linux-rdaccess: elements list focus wait expired")
                return False
            try:
                from orca import orca_state as state
                active = getattr(state, "activeScript", None)
                if active is None:
                    active = getattr(state, "active_script", None)
                active_window = getattr(state, "activeWindow", None)
                if active_window is None:
                    active_window = getattr(state, "active_window", None)
                if active is origin and active_window == window:
                    if document is not None:
                        getter = getattr(getattr(origin, "utilities", None), "documentFrame", None)
                        if not callable(getter) or getter() != document:
                            log.error("linux-rdaccess: elements list document changed")
                            return False
                    self._lrd_elements_request = None
                    self._linux_rdaccess_open_structural_list(key, modifiers)
                    return False
            except Exception:
                log.error("linux-rdaccess: elements list focus check failed")
                return False
            attempts += 1
            if attempts >= 80:
                log.error("linux-rdaccess: elements list focus was not restored")
                return False
            return True

        try:
            from gi.repository import GLib
        except ImportError:
            # An API-only install has no GTK nested loop to wait for.
            open_when_ready()
            return
        try:
            if not GLib.timeout_add(25, open_when_ready):
                log.error("linux-rdaccess: elements list scheduling failed")
        except Exception:
            log.error("linux-rdaccess: elements list scheduling failed")

    def _linux_rdaccess_show_elements_list(self, modifiers):
        # A second F7 inside Gtk.Dialog.run() must not capture the chooser as
        # its origin and later send a structural shortcut back into that dialog.
        if getattr(self, "_lrd_elements_dialog_active", False):
            return
        self._linux_rdaccess_sync_state()
        generation = getattr(self, "_lrd_generation", 0)
        request = object()
        self._lrd_elements_request = request
        origin = window = document = None
        try:
            from orca import orca_state as state
            origin = getattr(state, "activeScript", None)
            if origin is None:
                origin = getattr(state, "active_script", None)
            window = getattr(state, "activeWindow", None)
            if window is None:
                window = getattr(state, "active_window", None)
            getter = getattr(getattr(origin, "utilities", None), "documentFrame", None)
            if callable(getter):
                document = getter()
        except ImportError:
            pass
        except Exception:
            log.error("linux-rdaccess: elements list origin check failed")
            return

        def open_list(key):
            # Gtk.Dialog.run() processes a nested main loop. Recheck ownership
            # after it returns, just as for a queued top-level command.
            self._linux_rdaccess_sync_state()
            if (generation == getattr(self, "_lrd_generation", 0)
                    and request is getattr(self, "_lrd_elements_request", None)):
                if origin is not None:
                    self._linux_rdaccess_defer_structural_list(
                        key, modifiers, generation, origin, window, document, request)
                else:
                    self._linux_rdaccess_open_structural_list(key, modifiers)

        try:
            from linux_rdaccess_orca_adapter import show_elements_list as _show
        except ImportError:
            _show = None
        except Exception:
            log.error("linux-rdaccess: elements list failed")
            return

        try:
            self._lrd_elements_dialog_active = True
            try:
                result = _show(open_list) if _show is not None else None
            finally:
                self._lrd_elements_dialog_active = False
            if result is not None:
                # True: category selected and delegated to Orca.
                # False: the dialog was intentionally cancelled/Escaped.
                return
        except Exception:
            log.error("linux-rdaccess: elements list failed")
            return

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

        _trace = globals().get("_lrd_trace_write")
        if _trace is not None:
            try:
                _trace("script", method=method)
            except Exception:
                pass

        try:
            from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter as _adapter
        except ImportError:
            _adapter = None
        except Exception:
            log.error("linux-rdaccess: Orca adapter import failed: %s", method)
            return False

        try:
            handlers = {
                "toggleInputHelp": "toggle_input_help",
                "toggleMouseReview": "toggle_mouse_review",
                "cycleProgressBarOutput": "cycle_progress_bar_output",
                "panBrailleLeft": "pan_braille_left",
                "panBrailleRight": "pan_braille_right",
                "processRoutingKey": "route_braille",
                "goBrailleHome": "to_braille_focus",
                "bypassNextCommand": "bypass_next_command",
                "whereAmI": "where_am_i",
                "presentTitle": "present_title",
                "presentStatusBar": "present_status_bar",
                "presentCurrentLine": "present_current_line",
                "presentFocusAccelerator": "present_focus_accelerator",
                "presentTime": "present_time",
                "presentDate": "present_date",
                "togglePresentationMode": "toggle_presentation_mode",
                "toggleStructuralNavigation": "toggle_structural_navigation",
                "sayAll": "say_all",
                "showPreferences": "show_preferences",
                "presentLockState": "present_lock_state",
            }
            adapter_method = handlers.get(method)
            adapter_args = args
            if method == "processRoutingKey" and args:
                adapter_args = (args[0].event["argument"],)
            if adapter_method:
                handler = getattr(_adapter, adapter_method, None)
                result = handler(*adapter_args) if callable(handler) else None
            elif _adapter is not None:
                result = _adapter.call_script(method, *args, default_event=not args)
            else:
                result = None
            if result is not None:
                # Supported handlers can explicitly decline a command. Never
                # run them again through fallback after they performed work.
                return result is not False
            # None denotes an unsupported API; try the verified legacy API.
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
            if method == "cycleProgressBarOutput":
                try:
                    from orca import settings_manager as _settings_manager
                    manager = _settings_manager.getManager()
                    current = (
                        bool(manager.getSetting("speakProgressBarUpdates")),
                        bool(manager.getSetting("beepProgressBarUpdates")),
                    )
                    states = (
                        (False, False, "No progress bar updates"),
                        (True, False, "Speak progress bar updates"),
                        (False, True, "Beep for progress bar updates"),
                        (True, True, "Beep and speak progress bar updates"),
                    )
                    index = next(
                        (i for i, (speak, beep, _label) in enumerate(states)
                         if (speak, beep) == current),
                        len(states) - 1,
                    )
                    speak, beep, label = states[(index + 1) % len(states)]
                    manager.setSetting("speakProgressBarUpdates", speak)
                    manager.setSetting("beepProgressBarUpdates", beep)
                    presenter = getattr(script, "presentMessage", None)
                    if callable(presenter):
                        presenter(label)
                    return True
                except Exception:
                    return unavailable()
            if method == "toggleMouseReview":
                handlers = getattr(script, "inputEventHandlers", None)
                if handlers is None:
                    handlers = getattr(script, "input_event_handlers", None)
                handler_obj = (
                    handlers.get("toggleMouseReviewHandler")
                    if isinstance(handlers, dict) else None
                )
                function = getattr(handler_obj, "function", None)
                if callable(function):
                    return function(script, None) is not False
                return unavailable()
            if method == "toggleInputHelp":
                enabled = getattr(_state, "learnModeEnabled", None)
                if enabled is None:
                    enabled = getattr(_state, "learn_mode_enabled", False)
                names = (
                    ("exitLearnMode", "exit_learn_mode")
                    if bool(enabled)
                    else ("enterLearnMode", "enter_learn_mode")
                )
                for name in names:
                    handler = getattr(script, name, None)
                    if callable(handler):
                        return handler(None) is not False
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
            if method == "showPreferences":
                try:
                    from orca import orca as _orca
                    handler = getattr(_orca, "showPreferencesGUI", None)
                    if not callable(handler):
                        handler = getattr(_orca, "show_preferences_gui", None)
                    if callable(handler):
                        return handler(script, None) is not False
                except Exception:
                    pass
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
            if method == "presentCurrentLine":
                handler = getattr(script, "sayLine", None)
                if not callable(handler):
                    return unavailable()
                target = getattr(_state, "locusOfFocus", None)
                if target is None:
                    target = getattr(_state, "locus_of_focus", None)
                utilities = getattr(script, "utilities", None)
                get_context = getattr(utilities, "getCaretContext", None)
                in_document = getattr(utilities, "inDocumentContent", None)
                document_focus = bool(in_document(target)) if callable(in_document) else None
                browse_focus = document_focus is True and not bool(
                    getattr(script, "_inFocusMode", False))
                if callable(get_context) and (document_focus is None or browse_focus):
                    context = get_context()
                    if isinstance(context, (tuple, list)) and len(context) == 2:
                        target = context[0] if context[0] is not None else target
                if target is None:
                    return False
                flag_names = ("_lastCommandWasCaretNav", "_lastCommandWasStructNav")
                saved_flags = {name: getattr(script, name) for name in flag_names
                               if hasattr(script, name)}
                adjust_flags = document_focus is not None and len(saved_flags) == len(flag_names)
                try:
                    if adjust_flags:
                        script._lastCommandWasCaretNav = False
                        script._lastCommandWasStructNav = browse_focus
                    return handler(target) is not False
                finally:
                    if adjust_flags:
                        for name, value in saved_flags.items():
                            setattr(script, name, value)
            handler = getattr(script, method, None)
            if handler is None:
                return unavailable()
            if not args:
                if method == "togglePresentationMode":
                    focus = getattr(_state, "locusOfFocus", None)
                    if focus is None:
                        focus = getattr(_state, "locus_of_focus", None)
                    in_document = getattr(getattr(script, "utilities", None), "inDocumentContent", None)
                    if callable(in_document) and not in_document(focus):
                        return False
                    from types import SimpleNamespace
                    return handler(SimpleNamespace(type="keyboard", event_string="space")) is not False
                # Orca 42 requires inputEvent for these native commands.
                # Use None unless the command needs manual-event semantics.
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
_LRD_TRACE_PATH = "~/.local/share/orca/orca-remote-input-trace.log"
_LRD_TRACE_LIMIT = 262144
_LRD_TRACE_LOCK = __import__("threading").Lock()
_LRD_TRACE_SEQ = [0]
_LRD_TRACE_TOKEN = __import__("re").compile(r"^[A-Za-z0-9_./:+<>=-]{0,40}$")


def _lrd_trace_clean(value, depth=0):
    """Reduce a diagnostic value to numbers, booleans and fixed short tokens."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if -2147483648 <= value < 2147483648 else None
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, str):
        return value if _LRD_TRACE_TOKEN.match(value) else "?"
    if depth < 3 and isinstance(value, (list, tuple)):
        return [_lrd_trace_clean(item, depth + 1) for item in list(value)[:24]]
    if depth < 3 and isinstance(value, dict):
        return {(k if isinstance(k, str) and _LRD_TRACE_TOKEN.match(k) else "?"):
                _lrd_trace_clean(v, depth + 1) for k, v in list(value.items())[:24]}
    return "?"


def _lrd_trace_write(kind, **fields):
    """Append one metadata-only JSON line. Off unless LINUX_RDACCESS_TRACE=1.

    Records hold command names, generations, booleans and fixed tokens, never
    typed text, braille input, speech, clipboard data or connection keys.
    """
    _os = __import__("os")
    if _os.environ.get("LINUX_RDACCESS_TRACE") != "1":
        return
    path = _os.path.expanduser(_LRD_TRACE_PATH)
    with _LRD_TRACE_LOCK:
        _LRD_TRACE_SEQ[0] += 1
        record = {"seq": _LRD_TRACE_SEQ[0],
                  "t": round(__import__("time").time(), 3), "kind": kind}
        for key, value in fields.items():
            record[key] = _lrd_trace_clean(value)
        line = __import__("json").dumps(record, sort_keys=True) + chr(10)
        try:
            try:
                _os.chmod(path, 0o600)
                if _os.path.getsize(path) > _LRD_TRACE_LIMIT:
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
                handle.write(line)
        except OSError:
            pass


def _lrd_trace_context(script):
    """Classify the focused context without reading any content."""
    result = {"ctx": "unknown", "editable": None, "web_app": None, "stale": None}
    try:
        utilities = getattr(script, "utilities", None)
        in_document = getattr(utilities, "inDocumentContent", None)
        if not callable(in_document):
            result["ctx"] = "not_web"
        elif not in_document():
            result["ctx"] = "chrome_or_non_document"
        else:
            focus = getattr(script, "inFocusMode", None)
            focus = focus() if callable(focus) else getattr(script, "_inFocusMode", None)
            result["ctx"] = ("document_focus" if focus else "document_browse") \
                if focus is not None else "document"
    except Exception:
        return result
    try:
        from orca import orca_state
        locus = getattr(orca_state, "locusOfFocus", None)
        if locus is not None:
            import pyatspi
            result["editable"] = bool(
                locus.getState().contains(pyatspi.STATE_EDITABLE))
            web_app = getattr(utilities, "isWebAppDescendant", None)
            if callable(web_app):
                result["web_app"] = bool(web_app(locus))
            zombie = getattr(utilities, "isZombie", None)
            if callable(zombie):
                result["stale"] = bool(zombie(locus))
    except Exception:
        pass
    return result


def _lrd_trace_hook(hook, decision, script=None, **fields):
    """Record an Orca-side decision for a remote-claimed gesture."""
    if __import__("os").environ.get("LINUX_RDACCESS_TRACE") != "1":
        return
    try:
        context = _lrd_trace_context(script) if script is not None else {}
        _lrd_trace_write("hook", hook=hook, decision=decision, **context, **fields)
    except Exception:
        pass


_LRD_NAV_LOCK = __import__("threading").RLock()
_LRD_NAV_WINDOW = 1.0
_LRD_NAV_MAX_PENDING = 64
_LRD_D = {"pending": [], "swapped": False, "modifiers": 0, "code": None}


def _lrd_prune_navigation_markers(marker, now):
    marker["pending"][:] = [token for token in marker["pending"]
                            if now - token[0] <= _LRD_NAV_WINDOW]


def _lrd_publish_navigation_marker(marker, key):
    """Publish one bounded, expiring, key-specific injection claim."""
    now = __import__("time").monotonic()
    token = (now, key, object())
    with _LRD_NAV_LOCK:
        _lrd_prune_navigation_markers(marker, now)
        marker["pending"].append(token)
        del marker["pending"][:-_LRD_NAV_MAX_PENDING]
    return token


def _lrd_remove_navigation_marker(marker, token):
    with _LRD_NAV_LOCK:
        marker["pending"][:] = [item for item in marker["pending"]
                                if item is not token]


def _lrd_take_navigation_marker(marker, key):
    with _LRD_NAV_LOCK:
        _lrd_prune_navigation_markers(marker, __import__("time").monotonic())
        for index, token in enumerate(marker["pending"]):
            if token[1] == key:
                marker["pending"].pop(index)
                return True
    return False


def _lrd_clear_navigation_markers(marker):
    with _LRD_NAV_LOCK:
        marker["pending"].clear()


_LRD_BYPASS = {"pending": [], "owner": None, "codes": {}}
_LRD_BYPASS_MAX_PENDING = 256


def _lrd_publish_bypass_key(name, pressed, request):
    now = __import__("time").monotonic()
    token = (now, name, bool(pressed), request, object())
    with _LRD_NAV_LOCK:
        _LRD_BYPASS["pending"][:] = [item for item in _LRD_BYPASS["pending"]
                                     if now - item[0] <= _LRD_NAV_WINDOW]
        _LRD_BYPASS["pending"].append(token)
        del _LRD_BYPASS["pending"][:-_LRD_BYPASS_MAX_PENDING]
    return token


def _lrd_remove_bypass_key(token):
    with _LRD_NAV_LOCK:
        _LRD_BYPASS["pending"][:] = [item for item in _LRD_BYPASS["pending"]
                                     if item is not token]


def _lrd_clear_bypass_keys():
    with _LRD_NAV_LOCK:
        _LRD_BYPASS["pending"].clear()
        _LRD_BYPASS["codes"].clear()


def _lrd_cleanup_owned_bypass(request):
    """Clear only the native flag installed by this remote request."""
    if _LRD_BYPASS["owner"] is not request:
        return
    _LRD_BYPASS["owner"] = None
    request["complete"] = True
    try:
        from orca import orca_state
        if not getattr(orca_state, "bypassNextCommand", False):
            return
        orca_state.bypassNextCommand = False
        script = getattr(orca_state, "activeScript", None)
        restore = getattr(script, "addKeyGrabs", None)
        if callable(restore):
            restore()
    except Exception:
        log.error("linux-rdaccess: native bypass cleanup failed")


def _lrd_schedule_bypass_cleanup(request):
    # Identity checks, rather than generation checks, let cleanup survive
    # consecutive handoffs while protecting a newer request's native flag.
    if __import__("threading").current_thread() is __import__("threading").main_thread():
        _lrd_cleanup_owned_bypass(request)
        return
    try:
        from gi.repository import GLib
        GLib.idle_add(lambda: (_lrd_cleanup_owned_bypass(request), False)[1])
    except Exception:
        log.error("linux-rdaccess: native bypass cleanup unavailable")


def _lrd_native_bypass_claim(event, keybindings):
    pressed = event.isPressedKey()
    now = __import__("time").monotonic()
    found = None
    matched = False
    with _LRD_NAV_LOCK:
        _LRD_BYPASS["pending"][:] = [token for token in _LRD_BYPASS["pending"]
                                     if now - token[0] <= _LRD_NAV_WINDOW]
        for index, token in enumerate(_LRD_BYPASS["pending"]):
            _time, name, down, request, _identity = token
            code = _LRD_BYPASS["codes"].get(name) or keybindings.getKeycode(name)
            if down == pressed and code and code == event.hw_code:
                _LRD_BYPASS["pending"].pop(index)
                if pressed:
                    _LRD_BYPASS["codes"][name] = code
                else:
                    _LRD_BYPASS["codes"].pop(name, None)
                found = request
                matched = True
                break
    if not matched:
        return False
    if found is None:
        # An older normal event can arrive after the activation callback has
        # armed Orca's native flag. Only the claimed gesture owns that flag;
        # the bridge still retains the request after restoring native grabs.
        owner = _LRD_BYPASS["owner"]
        if owner is not None:
            _lrd_cleanup_owned_bypass(owner)
        return False
    if pressed:
        # Passing a repeat changes this held key's role. Its later release
        # must not inherit a structural command from an earlier normal press.
        if getattr(event, "event_string", None) in ("d", "D"):
            _LRD_D["swapped"] = False
            _LRD_D["modifiers"] = 0
            _LRD_D["code"] = None
        _LRD_T["held"].pop(event.hw_code, None)
    _lrd_cleanup_owned_bypass(found)
    if found["external"] and pressed:
        # Match Orca's native bypass cleanup when this claimed gesture reaches
        # its event processor; do it here even if another wrapper short-circuits.
        try:
            from orca import orca_state
            if getattr(orca_state, "bypassNextCommand", False):
                orca_state.bypassNextCommand = False
                restore = getattr(getattr(event, "_script", None), "addKeyGrabs", None)
                if callable(restore):
                    restore()
        except Exception:
            log.error("linux-rdaccess: native bypass cleanup failed")
    found["complete"] = True
    event._handler = None
    event._consumer = None
    return True


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
    _LRD_D["swapped"] = False
    blocked = (keybindings.CTRL_MODIFIER_MASK | keybindings.ALT_MODIFIER_MASK
               | keybindings.ORCA_MODIFIER_MASK)
    if event.modifiers & blocked:
        return None
    # An earlier, ineligible same-key event can still be queued when a later
    # remote landmark press publishes its claim. It must not steal that claim.
    fresh = _lrd_take_navigation_marker(_LRD_D, "d")
    if not fresh:
        return None
    script = getattr(event, "_script", None)
    nav = getattr(script, "structuralNavigation", None)
    gate = getattr(script, "useStructuralNavigationModel", None)
    if nav is None or gate is None:
        return None
    if pressed and not gate():
        # Typed text: no key identity is recorded for a refused letter.
        _lrd_trace_hook("letter_nav", "refused_not_browse", script)
        return None
    code = keybindings.getKeycode("m")
    if not code:
        return None
    original = (event.hw_code, event.modifiers)
    event.hw_code = code
    try:
        handler = script.keyBindings.getInputHandler(event)
    except BaseException:
        # Never leave the event rewritten if Orca's lookup fails.
        event.hw_code, event.modifiers = original
        raise
    if handler is None or handler.function not in nav.functions:
        event.hw_code, event.modifiers = original
        return None
    if pressed:
        _lrd_trace_hook("letter_nav", "translated", script, cmd="landmark")
        _LRD_D["swapped"] = True
        _LRD_D["modifiers"] = event.modifiers
        _LRD_D["code"] = code
    else:
        _LRD_D["swapped"] = False
        _LRD_D["modifiers"] = 0
        _LRD_D["code"] = None
    return original


# NVDA browse mode and Orca 42 disagree on these single-letter commands:
# A annotation vs clickable, F form field vs Orca's Tab-based form navigation,
# M frame vs landmark, O embedded object vs chunk, while N non-link block and
# W spelling error have no Orca 42 equivalents.
# Consume only a freshly proven remote key while Orca's structural model is
# active. Local Linux input and focus-mode/editable typing are untouched.
_LRD_NVDA_BROWSE = {"pending": [], "held": {}}


def _lrd_consume_layout_mode(event=None):
    action = getattr(event, "_lrd_layout_mode_action", None) if event is not None else None
    if not action:
        return True
    method, event_arg = action
    method(event_arg)
    return True


def _lrd_consume_find(event=None):
    action = getattr(event, "_lrd_find_action", None) if event is not None else None
    if not action:
        return True
    method, script = action
    method(script, event)
    return True


def _lrd_maybe_nvda_browse(event, keybindings):
    pressed = event.isPressedKey()
    held = _LRD_NVDA_BROWSE["held"]
    if not pressed:
        if event.hw_code not in held:
            return False
        held.pop(event.hw_code, None)
        event._handler = None
        event._consumer = _lrd_consume_unsupported_browse
        return True

    key = str(getattr(event, "event_string", "") or "")
    if (key.lower() == "f"
            and event.modifiers & keybindings.CTRL_MODIFIER_MASK):
        action = "find"
    elif key.lower() == "v":
        action = "layout"
    elif key == "F3":
        action = ("findPrevious"
                  if event.modifiers & keybindings.SHIFT_MODIFIER_MASK
                  else "findNext")
    elif key == "F10":
        action = "nativeSelection"
    elif key in ("Up", "Down") and event.modifiers & keybindings.ALT_MODIFIER_MASK:
        action = "collapseExpandUp" if key == "Up" else "collapseExpandDown"
    else:
        return False
    if not _lrd_take_navigation_marker(_LRD_NVDA_BROWSE, action):
        return False

    script = getattr(event, "_script", None)
    utilities = getattr(script, "utilities", None)
    in_document = getattr(utilities, "inDocumentContent", None)
    if not callable(in_document):
        in_document = getattr(utilities, "in_document_content", None)
    document_active = False
    if callable(in_document):
        try:
            document_active = bool(in_document())
        except Exception:
            document_active = False
    else:
        # Older/non-web scripts might lack the document helper. Retain the
        # structural-navigation gate only as a conservative fallback.
        gate = getattr(script, "useStructuralNavigationModel", None)
        document_active = bool(callable(gate) and gate())

    if action in ("collapseExpandUp", "collapseExpandDown"):
        gate = getattr(script, "useStructuralNavigationModel", None)
        if not callable(gate) or not gate():
            _lrd_trace_hook("nvda_browse", "refused_not_browse", script, cmd=action)
            return False

    held[event.hw_code] = event.modifiers
    event._handler = None
    if not document_active:
        _lrd_trace_hook("nvda_browse", "consumed_outside_document", script, cmd=action)
        # These are NVDA tree-interceptor commands. Outside document content
        # NVDA-modifier gestures must not fall through as unrelated Orca
        # commands (notably Orca+V toggles speech verbosity).
        event._consumer = _lrd_consume_unsupported_browse
        return True
    if action == "find":
        handlers = getattr(script, "inputEventHandlers", None)
        find_handler = handlers.get("findHandler") if isinstance(handlers, dict) else None
        method = getattr(find_handler, "function", None)
        if callable(method):
            _lrd_trace_hook("nvda_browse", "native", script, cmd=action)
            event._lrd_find_action = (method, script)
            event._consumer = _lrd_consume_find
            return True
    elif action == "layout":
        method = getattr(script, "toggleLayoutMode", None)
        if not callable(method):
            method = getattr(script, "toggle_layout_mode", None)
        if callable(method):
            _lrd_trace_hook("nvda_browse", "native", script, cmd=action)
            event._lrd_layout_mode_action = (method, event)
            event._consumer = _lrd_consume_layout_mode
            return True
    elif action in ("findNext", "findPrevious"):
        names = (
            ("findNext", "find_next")
            if action == "findNext"
            else ("findPrevious", "find_previous")
        )
        method = next(
            (getattr(script, name, None) for name in names
             if callable(getattr(script, name, None))),
            None,
        )
        if callable(method):
            _lrd_trace_hook("nvda_browse", "native", script, cmd=action)
            event._lrd_layout_mode_action = (method, event)
            event._consumer = _lrd_consume_layout_mode
            return True
    # Orca 42 has no NVDA-equivalent native-selection-mode or virtual-caret
    # collapse/expand command. In browse mode consume these rather than
    # executing unrelated application/desktop shortcuts.
    _lrd_trace_hook("nvda_browse", "consumed_unsupported", script, cmd=action)
    event._consumer = _lrd_consume_unsupported_browse
    return True


_LRD_BROWSE_UNSUPPORTED = {"pending": [], "held": {}}
_LRD_BROWSE_UNSUPPORTED_KEYS = ("a", "f", "m", "n", "o", "w", "7", "8", "9")


def _lrd_consume_unsupported_browse(event=None):
    return True


def _lrd_consume_form_field(event=None):
    action = getattr(event, "_lrd_form_field_action", None) if event is not None else None
    if not action:
        return True
    method, script = action
    return method(script, event)


def _lrd_consume_heading_level(event=None):
    action = getattr(event, "_lrd_heading_level_action", None) if event is not None else None
    if not action:
        return True
    method, script = action
    return method(script, event)


def _lrd_maybe_suppress_browse(event, keybindings):
    pressed = event.isPressedKey()
    held = _LRD_BROWSE_UNSUPPORTED["held"]

    if not pressed:
        if event.hw_code not in held:
            return False
        held.pop(event.hw_code, None)
        event._handler = None
        event._consumer = _lrd_consume_unsupported_browse
        return True

    key = str(getattr(event, "event_string", "") or "").lower()
    if key not in _LRD_BROWSE_UNSUPPORTED_KEYS and event.modifiers & keybindings.SHIFT_MODIFIER_MASK:
        # Shift+digits arrive as layout-dependent printable symbols. Identify
        # heading levels by their physical X keycode, retaining the original
        # event string for native typing, echo, and release matching.
        for level in ("7", "8", "9"):
            code = keybindings.getKeycode(level)
            if code and code == event.hw_code:
                key = level
                break
    if key not in _LRD_BROWSE_UNSUPPORTED_KEYS:
        return False
    blocked = (
        keybindings.CTRL_MODIFIER_MASK
        | keybindings.ALT_MODIFIER_MASK
        | keybindings.ORCA_MODIFIER_MASK
    )
    if event.modifiers & blocked:
        return False

    # Claim the remote provenance before asking Orca's mode gate. A remote key
    # refused in focus mode must not leave a token for a later local key.
    if not _lrd_take_navigation_marker(_LRD_BROWSE_UNSUPPORTED, key):
        return False

    script = getattr(event, "_script", None)
    gate = getattr(script, "useStructuralNavigationModel", None)
    if not callable(gate) or not gate():
        # Focus mode, editable controls and the address bar land here: the
        # letter is ordinary typing, so only the refusal and context are kept.
        _lrd_trace_hook("letter_nav", "refused_not_browse", script)
        return False

    held[event.hw_code] = event.modifiers
    event._handler = None
    if key == "f":
        nav = getattr(script, "structuralNavigation", None)
        if nav is None:
            nav = getattr(script, "structural_navigation", None)
        objects = getattr(nav, "enabledObjects", None) if nav is not None else None
        if objects is None and nav is not None:
            objects = getattr(nav, "enabled_objects", None)
        form = objects.get("formField") if isinstance(objects, dict) else None
        reverse = bool(event.modifiers & keybindings.SHIFT_MODIFIER_MASK)
        names = ("goPrevious", "go_previous") if reverse else ("goNext", "go_next")
        method = next(
            (getattr(form, name, None) for name in names
             if callable(getattr(form, name, None))),
            None,
        )
        if callable(method):
            _lrd_trace_hook("letter_nav", "native", script, cmd="form_field",
                            reverse=reverse)
            event._lrd_form_field_action = (method, script)
            event._consumer = _lrd_consume_form_field
            return True
    elif key in ("7", "8", "9"):
        nav = getattr(script, "structuralNavigation", None)
        if nav is None:
            nav = getattr(script, "structural_navigation", None)
        objects = getattr(nav, "enabledObjects", None) if nav is not None else None
        if objects is None and nav is not None:
            objects = getattr(nav, "enabled_objects", None)
        heading = objects.get("heading") if isinstance(objects, dict) else None
        reverse = bool(event.modifiers & keybindings.SHIFT_MODIFIER_MASK)
        factory_names = (
            ("goPreviousAtLevelFactory", "go_previous_at_level_factory")
            if reverse
            else ("goNextAtLevelFactory", "go_next_at_level_factory")
        )
        factory = next(
            (getattr(heading, name, None) for name in factory_names
             if callable(getattr(heading, name, None))),
            None,
        )
        if callable(factory):
            method = factory(int(key))
            if callable(method):
                _lrd_trace_hook("letter_nav", "native", script,
                                cmd="heading_level", level=int(key), reverse=reverse)
                event._lrd_heading_level_action = (method, script)
                event._consumer = _lrd_consume_heading_level
                return True
    _lrd_trace_hook("letter_nav", "consumed_unsupported", script, cmd="browse_letter")
    event._consumer = _lrd_consume_unsupported_browse
    return True


# NVDA Ctrl+Alt+PageUp/PageDown/Home/End move to the first/last row or
# column while preserving the other coordinate. Orca 42's Shift+Alt+Home/End
# instead jump to the first/last table cell, so use its native goCell primitive.
_LRD_TABLE_EDGE = {"pending": [], "held": {}}
_LRD_TABLE_EDGE_KEYS = {
    "Page_Up": "firstRow",
    "Page_Down": "lastRow",
    "Home": "firstColumn",
    "End": "lastColumn",
}


def _lrd_resolve_table_edge(script, action_name):
    nav = getattr(script, "structuralNavigation", None)
    if nav is None:
        nav = getattr(script, "structural_navigation", None)
    objects = getattr(nav, "enabledObjects", None) if nav is not None else None
    if objects is None and nav is not None:
        objects = getattr(nav, "enabled_objects", None)
    cell_obj = objects.get("tableCell") if isinstance(objects, dict) else None
    if cell_obj is None:
        return None

    utilities = getattr(script, "utilities", None)
    get_context = getattr(utilities, "getCaretContext", None)
    get_cell = getattr(nav, "getCellForObj", None)
    get_coords = getattr(nav, "getCellCoordinates", None)
    get_table = getattr(nav, "getTableForCell", None)
    go_cell = getattr(nav, "goCell", None)
    row_col_count = getattr(utilities, "rowAndColumnCount", None)
    if not all(callable(x) for x in (
            get_context, get_cell, get_coords, get_table, go_cell, row_col_count)):
        return None
    obj, _offset = get_context()
    this_cell = get_cell(obj)
    if this_cell is None:
        return None
    current = list(get_coords(this_cell, False))
    if len(current) != 2 or min(current) < 0:
        return None
    table = get_table(this_cell)
    if table is None:
        return None
    rows, columns = row_col_count(table, False)
    if rows <= 0 or columns <= 0:
        return None
    row, column = current
    if action_name == "firstRow":
        desired = [0, column]
    elif action_name == "lastRow":
        desired = [rows - 1, column]
    elif action_name == "firstColumn":
        desired = [row, 0]
    else:
        desired = [row, columns - 1]
    return nav, cell_obj, this_cell, current, desired


def _lrd_consume_table_edge(event=None):
    action = getattr(event, "_lrd_table_edge_action", None) if event is not None else None
    if not action:
        return True
    script, action_name = action
    resolved = _lrd_resolve_table_edge(script, action_name)
    if resolved is None:
        # The cell, table or focus changed between claim and consumer.
        _lrd_trace_hook("table", "consumer_stale", script, cmd=action_name)
        return True
    nav, cell_obj, this_cell, current, desired = resolved
    nav.goCell(cell_obj, this_cell, current, desired)
    return True


def _lrd_maybe_table_edge(event, keybindings):
    pressed = event.isPressedKey()
    held = _LRD_TABLE_EDGE["held"]
    if not pressed:
        if event.hw_code not in held:
            return False
        held.pop(event.hw_code, None)
        event._handler = None
        event._consumer = _lrd_consume_unsupported_browse
        return True

    key = str(getattr(event, "event_string", "") or "")
    action_name = _LRD_TABLE_EDGE_KEYS.get(key)
    if action_name is None:
        return False
    ctrl, alt = keybindings.CTRL_MODIFIER_MASK, keybindings.ALT_MODIFIER_MASK
    tracked = (keybindings.SHIFT_MODIFIER_MASK | ctrl | alt
               | keybindings.ORCA_MODIFIER_MASK)
    if event.modifiers & tracked != ctrl | alt:
        return False
    if not _lrd_take_navigation_marker(_LRD_TABLE_EDGE, action_name):
        return False

    script = getattr(event, "_script", None)
    gate = getattr(script, "useStructuralNavigationModel", None)
    if not callable(gate) or not gate():
        _lrd_trace_hook("table", "refused_not_browse", script, cmd=action_name)
        return False
    if _lrd_resolve_table_edge(script, action_name) is None:
        _lrd_trace_hook("table", "refused_no_cell", script, cmd=action_name)
        return False

    _lrd_trace_hook("table", "translated_edge", script, cmd=action_name)
    held[event.hw_code] = event.modifiers
    event._handler = None
    # Orca runs consumers later on GLib. Store only stable command identity;
    # re-read caret/cell/table at consume time so focus changes cannot make
    # this command operate on a stale AT-SPI cell.
    event._lrd_table_edge_action = (script, action_name)
    event._consumer = _lrd_consume_table_edge
    return True


# NVDA's table commands are Ctrl+Alt+Arrow; Orca 42 binds the same actions to
# Shift+Alt+Arrow (structural navigation, tableCell). Translate only an arrow
# that arrived from the remote session with exactly Ctrl+Alt held, and only
# where Orca itself would use structural navigation (web document, browse
# mode), so editable grids, focus mode and non-document windows keep Ctrl+Alt+
# Arrow. Only Orca's own tableCell handlers are accepted. A release follows
# the identity chosen for its press. Opt out with
# LINUX_RDACCESS_NVDA_TABLE_KEYS=0.
_LRD_T = {"pending": [], "held": {}}
_LRD_TABLE_ARROWS = ("Left", "Right", "Up", "Down")


def _lrd_maybe_swap_table(event, keybindings):
    """Return (hw_code, modifiers) to restore if translated, else None."""
    if __import__("os").environ.get("LINUX_RDACCESS_NVDA_TABLE_KEYS") == "0":
        return None
    pressed = event.isPressedKey()
    held = _LRD_T["held"]
    if not pressed:
        # Each translated arrow keeps its own identity, so rolling from one
        # table key to another while the first is still down does not strand
        # the first key's release. Other keys never inherit a translation.
        modifiers = held.pop(event.hw_code, None)
        if modifiers is None:
            return None
        original = (event.hw_code, event.modifiers)
        event.modifiers = modifiers
        return original

    key = next((name for name in _LRD_TABLE_ARROWS
                if keybindings.getKeycode(name) == event.hw_code), None)
    if key is None:
        return None
    # A new press (including auto-repeat) supersedes any earlier decision.
    held.pop(event.hw_code, None)
    # The marker belongs to exactly one arrow that Orca evaluates, whether or
    # not it ends up translated.
    ctrl, alt = keybindings.CTRL_MODIFIER_MASK, keybindings.ALT_MODIFIER_MASK
    tracked = (keybindings.SHIFT_MODIFIER_MASK | ctrl | alt
               | keybindings.ORCA_MODIFIER_MASK)
    if event.modifiers & tracked != ctrl | alt:
        return None
    # Plain arrows and other chords queued before a remote table press do not
    # own its claim. Browse/focus refusal below still consumes an eligible one.
    fresh = _lrd_take_navigation_marker(_LRD_T, key)
    if not fresh:
        return None
    script = getattr(event, "_script", None)
    nav = getattr(script, "structuralNavigation", None)
    gate = getattr(script, "useStructuralNavigationModel", None)
    if nav is None or gate is None or not gate():
        _lrd_trace_hook("table", "refused_not_browse", script, cmd=key)
        return None
    cell = (getattr(nav, "enabledObjects", None) or {}).get("tableCell")
    cell_functions = getattr(cell, "functions", None)
    if not cell_functions:
        _lrd_trace_hook("table", "refused_no_cell_handler", script, cmd=key)
        return None
    original = (event.hw_code, event.modifiers)
    event.modifiers = (event.modifiers & ~ctrl) | keybindings.SHIFT_MODIFIER_MASK
    try:
        handler = script.keyBindings.getInputHandler(event)
    except BaseException:
        # Never leave the event rewritten if Orca's lookup fails.
        event.hw_code, event.modifiers = original
        raise
    if handler is None or handler.function not in cell_functions:
        event.hw_code, event.modifiers = original
        _lrd_trace_hook("table", "refused_no_cell_handler", script, cmd=key)
        return None
    _lrd_trace_hook("table", "translated_arrow", script, cmd=key)
    held[event.hw_code] = event.modifiers
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
        try:
            if _lrd_native_bypass_claim(self, keybindings):
                return False, "linux-rdaccess passed remote gesture to application"
        except Exception:
            log.error("linux-rdaccess: native bypass dispatch failed")
        try:
            if _lrd_maybe_nvda_browse(self, keybindings):
                return True, "linux-rdaccess handled NVDA browse-mode command"
        except Exception:
            log.error("linux-rdaccess: NVDA browse-mode command failed")
        try:
            if _lrd_maybe_suppress_browse(self, keybindings):
                return True, "linux-rdaccess suppressed mismatched NVDA browse command"
        except Exception:
            log.error("linux-rdaccess: browse command suppression failed")
        try:
            if _lrd_maybe_table_edge(self, keybindings):
                return True, "linux-rdaccess translated NVDA table edge command"
        except Exception:
            log.error("linux-rdaccess: table edge navigation translation failed")
        restore = None
        try:
            restore = _lrd_maybe_swap_d(self, keybindings)
        except Exception:
            log.error("linux-rdaccess: D landmark translation failed")
        if restore is None:
            try:
                restore = _lrd_maybe_swap_table(self, keybindings)
            except Exception:
                log.error("linux-rdaccess: table navigation translation failed")
        try:
            result = original(self)
            if restore is not None:
                # Only gestures this patch translated are reported; Orca's
                # decision for ordinary keys is never recorded.
                _lrd_trace_hook(
                    "orca_native",
                    "consumed" if (result[0] if isinstance(result, tuple) and result
                                   else result) else "not_consumed",
                    getattr(self, "_script", None))
            return result
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
    "for _lrd_name in (\"_on_remote_key\", \"_on_remote_braille_input\",\n"
    "                  \"_linux_rdaccess_reset_keys\",\n"
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
    "                self._lrd_reset_reason = name\n"
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
    "                    self._lrd_reset_reason = \"client_left\"\n"
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
LOCAL_MACHINE_MARKER_V8 = LOCAL_MACHINE_MARKER_V1 + " v8"
LOCAL_MACHINE_MARKER_V9 = LOCAL_MACHINE_MARKER_V1 + " v9"
LOCAL_MACHINE_MARKER_V10 = LOCAL_MACHINE_MARKER_V1 + " v10"
LOCAL_MACHINE_MARKER_V11 = LOCAL_MACHINE_MARKER_V1 + " v11"
LOCAL_MACHINE_MARKER = LOCAL_MACHINE_MARKER_V1 + " v12"
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
_LRD_LOCK_KEY_NAMES = {
    0x14: "Caps_Lock", 0x90: "Num_Lock", 0x91: "Scroll_Lock",
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
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
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
                if name in ("Caps_Lock", "Num_Lock", "Scroll_Lock"):
                    # Make the resulting XKB state authoritative before the
                    # controller schedules lock-state presentation.
                    self._x11.XSync(self._dpy, 0)
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


_LRD_MAIN_GENERATION = [0]


def _lrd_invalidate_pending_main_calls():
    _LRD_MAIN_GENERATION[0] += 1


def _lrd_call_on_main(func, *args, **kwargs):
    """Run func on GLib only if it still belongs to the current session."""
    generation = _LRD_MAIN_GENERATION[0]
    try:
        from gi.repository import GLib
    except Exception:
        if generation == _LRD_MAIN_GENERATION[0]:
            return func(*args, **kwargs)
        return None

    def invoke():
        if generation == _LRD_MAIN_GENERATION[0]:
            func(*args, **kwargs)
        return False

    GLib.idle_add(invoke)


def _lrd_local_invalidate_pending(self):
    _lrd_invalidate_pending_main_calls()


LocalMachine._linux_rdaccess_invalidate_pending = _lrd_local_invalidate_pending
'''

_XDOTOOL_DEF_RE = re.compile(r"^    def _send_key_xdotool\(self, key, pressed\):\n", re.MULTILINE)
_RESOLVE_KEY_DEF_RE = re.compile(
    r"^    def _resolve_key\(key_name, vk_code, extended\):\n", re.MULTILINE)
_RESOLVE_KEY_HOOK = (
    "        if not key_name:\n"
    "            lock_name = _LRD_LOCK_KEY_NAMES.get(vk_code)\n"
    "            if lock_name is not None:\n"
    "                return lock_name\n"
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
                LEGACY_COMPAT_MARKER_V93,
                LEGACY_COMPAT_MARKER_V92,
                LEGACY_COMPAT_MARKER_V91,
                LEGACY_COMPAT_MARKER_V90,
                LEGACY_COMPAT_MARKER_V89,
                LEGACY_COMPAT_MARKER_V88,
                LEGACY_COMPAT_MARKER_V87,
                LEGACY_COMPAT_MARKER_V86,
                LEGACY_COMPAT_MARKER_V85,
                LEGACY_COMPAT_MARKER_V84,
                LEGACY_COMPAT_MARKER_V83,
                LEGACY_COMPAT_MARKER_V82,
                LEGACY_COMPAT_MARKER_V81,
                LEGACY_COMPAT_MARKER_V80,
                LEGACY_COMPAT_MARKER_V79,
                LEGACY_COMPAT_MARKER_V78,
                LEGACY_COMPAT_MARKER_V77,
                LEGACY_COMPAT_MARKER_V76,
                LEGACY_COMPAT_MARKER_V75,
                LEGACY_COMPAT_MARKER_V74,
                LEGACY_COMPAT_MARKER_V73,
                LEGACY_COMPAT_MARKER_V72,
                LEGACY_COMPAT_MARKER_V71,
                LEGACY_COMPAT_MARKER_V70,
                LEGACY_COMPAT_MARKER_V69,
                LEGACY_COMPAT_MARKER_V68,
                LEGACY_COMPAT_MARKER_V67,
                LEGACY_COMPAT_MARKER_V66,
                LEGACY_COMPAT_MARKER_V65,
                LEGACY_COMPAT_MARKER_V64,
                LEGACY_COMPAT_MARKER_V63,
                LEGACY_COMPAT_MARKER_V62,
                LEGACY_COMPAT_MARKER_V61,
                LEGACY_COMPAT_MARKER_V60,
                LEGACY_COMPAT_MARKER_V59,
                LEGACY_COMPAT_MARKER_V58,
                LEGACY_COMPAT_MARKER_V57,
                LEGACY_COMPAT_MARKER_V56,
                LEGACY_COMPAT_MARKER_V55,
                LEGACY_COMPAT_MARKER_V54,
                LEGACY_COMPAT_MARKER_V53,
                LEGACY_COMPAT_MARKER_V52,
                LEGACY_COMPAT_MARKER_V51,
                LEGACY_COMPAT_MARKER_V50,
                LEGACY_COMPAT_MARKER_V49,
                LEGACY_COMPAT_MARKER_V48,
                LEGACY_COMPAT_MARKER_V47,
                LEGACY_COMPAT_MARKER_V46,
                LEGACY_COMPAT_MARKER_V45,
                LEGACY_COMPAT_MARKER_V44,
                LEGACY_COMPAT_MARKER_V43,
                LEGACY_COMPAT_MARKER_V42,
                LEGACY_COMPAT_MARKER_V41,
                LEGACY_COMPAT_MARKER_V40,
                LEGACY_COMPAT_MARKER_V39,
                LEGACY_COMPAT_MARKER_V38,
                LEGACY_COMPAT_MARKER_V37,
                LEGACY_COMPAT_MARKER_V36,
                LEGACY_COMPAT_MARKER_V35,
                LEGACY_COMPAT_MARKER_V34,
                LEGACY_COMPAT_MARKER_V33,
                LEGACY_COMPAT_MARKER_V32,
                LEGACY_COMPAT_MARKER_V31,
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
