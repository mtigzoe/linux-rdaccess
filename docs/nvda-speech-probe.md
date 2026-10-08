# Windows NVDA speech probe for live tests

This optional probe lets a Codex session running in the Linux Remote-SSH
workspace confirm that Windows NVDA actually queued speech after a Linux action.

It is intentionally separate from normal linux-rdaccess operation:

- disabled by default;
- no speech is written to disk;
- the Linux receiver binds only to loopback;
- Windows sends only to 127.0.0.1:8765;
- the connection is carried through the existing SSH session with LocalForward;
- exact speech is hidden unless --show-text is explicitly requested.

Because NVDA can speak passwords or typed characters depending on the user's
settings, enable this probe only for a controlled test and disable it afterward.

## 1. Add the SSH local forward

In the Windows OpenSSH config entry that VS Code Remote-SSH uses for the Linux
Mint machine, add:

    LocalForward 8765 127.0.0.1:8765

Reconnect the VS Code Remote-SSH session after changing the SSH config.

The Windows side of that tunnel is 127.0.0.1:8765; it is forwarded securely
inside SSH to 127.0.0.1:8765 on Linux.

## 2. Install the NVDA diagnostic add-on on Windows

From a Windows checkout or copy of this repository:

    powershell -ExecutionPolicy Bypass -File .\tools\nvda\install_nvda_speech_probe.ps1

Restart NVDA.

For a portable or non-default NVDA configuration, pass its configuration
directory explicitly with -NvdaConfigPath.

The add-on is a diagnostic helper only. It does not depend on the rdAccess add-on
or xrdp.

## 3. Start the Linux receiver

Metadata only:

    python3 diagnostics/nvda/nvda_speech_probe.py

For a controlled test where Codex needs to verify the actual announcement:

    python3 diagnostics/nvda/nvda_speech_probe.py --show-text

A one-event test is also available:

    python3 diagnostics/nvda/nvda_speech_probe.py --show-text --once

No output file is created.

## 4. Enable capture from Windows NVDA

Press:

    NVDA+Ctrl+Shift+F12

NVDA announces that the Linux RDAccess speech probe is enabled. That confirmation
announcement itself is intentionally not forwarded.

Now perform one remote Linux test. The Linux receiver prints a JSON event when
NVDA queues speech. With --show-text, the text field contains the spoken
sequence's string content. Speech commands such as pitch, language, and index
changes are not serialized.

Press NVDA+Ctrl+Shift+F12 again immediately after the test to disable capture.

## What this proves

A received event proves that Windows NVDA queued a speech sequence. It is
stronger evidence than observing only Linux AT-SPI or Orca output.

It does not prove that the audio device physically emitted sound. Synthesizer or
audio-device failures occur after NVDA's pre_speechQueued extension point.

For linux-rdaccess compatibility testing this gives a useful chain:

    remote key
    -> Linux X11
    -> AT-SPI / Orca
    -> NVDA Remote speech message
    -> Windows NVDA queued speech

## Privacy

Do not leave --show-text and the Windows probe enabled during ordinary computer
use. NVDA speech can contain sensitive content.

The add-on never writes speech to a file. If the Linux listener is absent, the
event is dropped. The sender uses a bounded queue and short socket timeouts so a
missing SSH tunnel cannot block NVDA speech.

Uninstall from the same Windows checkout:

    powershell -ExecutionPolicy Bypass -File .\tools\nvda\install_nvda_speech_probe.ps1 -Uninstall

Restart NVDA afterward.
