# Live-test input trace

Purpose: prove a live Windows NVDA -> NVDA Remote -> linux-rdaccess -> Orca 42
failure from metadata, without recording anything a user typed, heard or read.

Enable by exporting `LINUX_RDACCESS_TRACE=1` in the environment Orca starts with,
then run `linux-rdaccess connect` and restart Orca (controller v80 or later).
Unset it and restart Orca to stop. The file is
`~/.local/share/orca/orca-remote-input-trace.log`; one JSON object per line, mode
0600, rotated to `.1` above 256 KiB. Read it with:

```sh
python3 tools/summarize_input_trace.py            # counts and findings
python3 tools/summarize_input_trace.py --timeline # plus a compact timeline
```

The summarizer exits 1 when it finds something worth examining (a release that
failed during reset, a rejected or raised injection, a skipped stale callback, a
lock press that did not change the XKB state, a refused browse command, a
delayed consumer that found stale objects, or both NVDA modifiers held).

## What is never recorded

Typed text, passwords, clipboard contents, speech, braille keyboard input
(dots/space), braille driver or gesture identifiers, routing positions, Remote
Access keys, key names, and arbitrary payloads. Enforced in two places: a
character key is written as `"id": "char"` with no VK, scan code or extended bit,
and the writer reduces every value to an integer, a boolean, or a token of at
most 40 characters from `[A-Za-z0-9_./:+<>=-]`; anything else becomes `"?"`.
A key's VK/scan code is recorded only when it is in a fixed non-character
vocabulary (modifiers, locks, navigation cluster, function keys, Escape, Tab,
Enter, Backspace, Apps) or while an NVDA modifier is held (a command). A refused
single-letter navigation records the context but not the letter.

## Records

Every record has `seq`, `t` (epoch seconds) and `kind`. Controller records also
carry `gen`, the input generation: it increases whenever control, the transport or
a client hand-off clears held-key state, so records with different generations
belong to different sessions.

| kind | fields |
| --- | --- |
| `key` | `press` (down/up/repeat), `disp`, `why`, `id`, `vk`/`ext`/`scan` (see above), `own`, `claim`, `claim_cmd` |
| `forward` | `id`, `down`, `result` (ok/rejected/raised), `owned` |
| `lock` | `id` (CapsLock/NumLock), `down`, `before`, `after`, `changed` from the actual XKB indicator |
| `reset` | `reason`, `held`, `failed` (keys whose release could not be injected and stay owned) |
| `session` | `controlling`, `connected`, `role` |
| `speech` | `what`: local_stop_requested/coalesced/ran/unscheduled, nvda_cancel_sent/not_applicable/failed, cancel_throttled |
| `main` | `ticket`, `state` (scheduled/ran/stale_skipped), `sched_gen` |
| `script` | `method`: the Orca operation that actually executed |
| `braille` | `cls` (pan_back, pan_forward, route, to_focus, key, keyboard, unclassified), `record`, `emulated` (canonical key and modifier names only) |
| `hook` | `hook`, `decision`, `cmd`, `ctx`, `editable`, `web_app`, `stale`, plus `level`/`reverse` for heading levels |

`disp` is one of `forwarded` (sent on to Orca/X unchanged), `translated` (an NVDA
command run through a native Orca API), `suppressed` (consumed, with a `why` of
`unsupported_nvda_command`, `unsupported_object_review`, `nvda_orca_collision`,
`unsupported_exit_embedded` or `lock_repeat`), `caps_deferred`, `owned_press`,
`owned_release`, `pass_next`, or `raised`.

`own` is the state when the decision was made, before this event's own
injection: `down` (received from Windows), `fwd` (injected into X), `nvda` (the key
chosen as NVDA modifier; Insert wins over Caps Lock), `caps_pending`, and counts
of other keys. Navigation-cluster identities carry `/ext` or `/nonext` and are
never interpreted as the keypad.

`ctx` is `document_browse`, `document_focus`, `chrome_or_non_document` (browser
chrome, address bar and any other non-document content: Orca does not tell them
apart), `not_web`, `document` (mode unavailable) or `unknown`. Table decisions are
`translated_arrow`, `translated_edge`, `refused_not_browse`, `refused_no_cell`,
`refused_no_cell_handler` and `consumer_stale`. NVDA+Ctrl+Alt+Arrow read-row and
read-column are `suppressed`/`unsupported_nvda_command` and never reach Orca.

## Not covered

Orca's own consumption of ordinary forwarded keys is not recorded (the event
carries no remote provenance, and recording it would identify typed keys); only
gestures this patch translated report `orca_native`. Audible output, braille
cells and what NVDA actually spoke or displayed are not visible from Linux.

## Manual checklist for a live run

Set one input source per trial, trace on, note the NVDA layout and modifier.
After each step run the summarizer with `--since` set to the last seen `seq`.

1. Ctrl+L, NVDA+Space: `hook` shows `chrome_or_non_document`, nothing translated.
2. Click into the page; Down/Up and NVDA+Space: `document_browse` <-> `document_focus`.
3. In the input, textarea and rich editor, type F, D, H, 7: `refused_not_browse`
   with `document_focus` or `editable=true`, no `cmd`; the text appears.
4. Browse mode: H, D, F, Shift+F, 7/8/9 and reverse: `native` with `cmd`/`level`.
5. NVDA+V, NVDA+Ctrl+F, NVDA+F3/Shift+F3: `nvda_browse` `native`; NVDA+Shift+F10:
   `consumed_unsupported`; same keys in the address bar: `consumed_outside_document`.
6. Ctrl+Alt+Arrows and Ctrl+Alt+PageUp/PageDown/Home/End in the table:
   `translated_arrow` / `translated_edge`; at the table edge and outside a table,
   a `refused_*` decision; NVDA+Ctrl+Alt+Arrow: `suppressed`.
7. Caps Lock and Num Lock, each alone: one `lock` pair with `changed` true then
   false semantics matching the Linux indicator; as NVDA modifier: no `lock`.
8. Ctrl during speech: `speech` `nvda_cancel_sent` once, no repeat; hold an arrow:
   `cancel_throttled`; Say All then Ctrl: no later `script` records.
9. Hold a modifier and an arrow, disconnect, release, reconnect: a `reset` with
   `failed: []`, a new `gen`, and no stale `main` execution.
10. Braille pan, route, to-focus, an emulated key: one `braille` record each with
    the expected `cls`, followed by a `script` record.
