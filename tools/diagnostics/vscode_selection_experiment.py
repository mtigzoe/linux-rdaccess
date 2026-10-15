#!/usr/bin/env python3
"""Test #79 using a private Code copy, Xvfb, D-Bus and disposable profiles.

Optional upstream TypeScript is transpiled into five methods of the private
bundle only. The installed bundle must match the reviewed 1.141.0 build.
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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.diagnostics import real_gui_atspi_smoke as smoke

BUNDLE = Path("resources/app/out/vs/workbench/workbench.desktop.main.js")
REVIEWED_SHA256 = "631c1d79c4f3af9177ca23a70cfe0cf2586a692678bd897af6c869324160d905"
BOUNDARIES = {
    "updateScreenReaderContent": "updateScrollTop",
    "_setSelectionChangeListener": "_getScreenReaderContentState",
    "onFocusChange": "onConfigurationChanged",
    "onWillCut": "onWillPaste",
    "onWillPaste": "_setIgnoreSelectionChangeTime",
}
CASES = {
    "ascii": "lrd code text",
    "unicode": "a🙂 café omega",
    "multiline": "alpha\nbravo\ncharlie",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_methods(source, methods):
    if set(methods) != set(BOUNDARIES):
        raise ValueError("Exactly the reviewed upstream methods are required")
    start = source.index("var K0e=class extends ")
    prefix, body = source[:start], source[start:]

    def declaration(name, start=0):
        position = body.index(name + "(", start)
        while position > 0 and body[position - 1] == ".":
            position = body.index(name + "(", position + len(name) + 1)
        return position

    # Find all original methods before replacing any: replacement source can
    # contain the name of a neighboring method in a comment or function call.
    changes = []
    for name, next_name in BOUNDARIES.items():
        first = declaration(name)
        last = declaration(next_name, first + len(name) + 1)
        changes.append((body[first:last], methods[name]))
    for before, after in changes:
        if before not in body:
            raise ValueError("Overlapping or missing bundled method")
        body = body.replace(before, after, 1)
    return prefix + body


def prepare(args):
    original = args.code_root.resolve()
    if digest(original / BUNDLE) != REVIEWED_SHA256:
        raise ValueError("Unsupported Code bundle; refusing unreviewed replacements")
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Output must be a new private directory")
    output.mkdir(parents=True, mode=0o700)
    private = output / "code"
    shutil.copytree(
        original,
        private,
        symlinks=True,
        ignore=shutil.ignore_patterns("chrome-sandbox"),
    )
    (private / "chrome-sandbox").symlink_to(original / "chrome-sandbox")
    bundle = private / BUNDLE
    if (
        bundle.resolve().is_relative_to(original)
        or bundle.stat().st_ino == (original / BUNDLE).stat().st_ino
    ):
        raise ValueError("Private bundle must be independent of the installed file")
    metadata = {
        "original_root": str(original),
        "original_sha256": REVIEWED_SHA256,
        "private_binary": str(private / "code"),
        "source_sha256": None,
    }
    if args.source:
        compiler = (
            original
            / "resources/app/extensions/node_modules/typescript/lib/typescript.js"
        )
        env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
        result = subprocess.run(
            [
                str(original / "code"),
                str(Path(__file__).with_name("vscode_selection_contract.cjs")),
                str(args.source.resolve()),
                str(compiler),
                "--emit-methods",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        compiled = json.loads(result.stdout)
        metadata.update(
            source_sha256=digest(args.source),
            node=compiled["node"],
            typescript=compiled["typescript"],
        )
        temporary = bundle.with_suffix(".experiment.tmp")
        temporary.write_text(patch_methods(bundle.read_text(), compiled["methods"]))
        temporary.replace(bundle)
        (output / "compiled-methods.json").write_text(json.dumps(compiled, indent=2))
        checked = subprocess.run(
            [str(private / "code"), "--check", str(bundle)],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if checked.returncode:
            errors = [
                line
                for line in checked.stderr.splitlines()
                if line.startswith("SyntaxError:")
            ]
            raise ValueError(
                "Private bundle syntax check failed: " + "; ".join(errors)[:500]
            )
    metadata["private_sha256"] = digest(bundle)
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return output, metadata


def run_inner(args):
    output = args.output.resolve()
    metadata = json.loads((output / "metadata.json").read_text())
    if digest(Path(metadata["original_root"]) / BUNDLE) != metadata["original_sha256"]:
        raise ValueError("Installed bundle changed since preparation")
    private = Path(metadata["private_binary"])
    if not private.resolve().is_relative_to(output):
        raise ValueError("Private binary outside experiment directory")
    smoke.desktop_code_binary = lambda: str(private)
    state = {
        "case": args.case,
        "caret_requests": 0,
        "readback": None,
        "after_right": None,
        "after_left": None,
        "clipboard": False,
        "focus_return_continuation": False,
    }
    node = None
    value = CASES[args.case]
    original_route, original_check = smoke.set_caret_offset, smoke.Session.check
    original_edit, original_close = smoke.Session.text_edit, smoke.Session.close

    def route(target, offset):
        nonlocal node
        node = target
        state.update(
            before=target.get_text_iface().get_caret_offset(),
            requested=offset,
            request_utc=datetime.now(timezone.utc).isoformat(),  # noqa: UP017 -- Python 3.10
        )
        state["caret_requests"] += 1
        result = original_route(target, offset)
        state["accepted"] = result
        return result

    def check(self, label, condition=True):
        result = original_check(self, label, condition)
        if label == "VS Code editor: routed caret is confirmed by the provider":
            state["readback"] = node.get_text_iface().get_caret_offset()
        elif label == "Routed caret: keyboard Right reaches 2":
            state["after_right"] = node.get_text_iface().get_caret_offset()
        elif label == "Routed caret: keyboard Left reaches 1":
            state["after_left"] = node.get_text_iface().get_caret_offset()
        elif (
            label
            == "VS Code: typed palette query exposes command list and Escape restores editor focus"
        ):
            self.key("Left")
            self.wait(
                lambda: node.get_text_iface().get_caret_offset() == len(value) - 1,
                "Code focus-return keyboard continuation",
            )
            self.key("Right")
            self.wait(
                lambda: node.get_text_iface().get_caret_offset() == len(value),
                "Code focus-return caret",
            )
            state["focus_return_continuation"] = True
        return result

    def edit(self, target, _value, label, **kwargs):
        nonlocal node
        node = target
        original_edit(self, target, value, label, **kwargs)
        text = target.get_text_iface()

        def contents():
            return self.Atspi.Text.get_text(text, 0, text.get_character_count())

        # This clipboard belongs to the verified private Xvfb display.
        self.key("ctrl+a", "ctrl+c", "ctrl+End", "ctrl+v")
        self.wait(lambda: contents() == value + value, "Code private clipboard paste")
        state["clipboard_paste"] = True
        self.key("ctrl+z")
        self.wait(lambda: contents() == value, "Code private paste undo")
        state["clipboard_undo"] = True
        self.key("ctrl+a", "ctrl+x")
        # Code exposes an empty document as one accessible newline in its
        # simple screen-reader representation, with the caret still at zero.
        self.wait(
            lambda: contents() in ("", "\n") and text.get_caret_offset() == 0,
            "Code private clipboard cut",
        )
        state["clipboard_cut"] = True
        self.key("ctrl+v")
        self.wait(lambda: contents() == value, "Code private cut/paste restore")
        state["clipboard"] = True

    def close(self):
        if node is not None:
            try:
                text = node.get_text_iface()
                state["fixture_final_caret_before_cleanup"] = text.get_caret_offset()
                state["provider_character_count"] = text.get_character_count()
                # AT-SPI, Python and Chromium selection APIs may count Unicode
                # differently. Record numeric lengths only, never editable text.
                observed = self.Atspi.Text.get_text(text, 0, text.get_character_count())
                state["expected_codepoints"] = len(value)
                state["expected_utf16_units"] = len(value.encode("utf-16-le")) // 2
                state["observed_codepoints"] = len(observed)
                state["observed_utf16_units"] = len(observed.encode("utf-16-le")) // 2
                state["observed_equals_fixture"] = observed == value
                if text.get_n_selections():
                    selection = self.Atspi.Text.get_selection(text, 0)
                    state["provider_selection"] = [
                        selection.start_offset,
                        selection.end_offset,
                    ]
                update = smoke.build_text_update(
                    "object:text-selection-changed",
                    node,
                    object_registry={smoke.object_id(node): node},
                )
                if update:
                    state["semantic_text_length"] = len(update["text"])
                    state["semantic_selection"] = [
                        update["selection_start"],
                        update["selection_end"],
                    ]
            except Exception as error:  # noqa: BLE001 -- provider may exit during cleanup
                state["diagnostics_read_error"] = type(error).__name__
        original_close(self)

    smoke.set_caret_offset, smoke.Session.check = route, check
    smoke.Session.text_edit, smoke.Session.close = edit, close
    try:
        result = smoke.run_inner(set(smoke.APPLICATIONS) - {"vscode"})
        complete = (
            state["caret_requests"] == 1
            and state["readback"] == 1
            and state["after_right"] == 2
            and state["after_left"] == 1
            and state["clipboard"]
            and state["focus_return_continuation"]
        )
        state["status"] = "pass" if result == 0 and complete else "fail"
        return 0 if state["status"] == "pass" else 1
    except BaseException as error:
        state.update(status="fail", failure_class=type(error).__name__)
        raise
    finally:
        (Path(os.environ["LRD_GUI_PRIVATE"]) / "selection-result.json").write_text(
            json.dumps(state, indent=2)
        )


def run_outer(args):
    output, metadata = prepare(args)
    results = []
    for run in range(1, args.runs + 1):
        fixture = Path(tempfile.mkdtemp(prefix="l79-", dir="/tmp"))
        env = smoke.isolated_environment(fixture)
        log = fixture / "experiment.log"
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
            "--case",
            args.case,
        ]
        with log.open("w") as stream:
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
        path = fixture / "selection-result.json"
        result = (
            json.loads(path.read_text()) if path.exists() else {"status": "unavailable"}
        )
        result.update(run=run, exit_code=code)
        evidence = output / fixture.name
        evidence.mkdir()
        result["evidence_directory"] = evidence.name
        for name in (
            "experiment.log",
            "selection-result.json",
            "vscode.log",
            "wm.log",
            "atspi.log",
        ):
            path = fixture / name
            if path.is_file():
                shutil.copyfile(path, evidence / name)
        results.append(result)
        print(json.dumps(result), flush=True)
        if code or result["status"] != "pass":
            break
    unchanged = (
        digest(Path(metadata["original_root"]) / BUNDLE) == metadata["original_sha256"]
    )
    report = {
        "metadata": metadata,
        "runs": results,
        "installed_bundle_unchanged": unchanged,
        "physical_braille": "unverified",
        "active_desktop_input": False,
    }
    (output / "results.json").write_text(json.dumps(report, indent=2))
    return (
        0
        if unchanged
        and len(results) == args.runs
        and all(
            item.get("status") == "pass" and item["exit_code"] == 0 for item in results
        )
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
        "--source",
        type=Path,
        help="Reviewed upstream TypeScript file with patch applied",
    )
    parser.add_argument("--runs", type=int, choices=range(1, 13), default=1)
    parser.add_argument("--case", choices=CASES, default="ascii")
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Linux private Xvfb/D-Bus fixture required")
    return run_inner(args) if args.inner else run_outer(args)


if __name__ == "__main__":
    raise SystemExit(main())
