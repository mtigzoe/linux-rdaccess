# Routing before NVDA's pending braille refresh — 2026-10-13

Related: physical braille issue #59; temporary-message lifecycle #72.
Base: `main` **7c21b45**. New companion build: **20261013.0.3**.

## Live symptom, with separate evidence layers

With companion .2, Linux controller v120 from PR #82 and Orca 42.0-1ubuntu2,
the user confirmed readable Mousepad text in NVDA speech and on a Eurobraille
b.note. A fresh authenticated check reported connected transport, an attached
bridge, negotiated semantic braille and active Linux control. No agent
desktop input or Desktop Commander was used.

During a bounded 60-second read-only AT-SPI observation, Mousepad's focused
editor stayed at caret **21**, with no caret events or focus changes. The user
confirmed pressing one routing key aligned with the start of the second word
during that window and seeing the physical braille cursor move there. Linux's
editing caret did not follow. The exact document text was not captured; its
end offset 21 differs from the requested `alpha bravo charlie` length 19.
Control was verified before the observer, not at the exact keypress, and no
Windows route-request telemetry was captured. The runtime cause of that
specific physical observation is therefore not established.

The [numeric observation](https://github.com/mtigzoe/linux-rdaccess/blob/997ff9b267691367e90c35f9d586728f102cf026/docs/mousepad-routing-atspi-evidence-2026-10-13.json)
and [layered report](https://github.com/mtigzoe/linux-rdaccess/blob/997ff9b267691367e90c35f9d586728f102cf026/docs/mousepad-routing-layered-evidence-2026-10-13.json)
record physical cursor movement and failed Linux caret synchronization
separately. They do not certify general routing, speech or braille acceptance.
Driver, firmware, contraction mode and display width remain unverified.

## Independently reproduced timing defect

The companion rebuilds semantic objects for each accepted focus snapshot,
invalidates the previous objects' action/caret senders and rebinds existing
same-ID regions to the new object. NVDA's `handleUpdate` and `handleCaretMove`
defer the actual region update until `_handlePendingUpdate` runs. The region's
cached reading TextInfo can consequently still belong to the old snapshot.
A local routing script queued before that idle refresh reaches the invalidated
sender and silently sends no caret request.

The regression uses NVDA's actual deferred-update methods from the sibling
source checkout **1406f9f**, with isolated presentation dependencies, and
the production remote TextInfo caret setter. It reproduces the gap for both
same-ID refresh and changed caret. It does not perform real braille translation
or send a physical gesture. A separate disposable harness also executes the
installed NVDA 2026.2 `braille.pyc` update methods against these test stubs.
Installed bytecode SHA-256:
`988b977c3e3286727070136c6b8f9b11a4046fed0e1eb10a64ca59f1712a2d12`.
It neither imports the running NVDA session nor injects code into it.

## Fix and checks

The existing queued recovery callback now runs NVDA's normal pending braille
update before the local coordinate script. It does so only for the current
connected session/control generation, while remote control is active and the
display uses the semantic main buffer. Temporary-message buffers skip this
refresh. Rendering and window handling stay in NVDA's own update method;
retained old TextInfo remains invalid. This also affects other already-local
coordinate commands such as panning and line navigation, which need live
acceptance alongside routing.

- Pre-fix source-backed routing regression: **one expected failure**, no
  semantic caret request sent.
- Pre-fix recovery method with installed NVDA update bytecode: **two expected
  routing failures**, five lifecycle checks pass.
- Fixed seven focused checks: **all pass** with source methods and independently
  with installed bytecode. They cover refresh before routing, old-sender
  rejection, window preservation, message buffers, local control, disconnection,
  stale sessions and stale control generations.
- Full Windows companion suite under Python 3.13 with documented
  `configobj==5.0.9`: **210 tests pass**, including Windows kernel/IPC tests.
  An earlier plain Python 3.14 run had one import error because `configobj`
  was missing (206 tests passed); it was not a complete suite PASS.
- After the version change, all **four packaging tests pass**. Ruff 0.16.4
  checks/format validation pass. No unrelated files were reformatted.

The prepared package has 17 entries, 13 compilable Python files and 47,399 bytes.
Its deterministic rebuild matches SHA-256
`8c4618a90803a38499542b2ac17e2c9b3130ab89c4ef3a8caa41fc999cb200a6`.
Compared with .2, only the manifest, help document and semantic bridge module
change. Linux controller v120, saved settings and IPC permissions are untouched.

## Pending physical acceptance

Build .3 has **not been installed or tested on the b.note**. The fix resolves
the reproduced timing defect, but its effect on the live mismatch needs a
controlled retest after user-approved installation/restart and fresh test
authorization. Use a verified public fixture, one routing key, synchronized
Linux caret observation and separate user confirmation. Retest panning and
temporary-message dismissal/restoration; no new physical PASS is claimed.
Keep #59 and #72 open. No GitHub Actions polling or merge is performed.
