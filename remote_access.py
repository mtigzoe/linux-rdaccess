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
import shutil
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

LOCAL_SPEECH_PREF_MARKER = "# linux-rdaccess local Orca speech preference"


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

    pref_line = (
        "LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH = "
        + ("True" if config.mute_local_orca_speech else "False")
    )
    pref_re = re.compile(
        r"^LINUX_RDACCESS_MUTE_LOCAL_ORCA_SPEECH\s*=.*$",
        re.MULTILINE,
    )
    if pref_re.search(text):
        text = pref_re.sub(pref_line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + pref_line + "\n"

    if LOCAL_SPEECH_PREF_MARKER not in text:
        text = text.rstrip("\n") + """


# linux-rdaccess local Orca speech preference
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
""" + "\n"

    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    # Both files can contain an NVDA Remote channel key: the live file has the
    # new key and the one-time backup may contain the previous key.
    for private_path in (backup, path):
        try:
            private_path.chmod(0o600)
        except OSError:
            pass
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass

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
                f"warning: NVDA input compatibility patch not applied: {exc}",
                file=sys.stderr,
            )
    local_machine = path.parent / LEGACY_LOCAL_MACHINE_RELATIVE
    if local_machine.exists():
        try:
            patch_legacy_orca_local_machine(local_machine)
        except (ValueError, OSError) as exc:
            print(
                f"warning: low-latency key injection patch not applied: {exc}",
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
LEGACY_COMPAT_MARKER = "# linux-rdaccess NVDA/Orca input compatibility v28"
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
                log.exception("linux-rdaccess: failed to cancel speech")

        self._linux_rdaccess_run_main(run)

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
            log.exception("linux-rdaccess: failed to send cancel to NVDA")

    def _linux_rdaccess_reset_keys(self):
        """Release forwarded held keys and clear compatibility state.

        Remote disconnects/control hand-offs can lose key-up events. Keys in
        _lrd_swapped were consumed by the compatibility layer and were never
        forwarded as their original key, so do not synthesize releases for
        those. Everything else that is still down is released directly through
        the local machine before state is forgotten.
        """
        down = set(getattr(self, "_lrd_down", set()))
        swapped = set(getattr(self, "_lrd_swapped", set()))
        pending_caps = getattr(self, "_lrd_caps_pending", None)
        send = getattr(getattr(self, "local_machine", None), "send_key", None)
        if callable(send):
            for vk_code, extended in sorted(down):
                if (vk_code, extended) in swapped or (vk_code, extended) == pending_caps:
                    continue
                try:
                    send(
                        key_name=None, pressed=False, modifiers=None,
                        vk_code=vk_code, scan_code=0, extended=extended)
                except Exception:
                    log.exception("linux-rdaccess: failed to release held key on reset")
        self._lrd_down = set()
        self._lrd_nvda_down = False
        self._lrd_swapped = set()
        self._lrd_nvda_key = None
        self._lrd_caps_pending = None
        self._lrd_caps_used = False
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
            self.local_machine.send_key(
                key_name=None, pressed=True, modifiers=None,
                vk_code=held[0], scan_code=0, extended=held[1])
        except Exception:
            log.exception("linux-rdaccess: failed to forward deferred CapsLock")

    def _linux_rdaccess_filter_key(self, pressed, vk_code, extended, modifiers,
                                   key_name=None, scan_code=None):
        """Return True when the event was fully handled here."""
        state = (
            getattr(self, "control_state", None),
            bool(getattr(getattr(self, "transport", None), "connected", True)),
        )
        if getattr(self, "_lrd_state", None) != state:
            # Control moved local/remote or the transport reconnected. Release
            # keys that were actually forwarded before forgetting state; a
            # missing remote key-up must never leave Linux with a stuck arrow
            # or modifier after reconnect.
            self._linux_rdaccess_reset_keys()
            self._lrd_state = state
        pressed = bool(pressed)
        held = (vk_code, bool(extended))
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
                    self._linux_rdaccess_run_main(
                        lambda: self._linux_rdaccess_script_call("bypassNextCommand"))
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

    def _linux_rdaccess_classify_braille(self, kwargs):
        """Return (action, safe_record) for an NVDA Remote braille_input."""
        def text(value):
            return str(value)[:120]
        ids = [kwargs.get("id")] + list(kwargs.get("identifiers") or [])
        # NVDA's BrailleInputGesture declares dots=0 and space=False as class
        # attributes and NVDA Remote copies them with hasattr(), so EVERY
        # gesture from a display whose gesture class inherits it (Eurobraille,
        # Handy Tech, Freedom Scientific, HIMS...) carries both fields, pan and
        # routing keys included. Their presence therefore says nothing; typed
        # braille is identified by a non-zero dots mask, a truthy space flag
        # (some drivers report it as an int such as 0x200), a "dot" in the
        # gesture id/identifiers, or an exact "space" key-name token. A lone
        # "backSpace" key name is not a typed space.
        def has_braille_input_token(value):
            import re as _re
            tokens = _re.split(r"[^a-z0-9]+", str(value).lower())
            return (
                "space" in tokens
                or any(
                    token.startswith("dot")
                    and token[3:].isdigit()
                    and 1 <= int(token[3:]) <= 8
                    for token in tokens
                )
            )
        keyboard = (
            bool(kwargs.get("dots"))
            or bool(kwargs.get("space"))
            or any(has_braille_input_token(i) for i in ids if i)
        )
        if keyboard:
            # Braille keyboard input is typed text (possibly a password).
            return "keyboard", {
                "redacted": "braille-keyboard-input",
                "model": text(kwargs.get("model")),
                "source": text(kwargs.get("source")),
            }
        record = {}
        for name in ("id", "scriptPath", "source", "model", "routingIndex", "cellIndexes"):
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
        if action is None and (
            "routingIndex" in kwargs
            or "cellIndexes" in kwargs
        ):
            # Routing position is protocol-level data and is sufficient to
            # identify a routing gesture even when an older/newer peer omits
            # scriptPath metadata. Validation still happens before dispatch.
            action = "route"
        return action, record

    def _linux_rdaccess_trace_braille(self, record):
        import json as _json
        import os as _os
        if _os.environ.get("LINUX_RDACCESS_BRAILLE_TRACE") != "1":
            return
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
        elif action == "to_focus":
            self._linux_rdaccess_run_main(
                lambda: self._linux_rdaccess_script_call("goBrailleHome"))
        elif action == "route":
            index = kwargs.get("routingIndex")
            if index is None:
                cell_indexes = kwargs.get("cellIndexes")
                if (
                    isinstance(cell_indexes, (list, tuple))
                    and len(cell_indexes) == 1
                ):
                    index = cell_indexes[0]
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
        send = self.local_machine.send_key
        held_modifiers = (
            ("Shift_L", 0xA0, False),
            ("Alt_L", 0xA4, False),
        )
        pressed_modifiers = []
        try:
            for name, mod_vk, mod_ext in held_modifiers:
                send(
                    key_name=name, pressed=True, modifiers=None,
                    vk_code=mod_vk, scan_code=0, extended=mod_ext)
                pressed_modifiers.append((name, mod_vk, mod_ext))
            for down in (True, False):
                send(
                    key_name=str(key).lower(),
                    pressed=down,
                    modifiers=None,
                    vk_code=vk,
                    scan_code=0,
                    extended=False,
                )
        finally:
            for name, mod_vk, mod_ext in reversed(pressed_modifiers):
                try:
                    send(
                        key_name=name, pressed=False, modifiers=None,
                        vk_code=mod_vk, scan_code=0, extended=mod_ext)
                except Exception:
                    log.exception(
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
            log.exception("linux-rdaccess: native structural list failed")

        # Adapter unavailable or this Orca version does not expose the object.
        # Fall back to the verified Orca 42 Alt+Shift+letter binding.
        self._linux_rdaccess_send_structural_list(key, modifiers)

    def _linux_rdaccess_show_elements_list(self, modifiers):
        try:
            from linux_rdaccess_orca_adapter import show_elements_list as _show
            result = _show(lambda key: self._linux_rdaccess_open_structural_list(key, modifiers))
            if result is not None:
                # True: category selected and delegated to Orca.
                # False: the dialog was intentionally cancelled/Escaped.
                return
        except Exception:
            log.exception("linux-rdaccess: elements list failed")

        # Safe fallback only when the chooser could not be presented.
        self._linux_rdaccess_open_structural_list("h", modifiers)

    @staticmethod
    def _linux_rdaccess_script_call(method, *args):
        """Run an Orca operation through the linux-rdaccess Orca API adapter.

        The adapter keeps Orca-version compatibility in one place and delegates
        to the active application script, preserving Orca's GTK/web/terminal
        semantics. A direct fallback keeps older installs functional if the
        adapter file cannot be imported.
        """
        try:
            from linux_rdaccess_orca_adapter import OrcaRuntimeAdapter as _adapter
            if method == "panBrailleLeft":
                _adapter.pan_braille_left()
                return
            if method == "panBrailleRight":
                _adapter.pan_braille_right()
                return
            if method == "processRoutingKey" and args:
                _adapter.route_braille(args[0].event["argument"])
                return
            if method == "goBrailleHome":
                _adapter.to_braille_focus()
                return
            if method == "bypassNextCommand":
                _adapter.bypass_next_command()
                return
            if method == "whereAmI":
                _adapter.where_am_i()
                return
            if method == "presentTitle":
                _adapter.present_title()
                return
            if method == "presentStatusBar":
                _adapter.present_status_bar()
                return
            if method == "togglePresentationMode":
                _adapter.toggle_presentation_mode()
                return
            if method == "toggleStructuralNavigation":
                _adapter.toggle_structural_navigation()
                return
            if method == "sayAll":
                _adapter.say_all()
                return
            _adapter.call_script(method, *args, default_event=method.startswith("pan"))
            return
        except ImportError:
            pass
        except Exception:
            log.exception("linux-rdaccess: Orca adapter %s failed", method)
            return

        try:
            from orca import orca_state as _state
            script = getattr(_state, "activeScript", None)
            if script is None:
                script = getattr(_state, "active_script", None)
            if script is None:
                return
            if method == "toggleStructuralNavigation":
                nav = getattr(script, "structuralNavigation", None)
                if nav is None:
                    nav = getattr(script, "structural_navigation", None)
                handler = getattr(nav, "toggleStructuralNavigation", None) if nav is not None else None
                if not callable(handler) and nav is not None:
                    handler = getattr(nav, "toggle_structural_navigation", None)
                if callable(handler):
                    handler(script, None)
                return
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
                    handler(None)
                return
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
            log.exception("linux-rdaccess: D landmark translation failed")
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
    "                with open(_p, \"a\") as _f:\n"
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
    "def _linux_rdaccess_wrap_reset(name):\n"
    "    original = getattr(RemoteController, name, None)\n"
    "    if original is None:\n"
    "        return\n"
    "    def wrapper(self, *args, **kwargs):\n"
    "        try:\n"
    "            self._linux_rdaccess_reset_keys()\n"
    "        finally:\n"
    "            self._lrd_state = None\n"
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


LOCAL_MACHINE_MARKER_V1 = "# linux-rdaccess low-latency XTest key injection"
LOCAL_MACHINE_MARKER_V2 = LOCAL_MACHINE_MARKER_V1 + " v2"
LOCAL_MACHINE_MARKER_V3 = LOCAL_MACHINE_MARKER_V1 + " v3"
LOCAL_MACHINE_MARKER = LOCAL_MACHINE_MARKER_V1 + " v4"
LEGACY_LOCAL_MACHINE_RELATIVE = Path("orca-scripts/local_machine.py")

# Upstream writes every key name (including typed passwords) to a debug log,
# opening the file twice per key event. Silence it unless explicitly enabled.
_DBG_RE = re.compile(r"^def _dbg\(msg\):\n", re.MULTILINE)
_DBG_GUARD = (
    "    if not __import__(\"os\").environ.get(\"LINUX_RDACCESS_DEBUG\"):\n"
    "        return  # linux-rdaccess: no per-keypress file logging by default\n"
)


def _silence_dbg(text: str) -> str:
    match = _DBG_RE.search(text)
    if match is None or "linux-rdaccess: no per-keypress" in text:
        return text
    return text[:match.end()] + _DBG_GUARD + text[match.end():]


_XTEST_HELPER = '''

''' + LOCAL_MACHINE_MARKER + '''
# Upstream starts one `xdotool` process per key event (~38 ms each, measured),
# serially on the receive thread, so key bursts queue up and NVDA feels
# "chunky". Inject through XTest in-process instead (~0.004 ms); fall back to
# upstream's xdotool path for anything we cannot map.
class _LrdXTest:
    def __init__(self):
        self._lock = __import__("threading").Lock()
        self._x11 = None
        self._xt = None
        self._dpy = None
        self._down_codes = {}
        self._failed = False

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

    def key(self, name, pressed):
        """Return True when the event was injected."""
        if self._failed or not name:
            return False
        with self._lock:
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
                        return False
                    sym = self._x11.XStringToKeysym(encoded_name)
                    code = self._x11.XKeysymToKeycode(self._dpy, sym) if sym else 0
                if not code:
                    return False
                if not self._xt.XTestFakeKeyEvent(self._dpy, code, 1 if pressed else 0, 0):
                    if not pressed:
                        # Upstream fallback will handle this release; forget
                        # the held mapping so the next fresh press can resolve
                        # against the current keyboard layout.
                        self._down_codes.pop(name, None)
                    return False
                if pressed:
                    self._down_codes[name] = code
                else:
                    self._down_codes.pop(name, None)
                self._x11.XFlush(self._dpy)
                return True
            except Exception:
                self._failed = True  # missing libs / no display: use xdotool
                return False


_LRD_XTEST = _LrdXTest()


def _lrd_call_on_main(func, *args, **kwargs):
    """Run func on the GLib main loop (GTK is not thread-safe)."""
    try:
        from gi.repository import GLib
    except Exception:
        return func(*args, **kwargs)
    GLib.idle_add(lambda: (func(*args, **kwargs), False)[1])
'''

_XDOTOOL_DEF_RE = re.compile(r"^    def _send_key_xdotool\(self, key, pressed\):\n", re.MULTILINE)
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


def patch_legacy_orca_local_machine(path: Path) -> bool:
    """Make key injection low-latency and stop per-keypress file logging.

    Idempotent; one-time backup; verified to compile; atomic write.
    """
    text = path.read_text(encoding="utf-8")
    if LOCAL_MACHINE_MARKER in text:
        return False
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    if LOCAL_MACHINE_MARKER_V1 in text:
        if not backup.exists():
            raise ValueError(f"older patch found but backup is missing: {backup}")
        text = backup.read_text(encoding="utf-8")
    match = _XDOTOOL_DEF_RE.search(text)
    if match is None:
        raise ValueError(f"legacy _send_key_xdotool was not found in {path}")
    text = text[:match.end()] + _XDOTOOL_HOOK + text[match.end():]
    clip = _CLIPBOARD_DEF_RE.search(text)
    if clip is not None:
        text = text[:clip.end()] + _CLIPBOARD_HOOK + text[clip.end():]
    text = _silence_dbg(text)
    text = text.rstrip("\n") + "\n" + _XTEST_HELPER
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


def patch_legacy_orca_remote_controller(path: Path) -> bool:
    """Patch legacy Orca Remote input handling for NVDA compatibility.

    Returns True when the file changed. The patch is idempotent, replaces an
    earlier v1-v4 patch from the one-time .linux-rdaccess-backup, verifies the
    result compiles before writing, and writes atomically.
    """
    text = path.read_text(encoding="utf-8")
    if LEGACY_COMPAT_MARKER in text:
        return False
    backup = path.with_name(path.name + ".linux-rdaccess-backup")
    old_marker = next(
        (
            marker
            for marker in (
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
    text = text.rstrip("\n") + "\n\n\n" + _LEGACY_SLOW_EVENT_HOOK
    text = text.rstrip("\n") + "\n\n\n" + _LEGACY_ORCA_D_HOOK.strip("\n") + "\n"
    text = _silence_dbg(text)

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
