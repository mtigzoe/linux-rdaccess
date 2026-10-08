# Root Python cleanup validation: 2026-10-08

## Scope

Seven remaining implementations moved into `linux_rdaccess_core`: the Linux CLI,
Windows controller, Remote Access configuration/Orca patcher, Orca adapter,
AT-SPI model, and the speech and braille bridges. All twelve historical root
Python paths remain as small compatibility files. Existing Linux/Windows
commands, public imports and private patching helpers are preserved.

The installer validates the complete runtime before copying, ships the package
and compatibility files, locates its source bundle after installation, and
quotes literal shell paths. Orca receives standalone implementation copies under
its existing adapter/model filenames. The optional braille launcher uses the
package without changing its working directory. Tools and CI use the new paths.

## Automated results

| Check | Environment | Result |
| --- | --- | --- |
| Current `main` baseline | Cyber, Mint 21.3, Python 3.10.12, temporary public clone | 1,141 tests; pass; 18 skipped without a display |
| Published cleanup suite without a display | Cyber temporary clone, Mint 21.3, Python 3.10.12 | 1,148 tests; pass; 18 display tests skipped |
| Published cleanup suite under private Xvfb | Cyber temporary clone, Mint 21.3, Python 3.10.12 | 1,148 tests; pass; no skips |
| Installed runtime, standalone Orca layout and package imports | Published cleanup code on Cyber; private configurations | 13 tests; pass |
| Full updated suite without a display | Local Ubuntu WSL, Python 3.10.12 | 1,148 tests; pass; 18 display tests skipped |
| Full updated suite under private Xvfb | Local Ubuntu WSL, Python 3.10.12, system accessibility libraries | 1,148 tests; pass; no skips |
| Windows controller, settings, public imports, standalone Orca layout | Native Windows, Python 3.14 | 23 tests; pass |
| Real GTK/AT-SPI controls and keyboard/caret/dialog smoke | Updated code, local WSL, private Xvfb/session bus/settings directories | 33 checks; pass; 44 events recorded |
| Real GTK/AT-SPI smoke on published cleanup | Cyber temporary public clone, private Xvfb | 33 checks; pass; 44 events recorded |
| Semantic fixture contract against local sibling `rdAccess` checkout | Windows; six newly generated JSON fixtures | 7 tests; pass |
| Package/tools/diagnostics/tests compilation | Local WSL, Python 3.10.12 | Pass |
| Linux/Windows/configuration root entry-point compilation | Local WSL | Pass |
| All Linux shell scripts, including root wrappers | Local WSL | Pass |
| Package and legacy speech/braille bridge `--help` | Local WSL, real AT-SPI/liblouis | Pass; no listeners started |
| Workflow YAML parse and executable-step validation | Local WSL | Pass |

The acceptance tests invoke `python3 linux_rdaccess.py install` with a temporary
home, then reinstall through the installed `linux-rdaccess` command outside the
source checkout. They exercise `status`, `doctor`, `compatibility`,
`connect --no-restart`, `disconnect --no-restart`, and forwarded `configure`
options with synthetic configurations. Missing files produce understandable
errors. Saved configuration, customization and backup files remain mode 0600;
keys are absent from captured output and saved settings survive disconnection.
No acceptance test contacts a relay or restarts Orca.

The standalone Orca fixture imports only `linux_rdaccess_orca_adapter.py` and
`linux_rdaccess_a11y_model.py` from a temporary scripts directory and verifies
semantic focus. Package imports are also tested without any root compatibility
files. Every missing manifest member is tested before an existing installation
can be overwritten.

## Defects and safeguards

- Windows CRLF checkouts broke Linux shell launchers with `set: pipefail` errors.
  `.gitattributes` now enforces LF for shell scripts.
- During migration, cached package attributes could revive a removed stub bridge
  and replace real liblouis conversion. Root forwarding uses `importlib` and the
  stub loader isolates the canonical module as well as the historical name.
  The full suite passes with the actual contracted braille tests enabled.
- The installer previously checked only one package module, allowing an
  incomplete package to overwrite an installation. It now validates all runtime
  dependencies first, with regressions for each missing module.
- Double-quoted launcher paths allowed shell expansion of literal dollar signs.
  Shell quoting is now explicit, with a real installed-path regression containing
  both quotes and a dollar sign.
- XTest injection tests previously accepted any available desktop display. They
  now require an identifiable private Xvfb process before opening X11, with
  regressions that reject normal and unverifiable desktop displays.

No newly reproduced end-to-end NVDA keyboard, speech or physical braille defect
was established in this session. The changes above are installation, import,
launcher and test-isolation fixes.

## Cyber and live testing status

SSH to `cyber.local` succeeded. Cyber runs Mint 21.3, Python 3.10.12, Orca 42 and
an XFCE session. Read-only checks of its existing installation found saved
configuration ready, autostart enabled, required applications available and its
existing patch checks current. The migrated installation was validated
separately using synthetic settings and a private temporary home.
Neither its existing source checkout nor its installed runtime was replaced.

Initial checks found both Desktop Commander devices offline and no running
NVDA process on the available Windows machine. In the follow-up session, the
user confirmed that Desktop Commander was open and NVDA was running, supplied
`ssh miriam@cyber.local`, and identified Insert+Alt+Tab as the remote-control
switch. Read-only checks then confirmed:

- Windows Desktop Commander was online and responded to a ping; its Cyber
  device still reported offline, while direct SSH worked.
- NVDA was running and had one established TCP connection on the relay port.
- The existing Orca process also had one established TCP connection on the
  relay port. These socket checks do not establish that both clients joined
  the same channel or that input, speech or braille reached the other endpoint.
- Mint's live accessibility bus exposed 24 applications. A redacted focus
  query found an active, focused menu. A 45-second focus/window event listener
  registered successfully but received no events during its observation.

This chat exposes terminal and file tools, but no Windows keyboard-control
tool or the `node_repl` runtime required by the Computer Use skill. No
Insert+Alt+Tab or application keystrokes were sent. The user was asked to press
Insert+Alt+Tab followed by NVDA+Tab and report the announcement; the result is
pending. No Orca restart, Remote Access disconnection or desktop changes were
performed, and no relay keys, focus labels or window titles were recorded.

Automatic approval review rejected both a broad source upload and a narrower
transfer of modified Python source/tests to Cyber, citing possible disclosure
of unpublished code. The requested commit and push subsequently published
implementation revision `5dcb9c9` in the verified public repository. Downloading
that public revision into Cyber's temporary clone was then approved. Both full
suites, isolated installation acceptance and actual GTK/AT-SPI smoke checks
passed on Mint. No unpublished local files were uploaded.

| Application | Availability on Cyber | Keyboard and focus | NVDA speech | Physical braille | Live defects |
| --- | --- | --- | --- | --- | --- |
| XFCE Settings Manager | Installed | Pending | Pending | Pending | Not assessed |
| Clock and Calendar | XFCE panel installed; calendar role passes isolated GTK smoke | Pending | Pending | Pending | Not assessed |
| Thunar File Manager | Installed | Pending | Pending | Pending | Not assessed |
| XFCE Terminal | Installed | Pending | Pending | Pending | Not assessed |
| Mousepad | Installed | Pending | Pending | Pending | Not assessed |
| Firefox | Installed | Pending | Pending | Pending | Not assessed |
| Visual Studio Code | Installed | Pending | Pending | Pending | Not assessed |

Live verification still needs local/remote control switching, NVDA+Tab/title,
Firefox elements list and browse/focus commands, Ctrl speech interruption,
Caps Lock/Num Lock, Tab/Shift+Tab and both NVDA keyboard layouts. It also needs
correct speech roles without duplicated Orca output, reliable focus delivery,
accurate braille labels/roles/states, panning in both directions and routing to
focus/caret. Record NVDA-native semantic braille separately from forwarded Orca
cells: the two presentation paths are not interchangeable. Preserve the current
connection and establish recovery before any live restart or disconnection.

## CI coverage

Workflows now trigger on package changes and the cleanup branch. CI runs
headless/Xvfb suites, real GTK/AT-SPI checks with system Orca/liblouis,
installed-runtime acceptance, legacy/package bridge entry points, Windows
controller/import checks and the Linux-to-rdAccess semantic protocol contract.
CI and isolated GTK tests cannot establish live NVDA speech or physical braille
compatibility. Live verification remains required before claiming that coverage.

The implementation revision's pull-request runs passed:
[full uv/Windows suite](https://github.com/mtigzoe/linux-rdaccess/actions/runs/37810983170),
[Linux accessibility diagnostics](https://github.com/mtigzoe/linux-rdaccess/actions/runs/37810983001),
and [remote semantic contracts on Python 3.10/3.12](https://github.com/mtigzoe/linux-rdaccess/actions/runs/37810983124).
