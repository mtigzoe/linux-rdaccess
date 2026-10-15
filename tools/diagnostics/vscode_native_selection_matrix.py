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

EXTENDED_CASES = {
    "distinct_astral": "a\U0001f642\U0001d11e\U00010437 caf\u00e9 omega",
    "multiline_astral": "a\U0001f642 caf\u00e9\nb\U0001d11e omega\nc\U00010437 fin",
}


def keyboard_cases(value, *, extended=False, fixture_name=None):
    """Expected endpoints use code points; Ctrl+Home/End span multiline text."""
    home, end = ("ctrl+Home", "ctrl+End") if extended else ("Home", "End")
    n = len(value)
    shift_end = "ctrl+shift+End" if extended else "shift+End"
    shift_home = "ctrl+shift+Home" if extended else "shift+Home"
    cases = [
        ("full_forward", [home, shift_end], 0, n),
        ("full_reverse", [end, shift_home], n, 0),
        ("suffix_forward", [home, "Right", "Right", shift_end], 2, n),
        ("suffix_reverse", [end, shift_home, "shift+Right", "shift+Right"], n, 2),
        ("one_character", [home, "Right", "shift+Right"], 1, 2),
        ("collapse_right", [home, shift_end, "Right"], n, n),
        ("collapse_left", [home, shift_end, "Left"], 0, 0),
    ]
    if fixture_name == "two_astral":
        cases += [
            ("both_emoji", [home, "Right", "shift+Right", "shift+Right"], 1, 3),
            ("second_emoji", [home, "Right", "Right", "shift+Right"], 2, 3),
        ]
    if fixture_name == "distinct_astral":
        cases += [
            (
                "three_supplementary",
                [home, "Right", "shift+Right", "shift+Right", "shift+Right"],
                1,
                4,
            ),
            (
                "third_supplementary",
                [home, "Right", "Right", "Right", "shift+Right"],
                3,
                4,
            ),
        ]
    return cases


def sample_passes(sample):
    """A diagnostic exit alone cannot prove provider or semantic correctness."""
    return (
        all(
            sample.get(field) is True
            for field in (
                "dom_selected_text_equals_expected",
                "provider_selection_passed",
                "provider_caret_passed",
                "semantic_selection_passed",
                "semantic_text_equals_fixture",
            )
        )
        and "copied_equals_expected" in sample
        and "expected_provider_selection" in sample
        and (
            sample["copied_equals_expected"] is True
            if sample["expected_provider_selection"] is not None
            else sample["copied_equals_expected"] is None
        )
    )


def routing_positions(value):
    return [index for index, character in enumerate(value) if ord(character) > 0xFFFF]


def matrix_result_passes(
    results, fixtures, *, extended=False, route_continuation=False
):
    expected = {
        (fixture, case)
        for fixture, value in fixtures.items()
        for case, *_ in keyboard_cases(value, extended=extended, fixture_name=fixture)
    }
    samples = results.get("samples", [])
    observed = [(sample.get("fixture"), sample.get("case")) for sample in samples]
    if (
        len(observed) != len(expected)
        or set(observed) != expected
        or not all(sample_passes(sample) for sample in samples)
    ):
        return False
    expected_routes = (
        {
            (fixture, point)
            for fixture, value in fixtures.items()
            for point in routing_positions(value)
        }
        if route_continuation
        else set()
    )
    routes = results.get("routes", [])
    observed_routes = [
        (route.get("fixture"), route.get("requested_codepoint")) for route in routes
    ]
    return (
        len(observed_routes) == len(expected_routes)
        and set(observed_routes) == expected_routes
        and all(
            route.get("passed") is True
            and [item.get("key") for item in route.get("observations", [])]
            == [None, "Right", "Left"]
            for route in routes
        )
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--require-correct-selection", action="store_true")
    parser.add_argument("--route-continuation", action="store_true")
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
        if args.extended:
            command.append("--extended")
        if args.require_correct_selection:
            command.append("--require-correct-selection")
        if args.route_continuation:
            command.append("--route-continuation")
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
        "routes": [],
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
            fixtures = EXTENDED_CASES if args.extended else probe.CASES
            for fixture_name, value in fixtures.items():
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
                matrix = keyboard_cases(
                    value, extended=args.extended, fixture_name=fixture_name
                )
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
                    # Keep the first observation as the strict result. A second
                    # read after the clipboard action diagnoses delayed provider
                    # state; it never changes an earlier failing selection.
                    later_count = None
                    later_selection = None
                    later_error = None
                    try:
                        later_count = text.get_n_selections()
                        if later_count:
                            later = self.Atspi.Text.get_selection(text, 0)
                            later_selection = [later.start_offset, later.end_offset]
                    except (self.GLib.Error, AttributeError, TypeError) as error:
                        later_error = type(error).__name__
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
                        "post_clipboard_selection_count": later_count,
                        "post_clipboard_selection": later_selection,
                        "post_clipboard_selection_error": later_error,
                        "provider_caret": text.get_caret_offset(),
                        "expected_caret": focus,
                        "semantic_selection": semantic_selection,
                        "semantic_selection_passed": semantic_selection
                        == (expected_provider if expected_provider else [None, None]),
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
                if args.route_continuation:
                    for point in routing_positions(value):
                        results["caret_setter_calls"] += 1
                        accepted = smoke.set_caret_offset(target, point)
                        initial_provider_caret = text.get_caret_offset()
                        # Keep the normal strict runner's existing readback wait.
                        # This sends no second setter or keyboard action.
                        self.wait(
                            lambda point=point: text.get_caret_offset() == point,
                            f"{fixture_name} route readback {point}",
                        )
                        observations = []
                        for key, expected in (
                            (None, point),
                            ("Right", point + 1),
                            ("Left", point),
                        ):
                            if key:
                                self.key(key)
                            expected_units = units(value[:expected])

                            def routed_dom_ready(
                                expected_units=expected_units, value=value
                            ):
                                dom = observe_dom()
                                return (
                                    dom
                                    if (
                                        dom["text"] == value
                                        and dom["anchor"]
                                        == dom["focus"]
                                        == expected_units
                                        and dom["selected"] == ""
                                    )
                                    else None
                                )

                            try:
                                dom = self.wait(
                                    routed_dom_ready,
                                    f"{fixture_name} routed keyboard DOM {expected}",
                                )
                            except AssertionError:
                                dom = observe_dom()
                                results["route_failure"] = {
                                    "fixture": fixture_name,
                                    "requested_codepoint": point,
                                    "key": key,
                                    "expected_caret": expected,
                                    "expected_dom_utf16": expected_units,
                                    "dom_anchor_utf16": dom["anchor"],
                                    "dom_focus_utf16": dom["focus"],
                                    "dom_text_equals_fixture": dom["text"] == value,
                                    "dom_text_codepoints": len(dom["text"]),
                                    "provider_caret": text.get_caret_offset(),
                                    "provider_character_count": text.get_character_count(),
                                }
                                raise
                            update = smoke.build_text_update(
                                "object:text-caret-moved",
                                target,
                                object_registry={smoke.object_id(target): target},
                            )
                            observations.append(
                                {
                                    "key": key,
                                    "expected_caret": expected,
                                    "expected_dom_utf16": expected_units,
                                    "dom_caret_utf16": dom["focus"],
                                    "provider_caret": text.get_caret_offset(),
                                    "semantic_caret": update.get("caret_offset")
                                    if update
                                    else None,
                                }
                            )
                        route = {
                            "fixture": fixture_name,
                            "requested_codepoint": point,
                            "accepted": accepted,
                            "initial_provider_caret": initial_provider_caret,
                            "observations": observations,
                        }
                        route["passed"] = accepted and all(
                            item["provider_caret"] == item["expected_caret"]
                            and item["semantic_caret"] == item["expected_caret"]
                            for item in observations
                        )
                        results["routes"].append(route)
                        print(json.dumps(route), flush=True)
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
        results["fully_correct_samples"] = sum(
            sample_passes(s) for s in results["samples"]
        )
        results["routes_passed"] = sum(route["passed"] for route in results["routes"])
        if args.require_correct_selection and not matrix_result_passes(
            results,
            EXTENDED_CASES if args.extended else probe.CASES,
            extended=args.extended,
            route_continuation=args.route_continuation,
        ):
            code = 1
            results["status"] = "selection_failure"
        (args.output / "matrix.json").write_text(json.dumps(results, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
