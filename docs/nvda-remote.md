# NVDA Remote + Orca Remote backend

This document records the preferred accessibility path for `linux-rdaccess`.

## Why this is the preferred path

Traditional RDP transports pixels and input. A Windows screen reader therefore sees the RDP client window rather than Linux AT-SPI objects.

NVDA Remote already provides a mature bidirectional transport for:

- keyboard input
- speech
- braille
- connection state

Orca can provide the Linux accessibility layer. Using Orca Remote between the two avoids making xrdp responsible for accessibility semantics.

## Tested topology

```text
Windows PC
  NVDA 2026.x
  Remote Access: Host locally
  TCP 6837
        ⇅
Linux Mint / XFCE
  Orca 42
  Orca Remote
  AT-SPI
        ⇅
Linux applications
```

A LAN-hosted Remote Access session has been validated with:

- Windows NVDA entering remote-control mode
- Windows keyboard input controlling Linux applications
- Linux Orca output spoken by NVDA
- Linux braille output displayed through the Windows NVDA braille display
- local Orca speech suppressed while the Linux machine is remotely controlled

## Compatibility findings

### Orca 42 speech API

Older Orca Remote code may use:

```python
SpeechServer.speak_character
```

Orca 42 uses:

```python
SpeechServer.speakCharacter
```

Compatibility code must account for that difference.

### Auto-connect sentinel

Install-time placeholder replacement must not accidentally rewrite the logic used to decide whether a real server/key has been configured.

### TLS relay behavior

The public relay at `nvdaremote.com:6837` may reject the older Linux TLS stack used by some distributions. A LAN-hosted Remote Access session on the Windows NVDA machine is a reliable alternative and removes the public relay from the path.

### X11 keyboard injection

On XFCE/X11, Orca Remote can inject received NVDA key events with `xdotool keydown` / `keyup`. The Linux session must have a focused application window; if only the desktop/panel is active, Tab may appear to do nothing.

### Braille forwarding

NVDA Remote expects raw braille cells as integers from 0 to 255. Orca 42 normally renders text through BRLTTY rather than exposing the final remote-cell stream directly.

A compatible bridge can:

1. hook Orca's braille refresh path,
2. read the currently visible braille line,
3. translate it using Liblouis with `dotsIO | ucBrl`,
4. convert Unicode braille patterns `U+2800..U+28FF` to raw cell values,
5. send those values in an NVDA Remote `display` message.

## Speech behavior

When Linux is the controlled endpoint, local Orca speech and NVDA speech should not both play.

The preferred behavior is:

- generate speech through Orca as usual,
- forward it to NVDA Remote,
- suppress the final local Orca audio call while the remote connection is active,
- restore normal local Orca speech when disconnected.

This keeps NVDA as the user's speech output while preserving Orca as the Linux accessibility engine.

## Relationship to the xrdp backend

The xrdp DVC implementation remains in this repository. It is useful for research into:

- native RDP accessibility transport
- reconnect/session lifecycle
- automatic RDP-session discovery
- richer AT-SPI object serialization
- possible future interoperability beyond NVDA Remote

It should be treated as an experimental backend, not deleted.
