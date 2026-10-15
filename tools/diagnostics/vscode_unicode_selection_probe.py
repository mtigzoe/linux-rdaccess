#!/usr/bin/env python3
"""Compare DOM, AT-SPI and semantic Unicode selection in a private Code copy.

Completion means diagnostic evidence was collected, not Unicode acceptance.
This selection-only probe never requests caret routing; the normal GUI runner
retains its strict routing and selection assertions. Requires websocket-client.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.diagnostics import real_gui_atspi_smoke as smoke
from tools.diagnostics import vscode_selection_experiment as experiment

CASES = {
    "bmp": "a café omega",
    "astral": "a🙂 café omega",
    "two_astral": "a🙂🙂 café omega",
}
DOM_SELECTION = """(() => {
    const n = document.activeElement, s = document.getSelection();
    return {utf16: n.textContent.length, codepoints: [...n.textContent].length,
        anchor: s.anchorOffset, focus: s.focusOffset,
        selected_utf16: s.toString().length,
        selected_codepoints: [...s.toString()].length};
})()"""


def selection_comparison(value, dom, provider_selection, semantic_selection):
    """Compare distinct coordinate spaces without correcting provider offsets."""
    points, units = len(value), len(value.encode("utf-16-le")) // 2
    return {
        "dom_full_selection": (
            dom["codepoints"] == points
            and dom["utf16"] == units
            and sorted((dom["anchor"], dom["focus"])) == [0, units]
            and dom["selected_codepoints"] == points
            and dom["selected_utf16"] == units
        ),
        "provider_full_selection": provider_selection == [0, points],
        "semantic_matches_provider": semantic_selection == provider_selection,
        "provider_end_shortfall": points - provider_selection[1],
    }


def browser_metadata(raw):
    """Keep runtime versions, excluding session-specific debugger URLs."""
    return {
        key: raw[key]
        for key in ("Browser", "Protocol-Version", "V8-Version")
        if key in raw
    }


def loopback_websocket_url(value, port):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "ws"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != port
        or parsed.username
        or parsed.password
    ):
        raise ValueError("CDP must use the private loopback endpoint")
    return value


def run_inner(args):
    # Import only during Linux execution; unit tests can import on Windows.
    import websocket

    output = args.output.resolve()
    metadata = json.loads((output / "metadata.json").read_text())
    original_bundle = Path(metadata["original_root"]) / experiment.BUNDLE
    private = Path(metadata["private_binary"])
    if (
        not private.resolve().is_relative_to(output)
        or experiment.digest(original_bundle) != metadata["original_sha256"]
        or experiment.digest(private.parent / experiment.BUNDLE)
        != metadata["private_sha256"]
    ):
        raise ValueError("Prepared private copy or installed bundle changed")
    result = {
        "kind": "selection_only_no_route",
        "status": "diagnostic_incomplete",
        "unicode_acceptance": "not_established",
        "caret_requests": 0,
        "samples": [],
    }
    original_binary = smoke.desktop_code_binary
    original_launch, original_edit = smoke.Session.launch, smoke.Session.text_edit

    def launch(self, label, command):
        if label == "vscode":
            command = command + [
                "--remote-debugging-port=0",
                "--remote-debugging-address=127.0.0.1",
            ]
        return original_launch(self, label, command)

    def edit(self, target, _value, _label, **_kwargs):
        self.focus(target)
        port_file = self.root / "code-user/DevToolsActivePort"
        self.wait(port_file.exists, "private Code CDP port")
        port = int(port_file.read_text().splitlines()[0])
        if not 1 <= port <= 65535:
            raise ValueError("Invalid private CDP port")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(f"http://127.0.0.1:{port}/{path}", timeout=5) as response:
                return json.load(response)

        result["browser"] = browser_metadata(get("json/version"))
        page = next(
            item
            for item in get("json/list")
            if item["type"] == "page" and "workbench" in item["url"]
        )
        ws = websocket.create_connection(
            loopback_websocket_url(page["webSocketDebuggerUrl"], port),
            timeout=5,
            suppress_origin=True,
            http_no_proxy=["127.0.0.1"],
        )
        request_id = 0

        def evaluate(expression):
            nonlocal request_id
            request_id += 1
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
                        raise RuntimeError("Private DOM selection query failed")
                    return reply["result"]["result"]["value"]

        text = target.get_text_iface()
        try:
            for case, value in CASES.items():
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
                self.key("ctrl+a")
                self.wait(lambda: text.get_n_selections() == 1, "selection exists")
                selection = self.Atspi.Text.get_selection(text, 0)
                update = smoke.build_text_update(
                    "object:text-selection-changed",
                    target,
                    object_registry={smoke.object_id(target): target},
                )
                if update is None:
                    raise RuntimeError("Semantic selection snapshot unavailable")
                dom = evaluate(DOM_SELECTION)
                self.key("ctrl+c")
                copied = subprocess.check_output(
                    ["xclip", "-selection", "clipboard", "-out"],
                    text=True,
                    encoding="utf-8",
                    timeout=8,
                )
                provider_selection = [selection.start_offset, selection.end_offset]
                semantic_selection = [
                    update["selection_start"],
                    update["selection_end"],
                ]
                sample = {
                    "case": case,
                    "fixture_codepoints": len(value),
                    "fixture_utf16": len(value.encode("utf-16-le")) // 2,
                    "provider_count": text.get_character_count(),
                    "provider_caret": text.get_caret_offset(),
                    "provider_text_equals_fixture": True,
                    "provider_selection": provider_selection,
                    "provider_selected_text_codepoints": len(
                        self.Atspi.Text.get_text(
                            text, selection.start_offset, selection.end_offset
                        )
                    ),
                    "semantic_selection": semantic_selection,
                    "semantic_text_equals_fixture": update["text"] == value,
                    "semantic_text_codepoints": len(update["text"]),
                    "dom": dom,
                    "copied_equals_fixture": copied == value,
                }
                sample.update(
                    selection_comparison(
                        value, dom, provider_selection, semantic_selection
                    )
                )
                result["samples"].append(sample)
                print(json.dumps(sample), flush=True)
        finally:
            ws.close()

    smoke.desktop_code_binary = lambda: str(private)
    smoke.Session.launch, smoke.Session.text_edit = launch, edit
    try:
        code = smoke.run_inner(set(smoke.APPLICATIONS) - {"vscode"})
        if code == 0 and len(result["samples"]) == len(CASES):
            result["status"] = "diagnostic_complete"
        return code if result["status"] == "diagnostic_complete" else 1
    except BaseException as error:
        result["failure_class"] = type(error).__name__
        raise
    finally:
        smoke.desktop_code_binary = original_binary
        smoke.Session.launch, smoke.Session.text_edit = original_launch, original_edit
        (Path(os.environ["LRD_GUI_PRIVATE"]) / "selection-probe.json").write_text(
            json.dumps(result, indent=2)
        )


def run_outer(args):
    output, metadata = experiment.prepare(args)
    fixture = Path(tempfile.mkdtemp(prefix="lrd-unicode-", dir="/tmp"))
    env = smoke.isolated_environment(fixture)
    # Expected-failure policy is irrelevant to this separate selection probe.
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
        str(Path(__file__).resolve()),
        "--execute",
        "--inner",
        "--output",
        str(output),
    ]
    with (fixture / "probe.log").open("w") as stream:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            code = process.wait(timeout=100)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            code = 2
    evidence = output / "session"
    evidence.mkdir()
    for name in (
        "probe.log",
        "selection-probe.json",
        "vscode.log",
        "wm.log",
        "atspi.log",
    ):
        if (fixture / name).is_file():
            shutil.copyfile(fixture / name, evidence / name)
    path = evidence / "selection-probe.json"
    result = (
        json.loads(path.read_text())
        if path.exists()
        else {"status": "diagnostic_unavailable"}
    )
    unchanged = (
        experiment.digest(Path(metadata["original_root"]) / experiment.BUNDLE)
        == metadata["original_sha256"]
    )
    report = {
        "metadata": metadata,
        "diagnostic": result,
        "exit_code": code,
        "installed_bundle_unchanged": unchanged,
        "active_desktop_input": False,
        "physical_braille": "unverified",
        "unicode_acceptance": "not_established",
    }
    (output / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    return (
        0
        if code == 0 and unchanged and result["status"] == "diagnostic_complete"
        else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New private evidence directory"
    )
    parser.add_argument("--code-root", type=Path, default=Path("/usr/share/code"))
    parser.add_argument(
        "--source", type=Path, help="Reviewed upstream TypeScript candidate"
    )
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Linux private Xvfb/D-Bus fixture required")
    return run_inner(args) if args.inner else run_outer(args)


if __name__ == "__main__":
    raise SystemExit(main())
