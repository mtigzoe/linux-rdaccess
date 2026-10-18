# Issue #123: Isolated relay transport fault-injection testing

These are **developer/integration tests**, not normal installation steps for linux-rdaccess. They use the actual pinned Orca Remote transport and genuine pinned NVDA Remote relay implementation, entirely on localhost. They do not launch Orca, access a live relay, or exercise physical NVDA/braille.

## Recommended: GitHub Actions

The [Issue 123 relay fault-injection stress workflow](../../.github/workflows/issue-123-relay-fault-stress.yml) checks out this repository and downloads the two pinned upstream repositories into temporary directories automatically. **You do not have to clone either upstream repository locally to use GitHub Actions.**

The workflow currently has two triggers:

- A pull request changing the stress test, its workflow, or `linux_rdaccess_core/connection/remote_access.py`.
- Manual **Actions → Issue 123 relay fault-injection stress → Run workflow** (`workflow_dispatch`).

**A direct push to `main` does not trigger this workflow.** Run it manually for changes already committed directly to main. The patched jobs gate success; the unpatched control is informational and currently permits failures.

## Optional local Linux setup

Use an **isolated Linux development machine**, not the active accessibility desktop, and avoid running this memory-/connection-intensive suite alongside an Electron/Chromium build. Requirements: Git, Python 3, `openssl` on PATH, and access to GitHub. Do not use a production relay address or credentials.

From the root of your linux-rdaccess checkout:

```bash
git clone https://github.com/serrebidev/orca-remote.git /tmp/orca-remote-upstream
git -C /tmp/orca-remote-upstream checkout d273e82fbc93bf6a6eb473a00e38291d84f1dccb

git clone https://github.com/a2hsh/nvda-remote.git /tmp/lrd-nvda-relay
git -C /tmp/lrd-nvda-relay checkout 78de6ac0cf7fde4081b6dc176a2e0dbb87450e17

export LRD_PINNED_ORCA_REMOTE=/tmp/orca-remote-upstream
export LRD_PINNED_RELAY_FILE=/tmp/lrd-nvda-relay/server.py
export PYTHONPATH=.
```

Verify the exact pinned commits before testing:

```bash
git -C "$LRD_PINNED_ORCA_REMOTE" rev-parse HEAD
git -C /tmp/lrd-nvda-relay rev-parse HEAD
```

The results must match the commit IDs in the checkout commands. These temporary directory names are examples; change the environment variables if you use different locations. This test is Linux-specific (it uses `/proc` and Linux socket/process behavior) and is not intended for native Windows PowerShell.

## Run individual scenarios

```bash
python3 -X faulthandler tests/integration/relay_transport_stress.py sessions --cycles 80
python3 -X faulthandler tests/integration/relay_transport_stress.py teardown --cycles 40
python3 -X faulthandler tests/integration/relay_transport_stress.py halfopen
python3 -X faulthandler tests/integration/relay_transport_stress.py partial --cycles 40
python3 -X faulthandler tests/integration/relay_transport_stress.py prejoin --cycles 40
```

Scenarios check repeated join/reconnect and frame order (`sessions`), termination under bidirectional traffic (`teardown`), a non-reading peer (`halfopen`), partial frame cutoff (`partial`), and application traffic before joining (`prejoin`). Check the `RESULT` output and process exit status. Test failures should be investigated, not hidden by retries or increasing timeouts.

For **informational historical comparison only**, set `LRD_UNPATCHED=1` before running an individual scenario against the unpatched pinned transport. Failures or crashes in that control are not evidence of a defect in the patched production path; do not run the intentionally unsafe control on an active desktop.

## Harness shutdown accounting (issues #137 and #138)

The stress harness owns its asyncio loop thread. `Env.close()` shuts it down like `asyncio.run()`: it stops accepting, closes every proxied and peer transport, lets tasks finish, cancels and **awaits** any survivors, retrieves their exceptions, closes the servers, loop and thread, and returns a report. Every scenario prints that report as `shutdown` in its `RESULT` line and fails if it lists any `problems`, pending tasks, an unclosed loop or a thread that did not end.

Errors on the harness's own asyncio side are classified rather than swallowed:

- **Expected**: `ConnectionError` subclasses (`ConnectionResetError`, `BrokenPipeError`, `ConnectionAbortedError`) are what the injected cut/RST/stall faults cause. They are counted in `shutdown.expected_fault_errors`.
- **Unexpected**: anything else is listed in `shutdown.problems` and fails the scenario.

The genuine relay and the production transport still log their own fault-injection output (for example `Error client N` with `BrokenPipeError`, `socket.send() raised exception`, `dropped malformed line`). That output is expected and is not shutdown noise.

Regression tests (they need the same pinned checkouts and environment variables; CI sets `LRD_REQUIRE_PINNED=1` so a missing checkout fails instead of skipping):

```bash
python3 -m unittest -v tests.integration.test_relay_stress_shutdown
```

The CI scenario steps run through `tests/integration/run_stress_gated.sh`, which also fails when the output contains `Task was destroyed but it is pending`, `exception was never retrieved` or `CancelledError`.

## Acceptance scope

Passing these simulated/isolated relay scenarios supports issue [#123](https://github.com/mtigzoe/linux-rdaccess/issues/123), but **does not establish live NVDA-origin input, Orca speech, or physical braille acceptance**. Those user-authorized tests remain tracked in [#61](https://github.com/mtigzoe/linux-rdaccess/issues/61). Preserve CI logs and exact interpreter/OpenSSL versions when reporting any failures.
