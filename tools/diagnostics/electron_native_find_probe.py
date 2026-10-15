#!/usr/bin/env python3
"""Observe native find-in-page in a private, pinned Electron runtime.

Completion means diagnostic evidence was collected, not physical acceptance.
Preparation copies the installed runtime without its Code application, then
adds a minimal fixture. An optional reviewed candidate executable is copied
from a previous private native-selection experiment; no binary is patched here.
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
from pathlib import Path

APP = r"""const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const root=process.env.LRD_GUI_PRIVATE;
const record=extra=>fs.appendFileSync(path.join(root,'app-events.jsonl'),JSON.stringify(extra)+'\n');
app.setPath('userData',path.join(root,'electron-user'));
app.setName('LRD native selection fixture');
app.commandLine.appendSwitch('force-renderer-accessibility','complete');
let win,last=0;
const pending=new Map();
const observe=()=>win.webContents.executeJavaScript(`(()=>{
 const s=document.getSelection(),n=document.querySelector('p');
 return {anchor:s.anchorOffset,focus:s.focusOffset,selected:s.toString(),
   text:n.textContent};})()`);
const ack=async(id,extra)=>{
 const dom=await observe();
 if(id===last)fs.writeFileSync(path.join(root,'ack.json'),JSON.stringify({id,dom,...extra}));
};
app.whenReady().then(async()=>{
 win=new BrowserWindow({width:900,height:600,webPreferences:{contextIsolation:true,sandbox:true}});
 win.webContents.on('found-in-page',async(_event,result)=>{
   record({event:'found-in-page',result});
   const id=pending.get(result.requestId);
   if(result.finalUpdate && id!==undefined){
     pending.delete(result.requestId);
     await ack(id,{requestId:result.requestId,matches:result.matches,
                   activeMatchOrdinal:result.activeMatchOrdinal});
   }
 });
 await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent(
   '<!doctype html><meta charset=utf-8><title>LRD private native selection</title>'+ 
   '<p style="white-space:pre-wrap">'+fs.readFileSync(path.join(root,'fixture.txt'),'utf8')+'</p>'));
 await ack(0,{ready:true});
 setInterval(async()=>{
   let command;try{command=JSON.parse(fs.readFileSync(path.join(root,'command.json'),'utf8'));}catch{return;}
   if(command.id<=last)return;last=command.id;
   record({event:'command',id:last,action:command.action});
   if(command.action==='find'){
     // Electron 43 documents findNext:true for an initial search request.
     const requestId=win.webContents.findInPage(command.query,{forward:true,findNext:true,matchCase:true});
     pending.set(requestId,command.id);
     record({event:'find-issued',id:command.id,requestId});
   }else if(command.action==='clear'){
     pending.clear();
     win.webContents.stopFindInPage('clearSelection');
     await ack(command.id,{cleared:true});
   }
 },25);
});
app.on('window-all-closed',()=>app.quit());
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection_observations_match(observations, expected, dom, fixture):
    """Require observed fixture nodes and an empty DOM selection for fallback."""
    if not observations or dom["text"] != fixture or dom["selected"] != "":
        return False
    active = [item for item in observations if item["selection_count"]]
    if expected is None:
        return not active
    return bool(active) and all(
        item["selection_count"] == 1 and item["selection"] == expected
        for item in active
    )


def find_cases(value):
    """Search visible line text while expecting document code-point offsets."""
    if "\n" in value:
        lines = value.split("\n")
        second_start = len(lines[0]) + 1
        return [
            ("first_line", lines[0], 0, len(lines[0])),
            ("second_line", lines[1], second_start, second_start + len(lines[1])),
            (
                "second_line_supplementary",
                lines[1][1:2],
                second_start + 1,
                second_start + 2,
            ),
        ]
    return [
        ("full", value, 0, len(value)),
        ("suffix", value[2:], 2, len(value)),
        ("one_character", value[1:2], 1, 2),
    ]


def find_result_passes(result, value):
    expected = {"initial_no_selection"} | {
        prefix + name
        for name, *_ in find_cases(value)
        for prefix in ("find_", "clear_")
    }
    samples = result.get("samples", [])
    observed = [sample.get("case") for sample in samples]
    return (
        len(observed) == len(expected)
        and set(observed) == expected
        and all(sample.get("passed") is True for sample in samples)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument(
        "--runtime",
        type=Path,
        required=True,
        help="New /tmp runtime directory with --prepare",
    )
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument(
        "--candidate-binary",
        type=Path,
        help="Reviewed private candidate executable; only with --prepare",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fixture",
        choices=("bmp", "astral", "two_astral", "distinct_astral", "multiline_astral"),
        default="astral",
    )
    parser.add_argument("--inner", action="store_true")
    parser.add_argument("--require-correct-selection", action="store_true")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Linux private Xvfb/D-Bus fixture required")
    sys.path.insert(0, str(args.repo.resolve()))
    from tools.diagnostics import real_gui_atspi_smoke as smoke
    from tools.diagnostics import vscode_native_selection_experiment as native
    from tools.diagnostics import vscode_unicode_selection_probe as probe

    installed = Path("/usr/share/code/code")
    if digest(installed) != native.NATIVE_SHA256:
        raise ValueError("Exact reviewed original native executable required")
    runtime = args.runtime.resolve()
    if not runtime.is_relative_to(Path("/tmp")):
        raise ValueError("Only a disposable runtime below /tmp is permitted")
    if args.prepare:
        if runtime.exists():
            raise ValueError("Runtime must be new")
        candidate = None
        if args.candidate_binary:
            candidate = args.candidate_binary.resolve()
            if (
                not candidate.is_relative_to(Path("/tmp"))
                or digest(candidate) != native.CANDIDATE_SHA256
            ):
                raise ValueError("Exact reviewed private candidate executable required")

        def ignore(directory, names):
            return (
                ["app"]
                if Path(directory) == Path("/usr/share/code/resources")
                else (
                    ["chrome-sandbox"]
                    if Path(directory) == Path("/usr/share/code")
                    else []
                )
            )

        shutil.copytree("/usr/share/code", runtime, symlinks=True, ignore=ignore)
        (runtime / "chrome-sandbox").symlink_to("/usr/share/code/chrome-sandbox")
        app = runtime / "resources/app"
        app.mkdir()
        (app / "package.json").write_text(
            json.dumps(
                {
                    "name": "lrd-native-selection-fixture",
                    "version": "0.0.0",
                    "main": "main.cjs",
                }
            )
        )
        (app / "main.cjs").write_text(APP)
        if candidate:
            shutil.copyfile(candidate, runtime / "code")
        print(
            json.dumps(
                {
                    "runtime": str(runtime),
                    "binary_sha256": digest(runtime / "code"),
                    "source_installed_binary_sha256": digest(
                        Path("/usr/share/code/code")
                    ),
                }
            )
        )
        return 0
    if args.candidate_binary:
        parser.error("--candidate-binary requires --prepare")
    if not args.output:
        parser.error("--output is required to run")
    args.output = args.output.resolve()
    if not args.output.is_relative_to(Path("/tmp")):
        raise ValueError("Only a disposable output below /tmp is permitted")
    if (
        digest(runtime / "code") not in (native.NATIVE_SHA256, native.CANDIDATE_SHA256)
        or (runtime / "resources/app/main.cjs").read_text() != APP
    ):
        raise ValueError("Reviewed native executable and exact fixture required")
    value = (
        probe.CASES[args.fixture]
        if args.fixture in probe.CASES
        else native.experiment.CASES[args.fixture]
    )
    if not args.inner:
        args.output.mkdir(mode=0o700)
        (args.output / "fixture.txt").write_text(value)
        installed_before = digest(Path("/usr/share/code/code"))
        env = smoke.isolated_environment(args.output)
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
            "--runtime",
            str(runtime),
            "--output",
            str(args.output),
            "--fixture",
            args.fixture,
            "--inner",
        ]
        if args.require_correct_selection:
            command.append("--require-correct-selection")
        with (args.output / "probe.log").open("w") as stream:
            process = subprocess.Popen(
                command,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                code = 2
        path = args.output / "matrix.json"
        data = (
            json.loads(path.read_text()) if path.exists() else {"status": "unavailable"}
        )
        data.update(
            exit_code=code,
            installed_binary_unchanged=digest(Path("/usr/share/code/code"))
            == installed_before,
            private_binary_sha256=digest(runtime / "code"),
            active_desktop_input=False,
            physical_braille="unverified",
        )
        (args.output / "report.json").write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data), flush=True)
        return code

    smoke.verify_private_display()
    os.environ.pop("AT_SPI_BUS_ADDRESS", None)
    root = args.output
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("Private bus required")
    session = smoke.Session(root)
    result = {
        "status": "incomplete",
        "kind": "native_electron_find_in_page",
        "fixture": args.fixture,
        "samples": [],
        "selection_setter_calls": 0,
        "caret_setter_calls": 0,
        "renderer_dom_observation_only": True,
    }
    code = 1
    try:
        session.launch("wm", ["xfwm4", "--replace", "--compositor=off"])
        session.launch(
            "atspi", ["/usr/libexec/at-spi-bus-launcher", "--launch-immediately"]
        )
        session.launch(
            "electron",
            [
                str(runtime / "code"),
                "--disable-gpu",
                "--password-store=basic",
                "--force-renderer-accessibility=complete",
            ],
        )
        ack_path = root / "ack.json"

        def ack_for(number):
            try:
                data = json.loads(ack_path.read_text())
                return data if data["id"] == number else None
            except (FileNotFoundError, json.JSONDecodeError):
                return None

        initial = session.wait(lambda: ack_for(0), "private Electron ready")

        def fixture_nodes():
            found = []
            for node in smoke.walk(session.Atspi.get_desktop(0)):
                try:
                    if "Text" not in node.get_interfaces():
                        continue
                    text = node.get_text_iface()
                    if (
                        session.Atspi.Text.get_text(text, 0, text.get_character_count())
                        == value
                    ):
                        found.append(node)
                except session.GLib.Error:
                    pass
            return found

        session.wait(fixture_nodes, "exact Unicode accessible nodes")

        def measure(label, expected, ack):
            observations = []
            for node in fixture_nodes():
                text = node.get_text_iface()
                count = text.get_n_selections()
                selection = None
                if count:
                    span = session.Atspi.Text.get_selection(text, 0)
                    selection = [span.start_offset, span.end_offset]
                observations.append(
                    {
                        "role": node.get_role_name(),
                        "selection_count": count,
                        "selection": selection,
                        "caret": text.get_caret_offset(),
                        "character_count": text.get_character_count(),
                    }
                )
            passed = selection_observations_match(
                observations, expected, ack["dom"], value
            )
            sample = {
                "case": label,
                "expected_selection": expected,
                "observations": observations,
                "passed": passed,
                "dom_selection_empty": ack["dom"]["selected"] == "",
                "dom_text_equals_fixture": ack["dom"]["text"] == value,
                "dom_anchor": ack["dom"]["anchor"],
                "dom_focus": ack["dom"]["focus"],
                "find_matches": ack.get("matches"),
                "find_active_match_ordinal": ack.get("activeMatchOrdinal"),
                "command_id": ack["id"],
                "request_id": ack.get("requestId"),
            }
            result["samples"].append(sample)
            print(json.dumps(sample), flush=True)

        measure("initial_no_selection", None, initial)
        number = 0
        for case, query, start, end in find_cases(value):
            number += 1
            (root / "command.json").write_text(
                json.dumps({"id": number, "action": "find", "query": query})
            )
            ack = session.wait(
                lambda number=number: ack_for(number), f"find {case} final result"
            )
            if ack["matches"] != value.count(query) or ack["activeMatchOrdinal"] != 1:
                raise AssertionError(
                    "Native find request did not select the expected first match"
                )
            session.wait(
                lambda: any(
                    node.get_text_iface().get_n_selections() for node in fixture_nodes()
                ),
                "native find selection event",
            )
            measure("find_" + case, [start, end], ack)
            number += 1
            (root / "command.json").write_text(
                json.dumps({"id": number, "action": "clear"})
            )
            ack = session.wait(
                lambda number=number: ack_for(number), "clear find result"
            )

            def selection_cleared():
                nodes = fixture_nodes()
                return bool(nodes) and all(
                    node.get_text_iface().get_n_selections() == 0 for node in nodes
                )

            session.wait(selection_cleared, "native find selection cleared")
            measure("clear_" + case, None, ack)
        code = 0
        result["status"] = "diagnostic_complete"
    finally:
        result["passed"] = sum(item["passed"] for item in result["samples"])
        result["sample_count"] = len(result["samples"])
        if args.require_correct_selection and not find_result_passes(result, value):
            code = 1
            result["status"] = "selection_failure"
        (root / "matrix.json").write_text(json.dumps(result, indent=2) + "\n")
        session.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
