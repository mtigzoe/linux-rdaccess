# NVDA/Orca event-boundary compatibility audit, October 8, 2026

Started from fetched `origin/main`, `772e27d` (merged PR #35), on
`fix/nvda-orca-event-boundaries-20261008`. Reviewed PRs #31–#35, the
compatibility matrix, test infrastructure, and the previous overnight audit.
Preserved the browser find mappings, GI accessors, Windows MCP configuration,
braille held-key ownership, and semantic focus lifetime guards.

All investigation used test doubles, disposable source copies, loopback TCP,
private Xvfb/D-Bus sessions, and temporary application profiles. No active
Orca/NVDA session, installed runtime/configuration, desktop keyboard lock state,
or physical braille display was changed. The temporary Python 3.12 interpreter
was installed under `/tmp`, without changing system Python.

## Confirmed defects

### Outgoing relay packets could cross a reconnect boundary

The pinned Orca Remote `send()` serialized a packet before inspecting the
current connection, then enqueued without coordinating with `_disconnect()`.
Two independently reproduced schedules caused stale output:

1. Pause serialization; disconnect and establish a replacement connection;
   finish serialization. Old speech, display, focus, or cancellation packets
   enter the replacement peer's queue.
2. Pause an accepted enqueue; disconnect clears the queue; complete the enqueue.
   The supposedly cleaned queue contains an old packet for the next sender.

The correction captures the socket and an output lifetime before serialization,
then validates them before enqueue. A separate output lock serializes enqueue
with disconnect cleanup. It deliberately does not acquire the connection lock:
connection callbacks already acquire controller input locks, and a controller
input callback can send cancellation. Reusing the connection lock here would
introduce a lock-order deadlock.

The output hook has its own verified marker. Genuine pre-fix v7 output from
`772e27d` is frozen as `transport-v7.txt`; upgrade, backup preservation,
idempotency, unknown send implementations, and patch tampering are checked.
Existing receive framing, size bounds, pending-connect ownership, and native
sender cleanup remain covered. Wire messages and serialization are unchanged.

### Legacy named modifiers had incorrect speech and pass-next semantics

Name-only events were correctly injected and owned, but decisions about
modifiers inspected only numeric VK codes. Consequently:

- `Control_L`/`Control_R` stopped local speech but sent no immediate NVDA
  cancellation, so Windows speech already queued could continue.
- Name-only Shift, Alt, and Super were treated as ordinary actions and stopped
  local speech/Say All.
- Pressing a named modifier alone used up pass-next before the intended key.

Recognize a fixed vocabulary of modifier key names for these decisions when
VK metadata is absent. An explicit VK remains authoritative. The injected key
payload and release identity retain their original name-only representation;
the #35 braille ownership comparison is unchanged. Controller patch v103
upgrades v102 and earlier through the existing backup mechanism.

### Caret routing could report success without moving a provider caret

After a setter exception, or when no setter existed, `set_caret_offset()`
assigned `iface.caretOffset` and returned success. On an ordinary Python/GI
wrapper this can create a local attribute without performing an AT-SPI call.
It could also retry a failed operation through a different property setter.

A failed provider method now returns failure immediately. The legacy property
fallback is restricted to a real writable Python property. Valid snake-case,
camel-case, and writable-property paths remain supported. Actual application
checks confirm that successful routing is visible through the provider's
caret query, rather than trusting the method result alone.

[AT-SPI's setter contract](https://docs.gtk.org/atspi2/method.Text.set_caret_offset.html)
defines a Boolean success result and a recoverable error; assigning an unrelated
wrapper field does not satisfy that operation.

## Regression evidence

Added 17 unittest methods: four caret-setter cases, seven transport lifetime and
upgrade cases, three speech cases, one pass-next modifier matrix, and two TCP
loopback regressions. Extended the controller upgrade matrix through v102.

Copied the new regression files into a disposable `git archive 772e27d` tree,
leaving its production implementation untouched. Eleven selected methods ran
and produced 21 assertion failures, including subtests:

| Area | Original failure evidence | Corrected behavior |
| --- | --- | --- |
| Relay output lifetime | Five unit failures across serialization/queue races; loopback receives `old-session` speech before the fresh utterance. | Six failures corrected; the fresh peer receives only `new-session` speech. |
| Named modifiers | Eleven unit subtest failures; loopback receives `[]` instead of two `cancel` messages. | Twelve failures corrected; fresh Ctrl presses cancel once each, other modifiers preserve speech, and pass-next survives the modifier. |
| Caret setter | Three failures: `True is not false`, including no setter and a failed setter followed by property fallback. | Failure is reported and no fake caret attribute/property operation occurs. The valid legacy property case passes before and after. |

Original evidence is in `/tmp/rdaccess-events-original-regressions.log`;
the disposable source tree is `/tmp/rdaccess-events-original-rn5GQA`.
Earlier focused reproductions are in `/tmp/rdaccess-events-caret-before.log`,
`/tmp/rdaccess-events-send-before.log`, and
`/tmp/rdaccess-events-named-modifier-before.log`.
These are local evidence files; the regressions and assertions are committed.

## Private application coverage

Expanded the existing runner from 43 to 57 checks on this Linux Mint host.
Settings search, Mousepad, Firefox, and VS Code now verify the Linux model's
caret setter against the provider's resulting caret, and verify semantic text
selection after Ctrl+A. Firefox also replaces a focused DOM button and checks
the replacement's identity, name, and focus state in the model snapshot.

Existing Thunar selected rows, Terminal output/menu navigation, Settings
controls, dialogs, clock popup, browser URL-bar return, and VS Code command
palette/focus return checks continue to pass. The GTK gallery separately covers
menus, lists/tables, values, text/caret/selection, and modal focus restoration.

Clock keyboard activation and calendar selected-date semantics remain explicitly
reported provider limitations. Pointer opening and Escape dismissal do not
establish keyboard date-navigation support.

## Final validation

| Check | Exact result |
| --- | --- |
| System Python 3.10.12, full headless discovery | 1,227 tests; no failures/errors; 19 private-X11 skips. |
| System Python 3.10.12, full private Xvfb discovery | 1,227 tests; no failures/errors; zero skips. Includes actual XTest and lock-state tests. |
| Temporary Python 3.12.13, full headless discovery | 1,209 tests; no failures/errors; 31 skips. |
| Temporary Python 3.12.13, full private Xvfb discovery | 1,209 tests; no failures/errors; 12 native-dependency skips. |
| Focused NVDA Remote TCP loopback, Python 3.10 | 17 tests passed; zero skips. Included in full discovery. |
| GTK/AT-SPI gallery | 38 checks passed; 57 accessibility events. |
| All seven real Linux applications | 57 checks passed; 237 accessibility events; no application skips. |
| Current rdAccess main `7bfc0c86aa97044e044558d9cac24f9ba39c9d08` | Seven producer/consumer contracts passed on both Python 3.10 and 3.12. Reverse action and heartbeat checks also passed on Python 3.10. |
| Compilation and Python 3.10 grammar | Passed; 148 Python files parsed. |
| Ruff 0.16.10, E9/F821/F822/F823 | Passed; partial native fixtures excluded from name analysis. |
| Shell syntax and diff whitespace | Passed. |

Python 3.12 lacks native GI and Liblouis bindings: ten native Liblouis cases and
two module-level GI skip records account for its 12 dependency skips. Nineteen
additional X11 cases skip headless. GI module discovery produces fewer test
records on 3.12, explaining the different totals. Those dependencies are
available in the system 3.10 run, which passes every discovered test under
Xvfb. Skipped 3.12 cases are not claimed as 3.12 coverage. Focused totals overlap
full discovery and should not be added to it.

Principal commands, run from the repository root:

```sh
env -u DISPLAY -u WAYLAND_DISPLAY python3.10 -m unittest discover -s tests -t . -v
env -u DISPLAY -u WAYLAND_DISPLAY xvfb-run -a python3.10 -m unittest discover -s tests -t . -v
python3.10 -m unittest -v tests.integration.test_nvda_remote_loopback
env -u DISPLAY -u WAYLAND_DISPLAY -u AT_SPI_BUS_ADDRESS -u DBUS_SESSION_BUS_ADDRESS python3.10 tools/diagnostics/gtk_atspi_smoke.py
env -u DISPLAY -u WAYLAND_DISPLAY -u AT_SPI_BUS_ADDRESS -u DBUS_SESSION_BUS_ADDRESS python3.10 tools/diagnostics/real_gui_atspi_smoke.py
```

Full logs use `/tmp/rdaccess-events-{headless,xvfb,python312-headless,python312-xvfb}.log`;
GUI logs use `/tmp/rdaccess-events-{gtk,real-gui}.log`. Cross-repository logs use
`/tmp/rdaccess-events-contracts.log` and `/tmp/rdaccess-events-contracts312.log`.

## Files changed

- `linux_rdaccess_core/accessibility/a11y_model.py`: caret setter failure handling.
- `linux_rdaccess_core/connection/remote_access.py`: relay output lifetime hook,
  modifier classification, and upgrade recognition.
- `tests/unit/accessibility/test_caret_setter_failures.py` and
  `test_speech_lifecycle.py`: setter and named-modifier regressions.
- `tests/unit/transport/test_transport_send_lifetime.py`: deterministic races,
  lock ordering, and upgrade/negative tests.
- `tests/unit/input/test_pass_next.py` and
  `tests/unit/braille/test_braille_protocol.py`: modifier and upgrade coverage.
- `tests/integration/test_nvda_remote_loopback.py`: both wire-level regressions.
- `tests/fixtures/legacy-patches/transport-v7.txt` and its `README.md`: genuine
  historical transport fixture and provenance.
- `tools/diagnostics/real_gui_atspi_smoke.py`: 14 additional real-provider checks.
- This audit.

## Remaining gaps and deferred live acceptance

No further defect is claimed from the reviewed display-width, partial/malformed
receive, semantic focus, GI query, or native Say All continuation paths. Their
existing regression suites remain passing. This investigation used deterministic
race schedules, fault injection, negative cases, modifier event matrices,
original-versus-fixed comparison, real-provider checks, and cross-version runs;
it does not establish exhaustive event-sequence coverage.

Windows NVDA gesture consumption and audible output, TLS/real relay latency,
physical display pan/routing/translation, and Wayland remain unverified here.
Named events retain the existing legacy command translation limits; this change
only repairs speech/pass-next modifier decisions. Same-focus text revisions
are not versioned in the semantic protocol. Unsupported review/navigator and
braille typing commands remain subject to the compatibility matrix.

For the later live session, check:

1. Ctrl interruption during Say All and typing, including a legacy named-key
   peer if available; Shift/Alt alone should preserve speech.
2. Pass-next followed by Shift/Ctrl/Alt and the intended application shortcut;
   verify one complete gesture passes and normal navigation resumes.
3. Disconnect/reconnect while speech or braille output is queued; no old speech,
   focus, cells, or cancellation should affect the new session.
4. Insert/Caps Lock desktop/laptop commands, Num Lock/keypad behavior, held
   modifiers, and missing key-ups across reconnect.
5. Physical 40/80-cell pan, route, selection/caret tracking, display reconnect,
   and braille navigation while holding a keyboard key/modifier.
6. Preserved NVDA browser find/F3/F7 mappings, browse/focus transitions, dynamic
   controls, and dialog focus return in the tested applications.
