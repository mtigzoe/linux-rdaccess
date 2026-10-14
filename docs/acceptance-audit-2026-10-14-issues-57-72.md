# Acceptance audit: issues #57 and #72 — 2026-10-14

Audited `main` at **f247d771e6b522f5fec8bde0c31eb7f928d0d42d**, after fetching
origin. The worktree was clean; no PR was open. The issue bodies and every
comment were read, together with merged PRs #82–#86 and their implementation,
tests and historical audits. Other worktrees were left untouched.

**#57: NOT READY. #72: NOT READY.** Both are live-validation issues. Successful
automation establishes the tested contracts, not complete Windows speech,
remote keyboard or physical b.note acceptance. Neither issue should close on
this evidence. Issue #59 remains independently open for ordinary physical
routing. No issue was closed or PR merged during this audit.

## Evidence labels and scope

- **Confirmed live PASS** means a specifically described human-operated
  observation; an older-build or partial observation does not accept the
  current build's whole criterion.
- **Automated PASS only** means the named regression passed in the runs below.
- **Confirmed failure** identifies historical observed behavior or a reproduced
  defect; it does not imply that the latest build still fails.
- **Not tested** means no adequate evidence exists for that particular check.
- **Unsupported or intentionally different** identifies a documented behavior
  gap, not an invented equivalent or a passing live test.

Abbreviations in the matrices identify source files, not additional uncounted
runs:

| ID | Source/test evidence |
| --- | --- |
| K | [`test_remote_access.py`](../tests/shared/test_remote_access.py), [`test_compat_lifecycle.py`](../tests/shared/test_compat_lifecycle.py): generated production controller, mock runtime/injection leaves; 305 tests |
| B | [`test_browser_command_context.py`](../tests/unit/accessibility/test_browser_command_context.py): actual installed Orca gates/keyboard method excerpts where specified, otherwise fake script/events |
| I | [`tests/unit/input`](../tests/unit/input): direct commands, layout/keypad, Insert deferral, pass-next, capture, release/list ownership, upgrades, payload validation and private trace tests |
| E | [`test_elements_focus.py`](../tests/unit/accessibility/test_elements_focus.py), [`test_native_list_lifetime.py`](../tests/unit/accessibility/test_native_list_lifetime.py), [`test_structural_list_ownership.py`](../tests/unit/input/test_structural_list_ownership.py) |
| W | [`test_nvda_remote_loopback.py`](../tests/integration/test_nvda_remote_loopback.py): real isolated TCP/relay/serialization, fake controller runtime providers |
| M | [`test_semanticBrailleMessageRestoration.py`](../nvda-addon/tests/test_semanticBrailleMessageRestoration.py): actual NVDA message/routing/panning methods compiled from pinned source, fake buffers/timers/display |
| S | [`test_remoteAccessSemanticBraille.py`](../nvda-addon/tests/test_remoteAccessSemanticBraille.py): companion's real bridge, fake NVDA/Remote dependencies |
| O | [`test_routingOutcomes.py`](../nvda-addon/tests/test_routingOutcomes.py), recorder/session/transport/IPC companion tests: transparent outcomes, bounded consent, privacy and real isolated Windows kernel IPC |
| X | [`test_xtest_injection.py`](../tests/integration/x11/test_xtest_injection.py), [`test_lock_toggle_integration.py`](../tests/integration/x11/test_lock_toggle_integration.py), [`test_xkb_lock_state.py`](../tests/integration/x11/test_xkb_lock_state.py): actual private Xvfb/XTest/XKB, fake Orca presentation |
| P82 | [PR #82](https://github.com/mtigzoe/linux-rdaccess/pull/82), [typing audit and limited live follow-up](compatibility-audit-2026-10-13-non-web-letter-input.md) |
| P83 | [PR #83](https://github.com/mtigzoe/linux-rdaccess/pull/83), [pending-region audit](compatibility-audit-2026-10-13-pending-braille-routing.md) |
| P84 | [PR #84](https://github.com/mtigzoe/linux-rdaccess/pull/84), [restoration audit](compatibility-audit-2026-10-13-message-restoration.md) |
| P85 | [PR #85](https://github.com/mtigzoe/linux-rdaccess/pull/85), [visible-message report](compatibility-audit-2026-10-13-message-routing-timeout.md), [later mixed traces](compatibility-audit-2026-10-13-caret-trace.md) |
| P86 | [PR #86](https://github.com/mtigzoe/linux-rdaccess/pull/86), [outcome/rejection audit](compatibility-audit-2026-10-14-routing-outcomes.md) |

## Issue #57 acceptance matrix

Original issue: [NVDA keyboard commands and modifier ownership](https://github.com/mtigzoe/linux-rdaccess/issues/57).
Its acceptance allows correct NVDA-style behavior **or clearly documented gaps**,
but also requires live capture, activation and stray-input checks. The additional
application/navigation rows below implement the requested audit scope.

| Requirement | Classification and specific evidence | Still needed for acceptance |
| --- | --- | --- |
| NVDA+T / title | **Automated PASS only.** K `test_title_and_status_use_direct_orca_apis_without_keypad_sequences`; B current-activation/expiry tests. Adapter calls Orca `presentTitle`, not a time/date/keypad substitute. | Actual Windows title announcement, focused public Linux window, no stray `t`, in each intended layout/modifier configuration. |
| NVDA+1 toggles input help | **Confirmed live PASS, limited older-build observation.** P85's .5 follow-up records individually requested on/off gestures and user announcements; automation B `test_input_help_toggle_still_exits_and_fresh_commands_execute` and W `test_wire_input_help_toggle_respects_receive_and_dispatch_capture` passes. | Current loaded-build/session attribution and the separate command-description check below. No latest-build speech claim. |
| Command description without action during input help | **Automated PASS only.** B `test_direct_commands_describe_native_help_without_executing`, `test_input_help_describes_browse_commands_without_executing_them`, native description preferences and expired callbacks. | One harmless command in learn mode, Windows speech/braille description, unchanged Linux target. |
| NVDA+F7 in Linux Firefox | **Automated PASS only; intentionally different UI.** E, K `test_elements_list_prefers_native_orca_list_without_synthetic_keys`, B document/chrome/capture checks, W master-departure test. [`show_elements_list`](../linux_rdaccess_core/accessibility/orca_adapter.py) chooses Links/Headings/Form fields/Buttons/Landmarks, then delegates to Orca's structural list; if the chooser is unavailable, the controlled fallback is Headings. This is an equivalent entry point, not NVDA's Windows elements dialog or complete feature parity. | Public Firefox document: category, actual result list, Windows announcement, navigation/activation and cancellation. |
| Insert+N / NVDA menu | **Unsupported or intentionally different.** K `test_nvda_n_is_consumed_without_opening_unrelated_orca_preferences`, `test_capslock_nvda_n_is_consumed_without_toggling_capslock`. In Linux control the bridge suppresses the forwarded chord; it opens neither Orca preferences nor the Windows menu. Return to local Windows control to use NVDA's menu. | Human confirmation of that local-control sequence; do not call suppression a menu PASS. |
| Caps Lock as NVDA modifier | **Automated PASS only.** I Insert deferral/all-modifier-form tests; K Caps command tests; X `test_caps_lock_nvda_command_preserves_the_real_lock`, `test_all_nvda_modifier_forms_stay_out_of_x11_for_consumed_commands`. | Real configured Caps modifier command and subsequent ordinary input; no lock change/stuck modifier. |
| Caps Lock and Num Lock toggles/announcements | **Automated PASS only.** K lock state tests and X completed-release, repeat, extended-flag and rapid-toggle snapshots verify real private XKB state; presentation is fake. | Actual remote toggle and Windows status speech/braille for each lock, restoring initial state in separate user actions. |
| Desktop layout | **Automated PASS only for the full layout.** I `test_layout_keypad_gestures`, direct-command/Insert tests; K desktop collision tables. Prior input-help live observations cover only a small subset. | Record active runtime layout and modifier settings, then isolated commands; ordinary keypad/navigation distinction. |
| Laptop layout | **Automated PASS only.** I layout/keypad and B shifted-find tests exercise both layouts. Unsupported review gestures are consumed rather than substituted with Orca flat review. | Separately approved user layout change and isolated live laptop checks, with settings restored. |
| Browse versus focus mode | **Automated PASS only.** B `test_actual_orca42_gate_preserves_editable_and_browser_chrome_typing`, `test_deferred_browse_navigation_refuses_focus_mode`, native structural registration tests. | Firefox public page: mode announcement, page quick navigation, editable-field typing and browser chrome typing separately. |
| Pass-next-key | **Automated PASS only.** I `test_pass_next`, K NVDA+F2 direct bypass tests; ownership, release, one-shot and handoff checks. | One harmless bypassed application chord followed by one normal command; no duplicate or leaked modifier. |
| Direct commands during Orca shortcut-editor capture | **Automated PASS only.** B `test_native_shortcut_editor_receives_the_insert_or_capslock_chord`, `test_shortcut_capture_receives_direct_commands_and_their_modifiers`; W capture toggle. | Real shortcut editor receives the intended physical shortcut without executing the bridge action. Opening capture requires a separate approved human step. |
| Commands after capture exits | **Automated PASS only.** B `test_native_dispatcher_keeps_commands_working_after_capture_ends`, captured repeats/releases and capture-entry ownership tests. | Fresh command after exit and safe release of a key held across that transition. |
| Held keys, repeats and releases | **Automated PASS only.** I payload validation/Insert/pass-next/list ownership; B held browse/release tests; W fragmented keyboard and reconnect tests; X real server key/release/failed-release cases. | Actual NVDA Remote physical held modifier, repeat/release and no stuck key in Linux or Windows. |
| Queued commands across windows/scripts; no stray replacement-window action | **Automated PASS only.** B `test_queued_direct_commands_expire_on_script_or_window_activation_change`, same-script replacement-window, equal-instance, failed-window-read, capture and handoff expiry; E list lifetime. | Controlled public-window transition while an action is pending, with target identity and no unrelated action observed. |
| Tab and Shift+Tab | **Not tested to full acceptance.** The [companion audit](compatibility-audit-2026-10-13-companion.md) records live Windows-origin Firefox Tab/Shift+Tab delivery and role changes, but not a completely captured return; a user-reported announcement difference remains unresolved under #58. | One Tab, then a separately prompted Shift+Tab; original/returned Linux focus and actual Windows announcement. |
| Terminal character typing / P82 regression | **Confirmed live PASS, limited.** User confirmed entering `mousepad --disable-server`, including the previously suppressed `m`; Linux later showed Mousepad focused (P82). No exact key-time/control trace or echo proof. B's empty-model regressions and actual Orca base gate pass again. | Current-build isolated `m` and key echo if acceptance requires it; do not extrapolate to all characters or apps. |
| Character typing in Mousepad and Firefox | **Automated PASS only.** B empty navigation model, actual Orca base/web gates, edit/chrome/focus-mode tests; K ordinary input. Existing public Mousepad text is not proof of its input path. | A single public character per focused app, real application/caret readback and Windows echo report; Firefox edit/chrome distinct from browse navigation. |
| Insert+Alt+Tab local/remote handoff and modifier ownership | **Automated PASS only for the complete sequence.** K/I/W handoff/disconnect/generation reset, capture expiry and stale output tests; past authenticated statuses establish individual control states, not a fully correlated physical chord/release sequence. | Record state on each side of one human handoff; no stuck key, stale command or Linux takeover of local output. |

Ownership is deliberate: title/help/pass-next/browser commands use Linux Orca
APIs; ordinary typing and Tab belong to the application; Remote's control
handoff belongs to Windows. Windows-only NVDA commands must not be remapped to
unrelated Orca actions. The pinned NVDA Remote source's `processKeyInput` allows
registered local scripts, otherwise forwards raw keys during remote control;
its `_remoteClient/__init__.py` registers send-keys/SAS. The companion does not
register the NVDA menu as a local script. No indiscriminate shortcut-forwarding
change is proposed.

P82's ordinary-letter fix remains present. In a same-Python-3.10 AST comparison,
the installed `_lrd_maybe_suppress_browse`, key filter/wrapper and elements-list
method match generated current main. That is disk-source evidence, not loaded
runtime attestation. No new reproducible keyboard defect was found in this
audit. The earlier reports of absent `i`/speech echo are not explained by P82's
empty-registry suppression and must not be declared fixed by it.

## Issue #72 acceptance matrix

Original issue: [temporary braille message acceptance](https://github.com/mtigzoe/linux-rdaccess/issues/72).
The issue's historical body calls `mtigzoe/rdAccess#9` open. A fresh read shows
that PR **merged on 2026-10-12**; that metadata does not satisfy its physical
release gate. The independent companion now contains the relevant receiver.

| Original requirement / additional audit check | Classification and specific evidence | Still needed for acceptance |
| --- | --- | --- |
| Firefox focus/browse temporary messages | **Automated PASS only.** S `test_temporary_message_requires_negotiation_and_preserves_focus`; W `test_temporary_braille_message_is_sent_after_capability_over_wire`; K/B mode command mapping. | NVDA+Space in a public Firefox page, actual b.note status text and restored semantic line/cursor. |
| Caps Lock / Num Lock transient status and key state | **Automated PASS only.** X real XKB state, mocked status presentation; W message feature; K lock commands. | Each real remote lock toggle, exact public status on b.note and correct key state, then restore initial state. |
| Input-help message appearance | **Confirmed live PASS, limited on .4.** P85 records user's yes to appearance/restoration on b.note, plus Linux caret 6 before/after; exact wording/time were not captured. | Repeat on an attested current receiver with a short isolated action. |
| Input help plus a shortcut's expected braille description | **Automated PASS only for the full original item.** B help-without-execution and W semantic/raw help description tests. The appearance-only observation above does not accept shortcut wording. | Separately prompted harmless command while help is on, physical description and no application action. |
| Timeout follows NVDA settings; original line/caret returns | **Automated PASS only for configured timing.** M `test_message_timeout_restores_linux_when_windows_replaced_main_buffer`, `test_message_timeout_restores_linux_when_windows_replaces_buffer_while_visible`, retained-current-snapshot test. The .4 appearance/return observation is a limited physical restoration PASS, not a measured four-second timer. | Current NVDA setting and actual elapsed time; same Linux caret, readable semantic line and physical cursor after timeout. |
| Pan during message; appropriate timer and unchanged semantic window | **Automated PASS only.** M `test_message_panning_resets_timer_without_moving_linux_window`, `test_intact_linux_region_and_pan_window_are_preserved`. Earlier ordinary Linux left-pan PASS on .2 did not pan a temporary message. | One physical pan while visible, timer behavior and same semantic panning window/focus after dismissal. |
| Routing dismisses without caret/action/activation | **Confirmed failure, historical .4; latest physical retest not accepted.** P85 records caret **6→9** with user's explicit statement that the message was visible and no other caret moves occurred. M `test_routing_dismisses_message_without_remote_caret_or_action` and guarded-routing tests now pass. Later mixed traces do not invalidate that original report. | Separate one-route visible-message trial, zero dropped diagnostics, unchanged Linux caret and no semantic action/caret request; actual b.note restoration. Exact live cause remains unknown. |
| No stale queued route affects underlying text or a newer Linux/Windows message | **Automated PASS only.** P85/M timeout-before-execution, two presses, later Linux/Windows message, weak-reference replacement and control/session lifetime tests. This is an independently reproduced/fixed queue defect, not attribution of the historical 6→9 movement. | Controlled current-build physical/session checks after basic dismissal is established; no newer message dismissed or remote route sent by the older press. |
| Linux messages never take over local Windows braille | **Automated PASS only for supported built-in Remote path.** S `test_builtin_temporary_message_and_local_control`, `test_builtin_message_is_dropped_if_control_changes_before_delivery`, parsed/queued handoff tests; M local-control/generation/Windows-message ownership tests. Legacy callback-only clients without a control-state API cannot establish the same suppression guarantee; this limitation remains documented. | Local Windows control, Linux message production and physical confirmation of no takeover, without exposing private local text. |
| Disconnect/reconnect: no stale replay | **Automated PASS only.** S queued fallback/reconnect and same-transport reconnect tests; W `test_message_before_negotiation_is_dropped_and_never_replayed`, `test_reconnect_withdraws_message_support_until_the_new_peer_opts_in`; M lifecycle expiry. | Separately approved real disconnect/reconnect, new negotiation, fresh message and physical absence of stale replay. |
| Older add-on fallback | **Automated PASS only; intentionally unavailable transient feature for non-negotiating peers.** W no-peer-support, unsupported-version and semantic-fallback tests. Messages require `message_version=1`; raw cells do not substitute for transient semantic messages, and there is no replay. O preserves status v1 and trace v2; outcomes v3 are optional. | Approved older-peer compatibility session or explicitly accepted supported-version limitation; no downgrade is performed by this audit. |
| NVDA Show messages disabled | **Automated PASS only.** M `test_disabled_messages_do_not_replace_windows_focus`, speech-only and disabled-message ownership tests use actual native message methods with fake configuration/timers. | User changes the setting in a separate approved step, triggers one message, confirms none appears, then restores setting. |
| Actual Eurobraille b.note text/cursor accuracy | **Not tested for complete/latest acceptance.** Historical limited input-help timeout PASS and separate ordinary pan PASS exist; routing remains disputed/unisolated. P86 outcomes are logical stages, not device output. | Driver/firmware/cell count/table/runtime settings recorded, public expected text and physical cursor confirmed per interaction. No complete checklist PASS. |

P84 fixes final semantic restoration, not a measured absence of any intermediate
Windows display frame: NVDA's post-dismiss callback follows its initial update.
Without native lifecycle hooks only pre-message repair is available; custom
non-weak-referenceable message regions retain native routing. Native timer/pan
behavior and Show messages policy remain NVDA-owned. These limitations must not
be hidden by the main-buffer restoration tests.

P86 adds observations, **not a routing/activation/Say All behavior fix**.
`caret_send_returned` proves only that a send call returned. Linux
`setter_returned` still requires an event/readback for caret application.
`message_dismissed` is not a physical-frame observation. Unknown outcomes, null
key associations and either ledger's dropped count prevent negative inference.
Mousepad can use an application-direct AT-SPI channel; an empty accessibility-bus
writer trace cannot exclude an Orca caret write. The historical 6→9 and .5
20→7 reports remain unisolated; input-help/native Say All cancellation is a
source-backed alternative mechanism, not a live diagnosis.

## Read-only environment check

| Component | Observed on this audit | Limit |
| --- | --- | --- |
| Windows | Installed NVDA executable product version **2026.2**, file version **2026.2.0.57664**; an NVDA process exists. Companion manifest **20261014.0.1** and all **15 installed Python files** equal the reviewed package. | No loaded-module attestation, authenticated live status or input was obtained in this audit. A running process and disk equality do not prove its loaded build. |
| Saved NVDA defaults | Main `nvda.ini`: desktop layout, braille display `auto`, Show messages `1`, timeout `4`; modifier-key choices not explicitly saved in that file. | Active profile/runtime settings and selected auto-detected physical driver are unverified. No settings were changed. |
| Linux SSH | `cyber` / `miriam@cyber.local` reachable read-only; Mint **21.3**, Orca **42.0-1ubuntu2**, pyatspi **2.38.2-1**, libatspi **2.44.0-3**; an Orca process exists. | Process presence does not attest loaded bridge or remote-control state. |
| Linux installed source | Controller marker **v120**, not v121. Standalone `linux_rdaccess_caret_diagnostics.py` absent. Keyboard methods above match current main; semantic-caret and main-thread scheduler differ consistently with the diagnostic update. | Updated Linux reason diagnostics are not deployed. Whole-file adapter/current-runtime equivalence is not claimed. |
| Native Orca source | Mint `script.py`, `scripts/web/script.py` and `input_event.py` SHA-256 values equal the WSL installed Orca files used by source-backed tests; both package versions are 42.0-1ubuntu2. | Tests compile selected native methods with fake surrounding runtime, not the live Orca process. |
| Message/display settings | b.note model is user-reported from previous tests. No literal saved Orca flash setting was found by the fixed-name customization AST inventory. | Orca runtime enableFlashMessages/brailleFlashTime, Remote/add-on active versions, driver/firmware/cells/contraction and active NVDA profile remain to record. Defaults are not inferred. |
| Desktop Commander | Requested availability-only account inventory: Windows and Cyber devices both report **offline**. | No device filesystem, process, input or desktop operation used it. Investigation/tests used terminal, SSH and private WSL instead. |

No installation, deployment, NVDA/Orca restart, remote connection change, active
application action or agent desktop input occurred. The consent endpoint was
not probed without a fresh test-session grant. No credentials, private document
text, general speech log or customization-file contents were published.

## Fresh automated results and exact commands

All results below were executed against the audited f247d77 tree. Counts are
test executions; inherited/source-reference cases overlap and are not a count
of unique acceptance criteria. Every run had **0 failures, 0 errors, 0 skips**.

| Run | Platform/reference | Tests | What is real / substituted |
| --- | --- | ---: | --- |
| Full Windows companion | Windows, CPython 3.13, configobj 5.0.9; NVDA source `1406f9f8a04eb50f7317af87aba3a9d439c2a772` | 334 | Production companion, actual selected NVDA methods and real isolated Windows IPC/DPAPI/ACL; NVDA process, wx timers, speech/display and remote providers substituted. |
| Outcome-specific release check | Same Windows interpreter; NVDA 2026.2 release source `f62c980589d1ac30babf68ad48177e9ad29a2e84` | 15 | Explicit new outcome methods; native routing/conversion/activation excerpts with fake surrounding state. This is not the whole companion suite on release source. |
| Linux acceptance selection | Local WSL Ubuntu **22.04.5**, CPython **3.10.12**, Orca **42.0-1ubuntu2**, native AT-SPI preloaded | 565 | Production generated controller/adapter, source-backed native Orca methods, isolated wire/serialization and filesystem; most scripts, queues and application providers fake. |
| Shared controller/lifecycle | Same WSL | 305 | Generated production patch and upgrade fixtures; runtime/injection/scheduling mocked. |
| Private native integration | Same WSL; Xvfb **21.1.4**, GTK **3.24.33**, libatspi **2.44.0-3**, new private X server and D-Bus | 25 | Actual XTest/XKB delivery/state/release; actual owned GTK provider setter/readback/caret event. Orca presentations mocked. No live NVDA, Firefox, Mousepad, b.note or user desktop. |

Working directory is the repository root except the two Windows commands,
which use `nvda-addon`. `rtk` prefixes the Windows shell commands as required.
The local helpers and source worktrees live under ignored
`tmp/braille-routing-outcomes/`; their exact selection/behavior is recorded
below rather than introducing a production test-runner change.

```powershell
rtk proxy uv run --no-project --python 3.13 --with configobj==5.0.9 --env-file ../tmp/braille-routing-outcomes/ci.env python -m unittest discover -s tests -t . -q
rtk proxy uv run --no-project --python 3.13 --with configobj==5.0.9 --env-file ../tmp/braille-routing-outcomes/test.env python ../tmp/braille-routing-outcomes/run_new_outcomes.py
```

The two environment files set `NVDA_SOURCE_DIR` respectively to the pinned CI
and release-source checkout's `source` directory. `run_new_outcomes.py` selects
only the 15 test methods defined directly by the new outcome test class, rather
than rerunning inherited message tests against a different source contract.

```powershell
rtk proxy wsl -d Ubuntu --cd /mnt/c/Users/Miriam/Personal_Coding/rdp/linux-rdaccess --exec python3 -B tmp/braille-routing-outcomes/run_acceptance_linux.py
rtk proxy wsl -d Ubuntu --cd /mnt/c/Users/Miriam/Personal_Coding/rdp/linux-rdaccess --exec python3 -B -m unittest -q tests.shared.test_remote_access tests.shared.test_compat_lifecycle
rtk proxy wsl -d Ubuntu --cd /mnt/c/Users/Miriam/Personal_Coding/rdp/linux-rdaccess --exec python3 -B tmp/braille-routing-outcomes/run_acceptance_private.py
```

The 565-test helper prepends the repo root to `sys.path`, imports native
`gi.repository.Atspi` after `gi.require_version('Atspi', '2.0')` **before mocks**,
then uses `unittest.TestLoader().loadTestsFromNames` and
`TextTestRunner(verbosity=1)`. Its explicit module list is:

```text
tests.unit.accessibility.test_browser_command_context
tests.unit.accessibility.test_elements_focus
tests.unit.accessibility.test_native_list_lifetime
tests.unit.accessibility.test_caret_diagnostics
tests.unit.accessibility.test_customization_say_all_callbacks
tests.unit.accessibility.test_say_all_presentation_lifetime
tests.unit.braille.test_temporary_braille_messages
tests.unit.braille.test_braille_display_lifecycle
tests.unit.braille.test_braille_cell_alignment
tests.unit.braille.test_braille_routing_speech
tests.unit.braille.test_nvda_native_braille
tests.unit.braille.test_braille_input_help
tests.unit.braille.test_braille_protocol
tests.unit.transport.test_logging_privacy
tests.unit.transport.test_connection_session
tests.unit.transport.test_customization_reconnect
tests.unit.transport.test_installed_layout
tests.unit.transport.test_configuration_updates
tests.unit.test_windows_test_session
tests.integration.test_nvda_remote_loopback
tests.unit.input.test_controller_v89_upgrade
tests.unit.input.test_customization_event_api
tests.unit.input.test_genuine_upgrades
tests.unit.input.test_input_trace
tests.unit.input.test_insert_modifier_deferral
tests.unit.input.test_layout_keypad_gestures
tests.unit.input.test_mouse_command_collisions
tests.unit.input.test_nvda_direct_commands
tests.unit.input.test_pass_next
tests.unit.input.test_patch_hardening
tests.unit.input.test_remote_key_validation
tests.unit.input.test_review_say_all_collision
tests.unit.input.test_structural_list_ownership
```

The private helper uses `TemporaryDirectory`,
`tools.diagnostics.real_gui_atspi_smoke.isolated_environment(Path(private))`,
and a 60-second subprocess timeout. It invokes exactly:

```text
xvfb-run -a -s "-screen 0 1280x900x24" dbus-run-session -- python3 -B -m unittest -v tests.integration.x11.test_xtest_injection tests.integration.x11.test_xkb_lock_state tests.integration.x11.test_lock_toggle_integration tests.integration.x11.test_caret_diagnostics
```

Limitations: WSL lacks Mousepad, so no new native Mousepad observer/application
test is claimed. Full real Firefox/VS Code GUI runs and physical braille were
not rerun locally. The [P86 audit](compatibility-audit-2026-10-14-routing-outcomes.md)
records an existing release-source empty-cell fixture mismatch and Windows
POSIX/default-encoding assertion failures; the passing pinned-reference/native
Linux runs here do not retroactively erase those findings. Expected rejection
test stderr and GI deprecation warnings occurred without unittest failures.

## Completed CI evidence

One read of `gh pr checks 86 --repo mtigzoe/linux-rdaccess --json name,state,bucket,link`
found **13 SUCCESS checks across seven workflows**. This independently confirms
the user's reported PR result, not physical acceptance:

- [Unit tests, Python 3.10/3.12](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068082)
- [Linux diagnostic scripts](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068193)
- [Remote loopback, Python 3.10/3.12](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068228)
- [Four compatibility-contract areas](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068175)
- [Real private GUI / AT-SPI](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068090)
- [Windows companion](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068181)
- [uv Linux/Windows suites](https://github.com/mtigzoe/linux-rdaccess/actions/runs/38602068055)

This is a completed-run snapshot, not CI monitoring. Any audit PR's CI is a
separate run; no wait, repeated polling or merge is authorized by this audit.

## Isolated next human actions

These are a plan, **not actions already requested as test gestures or performed**.
Each numbered test must receive its own short prompt only after both observers
are ready. Do not hand the whole sequence to the user as one mixed recording.

Preparation is separate from measurement. Finish public-fixture navigation and
panning first; note original caret and semantic window. Confirm loaded NVDA,
Remote/companion versions, active profile/layout/modifiers, b.note driver,
firmware/cells/table, message settings, and current control/negotiation. A fresh
explicit five-minute grant permits only the documented status/trace/outcome
operations, not arbitrary execution or desktop control. Opt-in diagnostics
remain unchecked by default, bounded and consent-scoped; do not auto-renew.

For complete Linux reason evidence, install merged **f247d77**'s v121 controller,
updated adapter/model and standalone diagnostics helper using the supported
backup-preserving installer, then restart Orca once. This briefly interrupts
Linux accessibility/Remote access and needs explicit approval before execution.
Windows .1 files already match; do not reinstall or restart NVDA merely to
obtain a disk match. If loaded .1 cannot be established through supported
evidence/user confirmation, a separate authorized NVDA reload is required.

Use the existing [read-only Linux observer](routing-tests-without-desktop-commander.md)
before a physical gesture and authenticated Windows `nvda-status`,
`nvda-braille-trace` and `nvda-braille-outcomes` reads within consent. Record
clock alignment uncertainty, initial/final caret, same-focus state, ledger
drop counts, and the human physical observation. Publish only numeric metadata
and the consented public fixture, never unrelated text. The current ledgers
do not attest every native message timer/physical frame; obtain the user's
message-visible/returned-line confirmation rather than inventing those events.
If setup fills a ledger, end that attempt and use newly granted consent later;
never clear or renew it through undocumented operations.

1. **First #72 check — appearance/timeout only:** Mousepad public
   `Alpha Barlio Charlie`, stable caret; observer ready and Linux control
   confirmed. Prompt only: “Press NVDA+1 once, then wait without touching Linux
   keys. Tell me whether input help was on/off, a message appeared, and the
   Linux line/cursor returned.” Measure timeout separately from caret readback.
   Stop recording; an undo toggle, if needed, is another prompted action.
2. **Separate #72 check — one physical routing dismissal:** a four-second
   message can expire during a chat reply. To keep each action separately
   prompted, first request specific permission for the user to select NVDA's
   **Show messages indefinitely** for this trial and restore the saved setting
   afterward. Do not change it automatically. Then prompt NVDA+1 once; after
   physical visibility is confirmed, prepare the routing recording and prompt
   **one** routing key under the first letter. No arrows, panning or extra
   routes. If visibility was lost, label inconclusive and stop. Require unchanged
   Linux caret, no caret/action send and actual line/cursor restoration. This
   tests dismissal, not the timeout policy tested separately above. Do not
   claim causality from a send return or missing bus call.
3. **First remaining #57 command:** known public Mousepad window, input help
   off, observers prepared. Prompt **NVDA+T once** and obtain the actual title
   announcement/no inserted letter. Caps-modifier, pass-next, locks, laptop,
   capture and held-key tests each receive later individual prompts. Return to
   local control and NVDA menu testing are two separately observed actions.
4. **Firefox and transitions:** after separately approved setup, test one
   NVDA+F7 invocation/category, one Tab then a later Shift+Tab, one edit-mode
   character and separate browse-mode navigation. Panning-on-message,
   Show-messages-disabled, local-control suppression, reconnect and older-peer
   fallback each require independent preparation/consent; none is implied by
   the first message or routing check.

No new behavior fix is proposed because this audit found no new reproducible
production defect. P82–P85's confirmed automated defects are fixed in source;
historical physical caret-preservation failure and all incomplete matrix cells
remain acceptance work. Both issues are **NOT READY**, rather than universally
BLOCKED: independent automation and source investigation were possible, while
current physical completion awaits consent, deployed diagnostics where needed,
and the user's short hardware-operated checks.
