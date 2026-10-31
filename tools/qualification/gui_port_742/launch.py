"""Owned, bounded launch of one proof child (adapted from the accepted GUI-PORT-740 launcher).

Same containment primitives (anonymous job object, suspended launch) and the same identity-bound descendant
quiescence check. Additions: a per-child environment, and an ``on_event`` hook so the parent can act on a structured
stdout event while the child is still running (used for the read-only UI Automation inspection of the child's own
window). Nothing is discovered or adopted by name, port or PID; the parent only ever touches the process it launched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from typing import Any

from tools.qualification.gui_port_740.common import ROOT

CHILD_TIMEOUT_S = 60


def child_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("QT_"):
            environment.pop(key)  # a host's Qt overrides must never leak into a measurement
    environment.update(
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        STABLENEW_TEST_MODE="1",
        STABLENEW_NO_WEBUI="1",
    )
    environment.update(extra or {})
    return environment


def run_child(
    python: str,
    module: str,
    arguments: list[str],
    *,
    env_extra: dict[str, str] | None = None,
    timeout: float = CHILD_TIMEOUT_S,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    import psutil

    from src.utils.managed_process import launch_contained
    from src.utils.process_container_v2 import ProcessContainerConfig, build_process_container

    environment = child_environment(env_extra)
    stdout_file = tempfile.TemporaryFile(mode="w+t", encoding="utf8")
    stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf8")
    container = build_process_container("gui-port-742-child", ProcessContainerConfig())
    started = time.perf_counter_ns()
    launched = launch_contained(
        [python, "-m", module, *arguments],
        label="GUI-PORT-742",
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
    descendants: set[tuple[int, float]] = set()
    timed_out = False
    seen = 0
    try:
        while process.poll() is None:
            if (time.perf_counter_ns() - started) / 1e9 > timeout:
                timed_out = True
                container.kill_all()  # only this launch's anonymous owned container
                break
            try:
                probe = psutil.Process(process.pid)
                total = probe.memory_info().rss
                for owned in probe.children(recursive=True):
                    try:
                        descendants.add((owned.pid, owned.create_time()))
                        total += owned.memory_info().rss
                    except psutil.Error:
                        pass
                peak = max(peak, total)
            except psutil.Error:
                pass
            if on_event is not None:
                stdout_file.seek(0)
                lines = stdout_file.read().splitlines()
                for line in lines[seen:]:
                    try:
                        on_event(json.loads(line))
                    except ValueError:
                        pass
                seen = len(lines)
            time.sleep(0.01)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            container.kill_all()
            process.wait(timeout=5)
        container.teardown()
    exited = time.perf_counter_ns()
    stdout_file.seek(0)
    stderr_file.seek(0)
    stdout, stderr = stdout_file.read(), stderr_file.read()
    stdout_file.close()
    stderr_file.close()
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            events.append({"unparsed_stdout": line[:300]})
    result = next((e for e in events if e.get("event") == "result"), None)
    first = next((e for e in events if e.get("event") == "first_visible"), None)
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
        "stderr": stderr[-2000:],
        "timeout": timed_out,
        "contained": launched.contained,
        "events": [
            e
            for e in events
            if e.get("event") in {"first_visible", "inspect_ready"} or "unparsed_stdout" in e
        ],
        "first_visible": first,
        "result": result,
        "peak_sampled_working_set": peak,
        "startup_ms": (first["clock_ns"] - started) / 1e6 if first else None,
        "close_to_exit_ms": (exited - result["close_started_ns"]) / 1e6
        if result and result.get("close_started_ns")
        else None,
        "surviving_descendants": surviving,
        "observed_descendants": len(descendants),
        "descendant_quiescence_ms": (time.perf_counter() - settle) * 1000,
    }
