"""Opt-in parent: bounded owned GUI children and native process-memory evidence."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.qualification.gui_port_740.common import (
    ROOT,
    runtime,
    source_identity,
    summary,
    visible_render_evidence,
)


def child(python: str, module: str, arguments: list[str], *, timeout=25):
    import psutil

    from src.utils.managed_process import launch_contained
    from src.utils.process_container_v2 import ProcessContainerConfig, build_process_container

    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("QT_"):
            environment.pop(key)
    environment.update(
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        STABLENEW_TEST_MODE="1",
        STABLENEW_NO_WEBUI="1",
    )
    started = time.perf_counter_ns()
    stdout_file, stderr_file = (
        tempfile.TemporaryFile(mode="w+t", encoding="utf8"),
        tempfile.TemporaryFile(mode="w+t", encoding="utf8"),
    )
    container = build_process_container("gui-port-740-synthetic-child", ProcessContainerConfig())
    launched = launch_contained(
        [python, "-m", module, *arguments],
        label="GUI-PORT-740",
        required=os.name == "nt",
        require_suspended=True,
        container=container,
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    process = launched.process
    peak = 0
    descendants = set()
    timed_out = False
    try:
        while process.poll() is None:
            if (time.perf_counter_ns() - started) / 1e9 > timeout:
                timed_out = True
                container.kill_all()  # only this launch's anonymous owned container
                break
            try:
                probe = psutil.Process(process.pid)
                children = probe.children(recursive=True)
                # Windows venv python.exe is a launcher. Include the actual Python
                # interpreter/native Qt footprint, not merely the launcher's ~5 MB.
                working_set = probe.memory_info().rss
                for owned in children:
                    try:
                        descendants.add((owned.pid, owned.create_time()))
                        working_set += owned.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, working_set)
            except psutil.Error:
                pass
            time.sleep(0.01)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            container.kill_all()
            process.wait(timeout=5)
        # The container belongs solely to this launch, including the Windows venv
        # redirector's interpreter. It cannot retain descendants after owner exit.
        container.teardown()
    stdout_file.seek(0)
    stderr_file.seek(0)
    stdout, stderr = stdout_file.read(), stderr_file.read()
    stdout_file.close()
    stderr_file.close()
    exited = time.perf_counter_ns()
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            events.append({"unparsed_stdout": line})
    result = next((e for e in events if e.get("event") == "result"), None)
    first = next((e for e in events if e.get("event") == "first_visible"), None)
    # Windows' venv launcher/native console can outlive its exit notification briefly.
    # Verify quiescence with an identity-bound deadline, never waive or kill a survivor.
    settle = time.perf_counter()
    while True:
        surviving = []
        for pid, created in descendants:
            try:
                candidate = psutil.Process(pid)
                if candidate.create_time() == created and candidate.is_running():
                    surviving.append(pid)
            except psutil.Error:
                pass
        if not surviving or time.perf_counter() - settle >= 2:
            break
        time.sleep(0.01)
    return {
        "exit_code": process.returncode,
        "stderr": stderr,
        "timeout": timed_out,
        "contained": launched.contained,
        "events": events,
        "result": result,
        "peak_sampled_working_set": peak,
        "startup_ms": (first["clock_ns"] - started) / 1e6 if first else None,
        "close_to_exit_ms": (exited - result["close_started_ns"]) / 1e6
        if result and result.get("close_started_ns")
        else None,
        "surviving_descendants": surviving,
        "observed_descendants": sorted(descendants),
        "descendant_quiescence_ms": (time.perf_counter() - settle) * 1000,
        "pass": process.returncode == 0
        and result is not None
        and visible_render_evidence(first, result)
        and result.get("status") == "PASS"
        and not surviving
        and not timed_out,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-gui", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--burst", type=int, default=2000)
    args = parser.parse_args(argv)
    if not args.allow_gui:
        print(
            json.dumps(
                {
                    "status": "NOT RUN",
                    "reason": "Explicit --allow-gui required",
                    "pyside_available_in_parent": importlib.util.find_spec("PySide6") is not None,
                }
            )
        )
        return 2
    if not args.output or not args.output.is_absolute() or not 1 <= args.samples <= 5:
        parser.error("new absolute --output directory and 1–5 samples required")
    if not 64 <= args.rows <= 2000 or not 1 <= args.burst <= 3000:
        parser.error("bounded proof inputs required")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "runtime_parent": runtime(),
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_files": source_identity(),
        "dataset": {"rows_per_table": args.rows, "tables": 2, "burst": args.burst},
        "runs": [],
    }

    def execute(toolkit, label, arguments):
        record = child(args.python, f"tools.qualification.gui_port_740.{toolkit}_child", arguments)
        report["runs"].append({"toolkit": toolkit, "label": label, **record})
        (args.output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        print(
            json.dumps(
                {
                    "toolkit": toolkit,
                    "label": label,
                    "pass": record["pass"],
                    "startup_ms": record["startup_ms"],
                    "stderr": record["stderr"],
                }
            ),
            flush=True,
        )
        return record["pass"]

    base = ["--rows", str(args.rows), "--burst", str(args.burst)]
    if not execute(
        "qt",
        "contracts",
        [*base, "--mode", "contracts", "--screenshot", str(args.output / "qt-proof.png")],
    ):
        return 1
    for close in ("repeat", "quit", "delete"):
        if not execute(
            "qt", "close-" + close, [*base, "--close-mode", close, "--mode", "benchmark"]
        ):
            return 1
    for toolkit in ("tk", "qt"):
        for sample in range(args.samples + 1):
            label = "warmup" if sample == 0 else f"sample-{sample}"
            arguments = [*base, "--mode", "benchmark"] if toolkit == "qt" else base
            if not execute(toolkit, label, arguments):
                return 1
    report["summary"] = {}
    for toolkit in ("tk", "qt"):
        samples = [
            r
            for r in report["runs"]
            if r["toolkit"] == toolkit and r["label"].startswith("sample-")
        ]
        report["summary"][toolkit] = {
            key: summary([r[key] for r in samples])
            for key in ("startup_ms", "close_to_exit_ms", "peak_sampled_working_set")
        }
        for key in ("populate_ms", "warm_shell_first_paint_ms"):
            report["summary"][toolkit][key] = summary([r["result"][key] for r in samples])
    report["status"] = "PASS"
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
