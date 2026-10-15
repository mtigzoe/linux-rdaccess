#!/usr/bin/env python3
"""Disposable private Code keyboard-selection matrix; CDP only observes DOM.

Diagnostic completion records failures without classifying Unicode acceptance.
Requires --binary to resolve below /tmp, and starts its own Xvfb and D-Bus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inner", action="store_true")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Linux private Xvfb/D-Bus fixture required")
    args.output = args.output.resolve()
    if not args.output.is_relative_to(Path("/tmp")):
        raise ValueError("Only a disposable output below /tmp is permitted")
    sys.path.insert(0, str(args.repo.resolve()))
    from tools.diagnostics import real_gui_atspi_smoke as smoke
    from tools.diagnostics import vscode_unicode_selection_probe as probe

    binary = args.binary.resolve()
    if not binary.is_relative_to(Path("/tmp")):
        raise ValueError("Only a disposable Code binary below /tmp is permitted")
    bundle_rel = Path("resources/app/out/vs/workbench/workbench.desktop.main.js")
    installed_bundle = Path("/usr/share/code") / bundle_rel
    if (binary.parent / bundle_rel).resolve() == installed_bundle.resolve():
        raise ValueError("Private Code bundle resolves to installed Code")

    if not args.inner:
        args.output.mkdir(mode=0o700)
        installed_before = digest(installed_bundle)
        # Keep Code's IPC path below Unix socket limits independently of the
        # evidence-directory length. This is also the retained session root.
        fixture = Path(tempfile.mkdtemp(prefix="lrd-nmatrix-", dir="/tmp"))
        env = smoke.isolated_environment(fixture)
        env.pop("LRD_EXPECT_VSCODE_79", None)
        command = [
            "xvfb-run",
            "-a",
            "-s",
            "-screen 0 1280x900x24",
            "dbus-run-session",
            "--",
            sys.executable,
            "-B",
            __file__,
            "--repo",
            str(args.repo),
            "--binary",
            str(binary),
            "--output",
            str(args.output),
            "--inner",
        ]
        with (args.output / "probe.log").open("w") as stream:
            process = subprocess.Popen(
                command,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                code = 2
        for name in ("vscode.log", "wm.log", "atspi.log"):
            if (fixture / name).is_file():
                shutil.copyfile(fixture / name, args.output / name)
        path = args.output / "matrix.json"
        report = (
            json.loads(path.read_text()) if path.exists() else {"status": "unavailable"}
        )
        report.update(
            exit_code=code,
            installed_bundle_unchanged=(digest(installed_bundle) == installed_before),
            active_desktop_input=False,
            physical_braille="unverified",
            unicode_acceptance="not_established",
            binary_sha256=digest(binary),
            private_bundle_sha256=digest(binary.parent / bundle_rel),
        )
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
        return code

    import websocket

    results = {
        "status": "incomplete",
        "kind": "native_keyboard_selection_matrix",
        "cdp_observation_only": True,
        "caret_setter_calls": 0,
        "selection_setter_calls": 0,
        "samples": [],
    }
    smoke.desktop_code_binary = lambda: str(binary)
    original_launch = smoke.Session.launch

    def launch(self, label, command):
        if label == "vscode":
            command += [
                "--remote-debugging-port=0",
                "--remote-debugging-address=127.0.0.1",
            ]
        return original_launch(self, label, command)

    smoke.Session.launch = launch

    def edit(self, target, *_unused, **_kwargs):
        self.focus(target)
        port_file = self.root / "code-user/DevToolsActivePort"
        self.wait(port_file.exists, "private CDP port")
        port = int(port_file.read_text().splitlines()[0])
        if not 1 <= port <= 65535:
            raise ValueError("Invalid private CDP port")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(f"http://127.0.0.1:{port}/{path}", timeout=5) as response:
                return json.load(response)

        results["browser"] = probe.browser_metadata(get("json/version"))
        page = next(
            item
            for item in get("json/list")
            if item["type"] == "page" and "workbench" in item["url"]
        )
        ws = websocket.create_connection(
            probe.loopback_websocket_url(page["webSocketDebuggerUrl"], port),
            timeout=5,
            suppress_origin=True,
            http_no_proxy=["127.0.0.1"],
        )
        request_id = 0

        def observe_dom():
            nonlocal request_id
            request_id += 1
            # This expression only reads current selection; it cannot set selection.
            expression = """(() => {
              const n=document.activeElement,s=document.getSelection();
              return {text:n.textContent,anchor:s.anchorOffset,focus:s.focusOffset,
                selected:s.toString(),same_node:s.anchorNode===s.focusNode};
            })()"""
            ws.send(
                json.dumps(
                    {
                        "id": request_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": expression, "returnByValue": True},
                    }
                )
            )
            while True:
                reply = json.loads(ws.recv())
                if reply.get("id") == request_id:
                    if "error" in reply or "exceptionDetails" in reply.get(
                        "result", {}
                    ):
                        raise RuntimeError("Private DOM observation failed")
                    return reply["result"]["result"]["value"]

        def units(value):
            return len(value.encode("utf-16-le")) // 2

        text = target.get_text_iface()
        try:
            for fixture_name, value in probe.CASES.items():
                self.key("ctrl+a")
                subprocess.run(
                    ["xclip", "-selection", "clipboard", "-in"],
                    input=value,
                    text=True,
                    encoding="utf-8",
                    check=True,
                    timeout=8,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.key("ctrl+v")
                self.wait(
                    lambda value=value: (
                        self.Atspi.Text.get_text(text, 0, text.get_character_count())
                        == value
                    ),
                    "exact Unicode fixture",
                )
                self.wait(
                    lambda value=value: text.get_caret_offset() == len(value),
                    "fixture end caret",
                )
                n = len(value)
                matrix = [
                    ("full_forward", ["Home", "shift+End"], 0, n),
                    ("full_reverse", ["End", "shift+Home"], n, 0),
                    ("suffix_forward", ["Home", "Right", "Right", "shift+End"], 2, n),
                    (
                        "suffix_reverse",
                        ["End", "shift+Home", "shift+Right", "shift+Right"],
                        n,
                        2,
                    ),
                    ("one_character", ["Home", "Right", "shift+Right"], 1, 2),
                    ("collapse_right", ["Home", "shift+End", "Right"], n, n),
                    ("collapse_left", ["Home", "shift+End", "Left"], 0, 0),
                ]
                if fixture_name == "two_astral":
                    matrix += [
                        (
                            "both_emoji",
                            ["Home", "Right", "shift+Right", "shift+Right"],
                            1,
                            3,
                        ),
                        (
                            "second_emoji",
                            ["Home", "Right", "Right", "shift+Right"],
                            2,
                            3,
                        ),
                    ]
                for case, keys, anchor, focus in matrix:
                    self.key(*keys)
                    # Wait only for the independently expected keyboard/DOM state,
                    # then record AT-SPI once. Provider assertions are never retried.
                    expected_anchor, expected_focus = (
                        units(value[:anchor]),
                        units(value[:focus]),
                    )

                    def ready(
                        value=value,
                        expected_anchor=expected_anchor,
                        expected_focus=expected_focus,
                    ):
                        dom = observe_dom()
                        return (
                            dom
                            if (
                                dom["text"] == value
                                and dom["anchor"] == expected_anchor
                                and dom["focus"] == expected_focus
                                and dom["same_node"]
                            )
                            else None
                        )

                    dom = self.wait(ready, f"{fixture_name}/{case} keyboard DOM state")
                    lo, hi = sorted((anchor, focus))
                    selected = value[lo:hi]
                    provider_count = text.get_n_selections()
                    provider_selection = None
                    provider_error = None
                    if provider_count:
                        try:
                            raw = self.Atspi.Text.get_selection(text, 0)
                            provider_selection = [raw.start_offset, raw.end_offset]
                        except (self.GLib.Error, AttributeError, TypeError) as error:
                            provider_error = type(error).__name__
                    update = smoke.build_text_update(
                        "object:text-selection-changed",
                        target,
                        object_registry={smoke.object_id(target): target},
                    )
                    semantic_selection = (
                        [update["selection_start"], update["selection_end"]]
                        if update
                        else None
                    )
                    copied_ok = None
                    if lo != hi:
                        self.key("ctrl+c")
                        copied = subprocess.check_output(
                            ["xclip", "-selection", "clipboard", "-out"],
                            text=True,
                            encoding="utf-8",
                            timeout=8,
                        )
                        copied_ok = copied == selected
                    expected_provider = [lo, hi] if lo != hi else None
                    sample = {
                        "fixture": fixture_name,
                        "case": case,
                        "keys": keys,
                        "fixture_codepoints": n,
                        "fixture_utf16": units(value),
                        "expected_dom": [expected_anchor, expected_focus],
                        "dom_selection": [dom["anchor"], dom["focus"]],
                        "dom_selected_text_equals_expected": dom["selected"]
                        == selected,
                        "expected_provider_selection": expected_provider,
                        "provider_selection": provider_selection,
                        "provider_error": provider_error,
                        "provider_selection_count": provider_count,
                        "provider_caret": text.get_caret_offset(),
                        "expected_caret": focus,
                        "semantic_selection": semantic_selection,
                        "semantic_text_equals_fixture": bool(
                            update and update["text"] == value
                        ),
                        "copied_equals_expected": copied_ok,
                        "provider_selection_passed": provider_selection
                        == expected_provider,
                        "provider_caret_passed": text.get_caret_offset() == focus,
                    }
                    results["samples"].append(sample)
                    print(json.dumps(sample), flush=True)
        finally:
            ws.close()

    smoke.Session.text_edit = edit
    code = 1
    try:
        code = smoke.run_inner(set(smoke.APPLICATIONS) - {"vscode"})
        results["status"] = "diagnostic_complete" if code == 0 else "incomplete"
    finally:
        results["sample_count"] = len(results["samples"])
        results["provider_selection_passed"] = sum(
            s["provider_selection_passed"] for s in results["samples"]
        )
        (args.output / "matrix.json").write_text(json.dumps(results, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
