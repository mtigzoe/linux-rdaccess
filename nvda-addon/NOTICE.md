# Source and licensing

The Windows companion is GPL-2.0-or-later. See `COPYING.txt`. This directory's
license is separate from the Apache-2.0 license of the Linux project.

The consent service, Remote Access adapter, semantic braille bridge, accessibility
object model, and associated tests are extracted from
[mtigzoe/rdAccess](https://github.com/mtigzoe/rdAccess), originally RDAccess by
Leonard de Ruijter <alderuijter@gmail.com> and contributors. Existing source
copyright and license notices are retained. Extraction and adaptations were
made on 2026-10-12 by linux-rdaccess contributors.

Source baseline: rdAccess main after PR #10 (`9cd3593`), plus the optional
NVDA braille command compatibility correction from
[PR #12](https://github.com/mtigzoe/rdAccess/pull/12) (`f7ac812`) and Linux
focus-context/buffer recovery from
[PR #13](https://github.com/mtigzoe/rdAccess/pull/13)
(`ebb4c050f6838bf5252601736092afc5dc020b2c`). The latter correction is
automated-tested; its physical braille panning outcome remains unverified.

Adaptations remove RDP/DVC handlers, DLL registration, synth/display drivers and
general RDAccess settings. Imports now resolve within `linuxRdAccess`.
The entry point defers activation until NVDA has initialized its plugins and
declines ownership when a running RDAccess development plugin still provides
the Linux integration. No add-on is automatically disabled or uninstalled.

The four original IPC wire modules are not duplicated in this directory. `build.py`
packages their authoritative sources from
`linux_rdaccess_core/connection/nvda_test_client/`. They retain the original
GPL-2.0-or-later licensing and are included in the companion under that license.
The additional `localTestRoutingTrace.py` is project-authored, licensed under
GPL-2.0-or-later, and packaged from the same authoritative source directory.
The distribution includes readable Python source, this notice, and the complete
license. It does not contain NVDA source, binaries, relay keys, or user data.
