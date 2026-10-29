"""Read-only binding of stopped capture evidence to qualification request records."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.qualification.ai111 import capture_control as control
from tools.qualification.ai111.capture_analysis import (
    ANALYZER_VERSION,
    analyzer_sha256,
    read_window_log,
)
from tools.qualification.ai111.execution_evidence import (
    RETROSPECTIVE_HOST,
    childless_record_problems,
    prelaunch_only,
)
from tools.qualification.ai111.plan import digest


def read_json(path: Path) -> Any:
    if path.is_symlink() or path.is_junction():
        raise ValueError(f"redirected evidence: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise ValueError("redirected records")
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def capture_problems(
    directory: Path,
    analysis: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    capture_id: str,
) -> list[str]:
    """No live queries, conversion, session start/stop, or mutation. Missing facts never mean zero."""
    problems = []
    if analysis is None:
        return ["capture analysis missing"]
    expected = {
        "capture_id": capture_id,
        "run_id": run_id,
        "kind": "canary_capture" if prelaunch_only(rows) else "qualification_capture",
        "verdict": "PASS",
        "analyzer_version": ANALYZER_VERSION,
        "analyzer_sha256": analyzer_sha256(),
        "tool_sha256": control.tool_sha256(),
        "provider_config_sha256": control.provider_config_sha256(),
        "capture_problems": [],
    }
    for key, value in expected.items():
        if analysis.get(key) != value:
            problems.append(f"capture {key} missing/mismatched")
    if analysis.get("state") not in ("STOPPED", "VERIFIED"):
        problems.append("capture not terminal")
    try:
        manifest = read_json(directory / "capture.json")
        active = read_json(directory / "state-02-active.json")
        stopped = read_json(directory / "state-04-stopped.json")
        verification = read_json(directory / "verification.json")
        if manifest.get("capture_id") != capture_id or manifest.get("run_id") != run_id:
            problems.append("capture manifest identity mismatch")
        if (
            active.get("state") != "ACTIVE"
            or stopped.get("state") != "STOPPED"
            or stopped.get("sessions_left") != []
        ):
            problems.append("ACTIVE/STOPPED or zero surviving sessions not proved")
        if verification.get("state") != "VERIFIED" or verification.get("verdict") != "PASS":
            problems.append("capture verification not PASS")
        if analysis.get("stop_record") != stopped:
            problems.append("analysis and operator stop contradict")
        if datetime.fromisoformat(stopped["stopped_utc"]) > datetime.fromisoformat(
            manifest["deadline_utc"]
        ):
            problems.append("capture expired")
        saved = [read_json(p) for p in directory.glob("analysis*.json")]
        if not saved or not any(
            digest(s) == digest({k: v for k, v in analysis.items() if k != "analysis_file"})
            for s in saved
        ):
            problems.append("analysis not preserved in capture directory")
        if any(s.get("verdict") != "PASS" for s in saved):
            problems.append("contradictory or incomplete capture analyses")
    except (OSError, KeyError, TypeError, ValueError):
        problems.append("capture lifecycle evidence missing/malformed")
    traces = analysis.get("traces", {})
    if set(traces) != {s.kind for s in control.SESSIONS} or any(
        t.get("header_ok") is not True for t in traces.values()
    ):
        problems.append("trace completeness not proved")
    requests = analysis.get("requests", [])
    real = {r.get("number"): r for r in requests if r.get("canary") is False}
    if len(real) != sum(r.get("canary") is False for r in requests):
        problems.append("duplicate capture request number")
    expected_numbers = []
    log = read_window_log(directory / "windows.jsonl")
    header = log.header or {}
    problems += log.problems
    if not log.ended or log.end_failed:
        problems.append("capture closing evidence incomplete")
    if any(
        header.get(k) != value
        for k, value in {
            "capture_id": capture_id,
            "run_id": run_id,
            "monitor_implementation": RETROSPECTIVE_HOST,
            "host": analysis.get("host"),
            "tool_sha256": control.tool_sha256(),
            "provider_config_sha256": control.provider_config_sha256(),
        }.items()
    ) or not analysis.get("host"):
        problems.append("retrospective monitor provenance/identity not proved")
    raw = {r.get("number"): r for r in log.requests if r.get("canary") is False}
    if set(raw) != set(real):
        problems.append("analyzer and raw owned windows differ")
    for row in rows:
        elapsed = row.get("elapsed_ms")
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            problems.append("request elapsed measurement missing/invalid")
        numbers = row.get("monitor_request_numbers")
        if row.get("execution_state") == "not_launched":
            problems += childless_record_problems(row)
            if (
                row.get("monitor_kind") != RETROSPECTIVE_HOST
                or row.get("synthetic") is True
                or row.get("capture_id") != capture_id
                or row.get("run_id") != run_id
            ):
                problems.append("childless request capture provenance not proved")
            continue
        if not isinstance(numbers, list) or len(numbers) != 1:
            problems.append("record has no unique observed execution window")
            continue
        expected_numbers.extend(numbers)
        observed = real.get(numbers[0], {})
        window = raw.get(numbers[0], {})
        if not owned_window_verified(window, observed, row):
            problems.append("raw process ownership or monitored interval incomplete")
        if (
            observed.get("executable_sha256") != row.get("runtime_member_sha256")
            or observed.get("executable") != row.get("executable")
            or observed.get("owned_connection_events") != 0
            or observed.get("ambiguous_events") != 0
            or observed.get("violations") != []
            or observed.get("files_outside_policy", []) != []
            or row.get("process_complete") is not True
            or row.get("active_after_teardown") != 0
            or row.get("capture_id") != capture_id
            or row.get("run_id") != run_id
            or row.get("monitor_kind") != RETROSPECTIVE_HOST
            or row.get("synthetic") is True
        ):
            problems.append("request attribution, zero egress/files or teardown not proved")
    if len(expected_numbers) != len(set(expected_numbers)):
        problems.append("execution window reused")
    if set(expected_numbers) != set(real):
        problems.append("capture has missing or unexplained execution windows")
    # Lifecycle probes are additional real windows, deliberately separate from scored requests.
    if any(
        r.get("owned_connection_events") != 0
        or r.get("violations") != []
        or r.get("ambiguous_events") != 0
        for r in real.values()
    ):
        problems.append("capture contains a violating or ambiguous real request")
    canaries = [r for r in requests if r.get("canary") is True]
    if len(canaries) < 2 or any(r.get("canary_problems") != [] for r in canaries):
        problems.append("bracketing canaries not proved")
    elif real and not (
        min(r["number"] for r in canaries)
        < min(real)
        <= max(real)
        < max(r["number"] for r in canaries)
    ):
        problems.append("canaries do not bracket the capture")
    return sorted(set(problems))


def owned_window_verified(
    window: Mapping[str, Any], analyzed: Mapping[str, Any], row: Mapping[str, Any]
) -> bool:
    """Check the owned-job window independently of the supplied row's labels."""
    members = window.get("members", [])
    start, end, root = window.get("start_ns"), window.get("end_ns"), window.get("root_pid")
    if (
        type(start) is not int
        or type(end) is not int
        or start <= 0
        or end < start
        or type(root) is not int
        or root <= 0
        or not members
    ):
        return False
    for member in members:
        a, b, pid = member.get("start_ns"), member.get("end_ns"), member.get("pid")
        if (
            type(a) is not int
            or type(b) is not int
            or type(pid) is not int
            or not start <= a <= b <= end
            or pid <= 0
        ):
            return False
    return (
        root in {m["pid"] for m in members}
        and len({m["pid"] for m in members}) == len(members)
        and window.get("process_complete") is True
        and window.get("active_after_teardown") == 0
        and window.get("token_elevated") is False
        and window.get("realtime_violations") == []
        and window.get("provider_errors") == {}
        and analyzed.get("members") == len(members)
        and window.get("executable_sha256") == row.get("runtime_member_sha256")
        and Path(str(window.get("executable", ""))).name == row.get("executable")
    )
