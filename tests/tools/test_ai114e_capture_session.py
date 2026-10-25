"""PR-AI-QUAL-114E: admission to the operator's capture and the standard-user session monitor.

The capture is simulated by ``FakeLogman``; the child processes are REAL (the owned job object, through the bounded runner) and
synthetic. Nothing downloaded runs, nothing is elevated and no trace session is started. These tests prove that no child is
launched while the capture cannot be relied on, that every request leaves a window record the analyzer can use, and that the
harness never controls a trace session.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.tools.ai114e_support import (  # noqa: E402
    FIXED_NOW,
    FakeLogman,
    make_env,
    started_capture,
    stopped_capture,
)
from tools.qualification.ai111 import capture_analysis as analysis  # noqa: E402
from tools.qualification.ai111 import capture_control as control  # noqa: E402
from tools.qualification.ai111 import capture_session as session  # noqa: E402
from tools.qualification.ai111.ownership import OwnershipPolicy  # noqa: E402

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")
PY = getattr(sys, "_base_executable", sys.executable)


def make_proof(tmp_path: Path, **override) -> Path:
    proof = {
        "kind": "canary_capture",
        "verdict": "PASS",
        "analyzer_version": analysis.ANALYZER_VERSION,
        "provider_config_sha256": control.provider_config_sha256(),
        "tool_sha256": control.tool_sha256(),
        "host": platform.node(),
        "capture_id": "20250101T000000Z-aaaaaaaa",
        "finished_utc": (FIXED_NOW - timedelta(hours=1)).isoformat(),
        **override,
    }
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    return path


def admission_for(target: Path, env: control.Environment, tmp_path: Path, **kwargs):
    if "proof_path" not in kwargs:
        kwargs["proof_path"] = make_proof(tmp_path)
    return session.CaptureAdmission(
        capture_dir=target,
        run_id="run-1",
        tools=env.tools,
        now=env.now,
        reports_root=env.reports_root,
        **kwargs,
    )


def monitor_for(admission, **kwargs) -> session.RetrospectiveMonitor:
    kwargs.setdefault("self_elevated", lambda: False)
    kwargs.setdefault("token_probe", lambda pid: False)
    return session.RetrospectiveMonitor(OwnershipPolicy(), admission, **kwargs)


def lines(target: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (target / "windows.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# -- admission: the static facts ----------------------------------------------------------------------------------------


def test_a_sound_capture_with_a_current_canary_proof_is_admitted(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    assert admission_for(target, env, tmp_path).problems() == []


def test_the_capture_must_belong_to_this_run(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    admission = admission_for(target, env, tmp_path)
    admission.run_id = "another-run"
    assert any("belongs to run" in p for p in admission.static_problems())


@pytest.mark.parametrize(
    ("field", "fragment"),
    [
        ("provider_config_sha256", "provider configuration differs"),
        ("tool_sha256", "different capture_control.py"),
    ],
)
def test_a_capture_made_by_other_code_or_configuration_is_refused(
    tmp_path: Path, field: str, fragment: str
) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    manifest = json.loads((target / "capture.json").read_text(encoding="utf-8"))
    manifest[field] = "0" * 64
    (target / "capture.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any(fragment in p for p in admission_for(target, env, tmp_path).static_problems())


def test_a_missing_manifest_or_a_directory_outside_reports_is_refused(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    (target / "capture.json").unlink()
    assert admission_for(target, env, tmp_path).static_problems() == [
        "capture.json is missing or unreadable"
    ]
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert any(
        "must be inside" in p for p in admission_for(outside, env, tmp_path).static_problems()
    )


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"kind": "qualification_capture"}, "not an analyzed canary capture"),
        ({"verdict": "INCONCLUSIVE"}, "not PASS"),
        ({"verdict": "FAIL"}, "not PASS"),
        ({"analyzer_version": "0"}, "different analyzer version"),
        ({"provider_config_sha256": "0" * 64}, "different provider configuration"),
        ({"tool_sha256": "0" * 64}, "different capture_control.py"),
        ({"host": "SOMEONE-ELSES-PC"}, "another host"),
        ({"finished_utc": "garbage"}, "no valid finish time"),
    ],
)
def test_a_canary_proof_that_does_not_fit_is_refused(
    tmp_path: Path, override: dict, fragment: str
) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    admission = admission_for(target, env, tmp_path, proof_path=make_proof(tmp_path, **override))
    assert any(fragment in p for p in admission.static_problems()), admission.static_problems()


def test_a_stale_or_future_canary_proof_is_refused(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    old = make_proof(tmp_path, finished_utc=(FIXED_NOW - timedelta(hours=30)).isoformat())
    assert any(
        "old" in p for p in admission_for(target, env, tmp_path, proof_path=old).static_problems()
    )
    future = make_proof(tmp_path, finished_utc=(FIXED_NOW + timedelta(hours=1)).isoformat())
    assert any(
        "old" in p
        for p in admission_for(target, env, tmp_path, proof_path=future).static_problems()
    )


def test_the_proof_cannot_be_the_capture_it_authorizes(tmp_path: Path) -> None:
    target, report, env = started_capture(tmp_path, FakeLogman())
    own = make_proof(tmp_path, capture_id=report["capture_id"])
    assert any(
        "this capture's own" in p
        for p in admission_for(target, env, tmp_path, proof_path=own).static_problems()
    )


def test_no_or_unreadable_proof_is_refused(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    admission = admission_for(target, env, tmp_path, proof_path=None)
    assert any("no canary proof" in p for p in admission.static_problems())
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert any(
        "unreadable" in p
        for p in admission_for(target, env, tmp_path, proof_path=bad).static_problems()
    )


def test_the_canary_capture_itself_needs_no_proof(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    admission = admission_for(target, env, tmp_path, proof_path=None, require_proof=False)
    assert admission.problems() == []


# -- admission: what the OS says right now ------------------------------------------------------------------------------


def test_a_capture_that_is_not_active_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    control.stop_capture(report["capture_id"], evidence_dir=target, env=env)
    problems = admission_for(target, env, tmp_path).live_problems()
    assert any("STOPPED, not ACTIVE" in p for p in problems)


def test_an_expired_capture_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman, minutes=10)
    late = make_env(tmp_path, logman, now=lambda: FIXED_NOW + timedelta(minutes=11))
    admission = admission_for(target, late, tmp_path)
    assert any("EXPIRED" in p for p in admission.live_problems())


def test_a_session_that_stopped_unexpectedly_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    del logman.sessions[control.session_names(report["capture_id"])["file"]]
    assert any(
        "CLEANUP_REQUIRED" in p for p in admission_for(target, env, tmp_path).live_problems()
    )


def test_a_session_changed_after_start_is_refused(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    logman.sessions[control.session_names(report["capture_id"])["network"]]["circular"] = "On"
    assert any("circular" in p for p in admission_for(target, env, tmp_path).live_problems())


def test_buffers_already_lost_refuse_admission(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    logman.buffers_lost = 4
    assert any("lost buffers" in p for p in admission_for(target, env, tmp_path).live_problems())


def test_a_trace_file_near_its_cap_refuses_admission(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman, max_mb=16)
    with (target / "file.etl").open("wb") as handle:
        handle.truncate(int(16 * 1024 * 1024 * 0.95))
    assert any(
        "near its 16 MB cap" in p for p in admission_for(target, env, tmp_path).live_problems()
    )


def test_an_unreadable_session_list_is_never_admission(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    logman.list_fails = True
    assert any(
        "could not be read" in p for p in admission_for(target, env, tmp_path).live_problems()
    )


def test_live_checks_are_cached_briefly_and_then_repeated(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    clock = [100.0]
    admission = admission_for(target, env, tmp_path, monotonic=lambda: clock[0])
    assert admission.live_problems() == []
    queries = len(logman.calls)
    assert admission.live_problems() == [] and len(logman.calls) == queries, (
        "within the TTL: no new query"
    )
    clock[0] += 5
    logman.list_fails = True
    assert admission.live_problems(), "after the TTL the OS is asked again"


# -- the monitor: nothing runs unless the capture is sound -----------------------------------------------------------------


@windows_only
def test_no_child_is_launched_when_the_capture_is_not_active(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    control.stop_capture(report["capture_id"], evidence_dir=target, env=env)
    marker = tmp_path / "must-not-exist.txt"
    monitor = monitor_for(admission_for(target, env, tmp_path))
    outcome = monitor.runner()(
        [PY, "-I", "-c", f"open({str(marker)!r}, 'w').write('ran')"],
        timeout_seconds=20.0,
        max_stdout_bytes=1024,
    )
    assert outcome.launch_error and outcome.returncode is None
    assert not marker.exists(), "the child never started"
    assert {"provider_failed:connections", "provider_failed:files"} <= set(
        monitor.records[-1].violations
    )
    assert not (target / "windows.jsonl").exists(), (
        "a refused request writes no window and no beacon"
    )
    assert any("not ACTIVE" in p for p in monitor.readiness())


@windows_only
def test_an_elevated_harness_is_refused_before_anything_runs(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    monitor = monitor_for(admission_for(target, env, tmp_path), self_elevated=lambda: True)
    assert any(p.startswith("privilege:") for p in monitor.provider_problems())
    unreadable = monitor_for(admission_for(target, env, tmp_path), self_elevated=lambda: None)
    assert any(p.startswith("privilege:") for p in unreadable.provider_problems())


@windows_only
def test_readiness_without_the_canary_is_not_ready(tmp_path: Path) -> None:
    target, _report, env = started_capture(tmp_path, FakeLogman())
    monitor = monitor_for(admission_for(target, env, tmp_path))
    assert "monitor canary has not been run" in monitor.readiness()


# -- the monitor: the real canary and the window log ----------------------------------------------------------------------


@windows_only
def test_the_canary_child_is_standard_user_and_leaves_a_complete_window_record(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    monitor = session.RetrospectiveMonitor(
        OwnershipPolicy(), admission_for(target, env, tmp_path), forbid_elevation=True
    )  # real token checks: the child itself reports its own elevation
    result = monitor.run_canary()
    assert monitor.readiness() == [], monitor.readiness()
    assert (
        result["passed"]
        and result["saw"]["standard_user"] is True
        and result["saw"]["descendant"] is True
    )
    monitor.close_and_report(target)
    assert monitor.end_canary_report and monitor.end_canary_report["passed"]
    kinds = [entry["type"] for entry in lines(target)]
    assert kinds == [
        "header",
        "beacon",
        "request",
        "canary_report",
        "request",
        "canary_report",
        "beacon",
        "end",
    ]
    entries = lines(target)
    assert entries[0]["capture_id"] == report["capture_id"] and entries[0]["run_id"] == "run-1"
    assert entries[0]["harness_pid"] == os.getpid()
    assert [e["tag"] for e in entries if e["type"] == "beacon"] == ["start", "end"]
    for request in (e for e in entries if e["type"] == "request"):
        assert request["canary"] is True and request["process_complete"] is True
        assert request["active_after_teardown"] == 0 and request["token_elevated"] is not True
        assert len(request["members"]) >= 2, "the canary child and its short-lived descendant"
        assert request["start_ns"] < request["end_ns"]
        assert request["canary_expect"]["port"] and request["canary_expect"]["marker"]
    for reported in (e for e in entries if e["type"] == "canary_report"):
        assert reported["reported_elevated"] == 0 and reported["returncode"] == 0
    first_beacon = next(e for e in entries if e["type"] == "beacon")
    assert first_beacon["before_ns"] <= first_beacon["after_ns"] <= entries[2]["start_ns"]
    assert not list((target / "beacons").glob("*")), "a beacon file exists only for an instant"


@windows_only
def test_a_qualification_request_is_logged_with_its_owned_processes_and_policy(
    tmp_path: Path,
) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    monitor = monitor_for(admission_for(target, env, tmp_path))
    monitor.run_canary()
    outcome = monitor.runner()(
        [PY, "-I", "-c", "print('ok')"], timeout_seconds=20.0, max_stdout_bytes=1024
    )
    monitor.close_and_report(target)
    assert outcome.returncode == 0
    request = next(e for e in lines(target) if e["type"] == "request" and not e["canary"])
    assert request["number"] == 2 and request["root_pid"] in {m["pid"] for m in request["members"]}
    assert request["process_complete"] is True and request["active_after_teardown"] == 0
    assert (
        request["policy"]["allow_connections"] is False
        and request["policy"]["max_descendants"] == 0
    )
    assert request["canary_expect"] is None


@windows_only
def test_a_child_with_an_elevated_token_is_stopped_and_logged(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    monitor = monitor_for(admission_for(target, env, tmp_path), token_probe=lambda pid: True)
    outcome = monitor.runner()(
        [PY, "-I", "-c", "import time; time.sleep(30)"], timeout_seconds=30.0, max_stdout_bytes=1024
    )
    assert outcome.cancelled, "an elevated child is stopped through the runner's cancel path"
    assert "child_token_elevated" in monitor.records[-1].violations
    request = next(e for e in lines(target) if e["type"] == "request")
    assert (
        request["token_elevated"] is True
        and "child_token_elevated" in request["realtime_violations"]
    )


@windows_only
def test_the_harness_never_starts_stops_or_sweeps_a_trace_session(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    before = len(logman.calls)
    monitor = monitor_for(admission_for(target, env, tmp_path))
    monitor.run_canary()
    monitor.close_and_report(target)
    verbs = {c[1] for c in logman.calls[before:]}
    assert verbs <= {"query"}, f"the standard-user half used {verbs}"
    assert len(logman.sessions) == 3, "the operator's sessions are untouched"
    assert monitor.leaked_traces() == []
    assert session.CaptureWindowProvider("files", monitor.admission).leaked() == []


@windows_only
def test_the_monitor_is_retrospective_and_never_claims_zero_connections(tmp_path: Path) -> None:
    target, report, env = started_capture(tmp_path, FakeLogman())
    monitor = monitor_for(admission_for(target, env, tmp_path))
    monitor.run_canary()
    summary = monitor.summary()
    assert monitor.kind == "host_retrospective" and summary["mode"] == "retrospective_capture"
    assert monitor.connection_attempts() is None and summary["connection_attempts"] is None
    assert (
        summary["capture_analysis_required"] is True
        and summary["capture_id"] == report["capture_id"]
    )
    assert "pending" in summary["file_and_egress_findings"]


@windows_only
def test_a_closing_canary_that_cannot_run_is_not_a_pass(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, report, env = started_capture(tmp_path, logman)
    clock = [100.0]
    monitor = monitor_for(admission_for(target, env, tmp_path, monotonic=lambda: clock[0]))
    monitor.run_canary()
    control.stop_capture(
        report["capture_id"], evidence_dir=target, env=env
    )  # the operator stopped it too early
    clock[0] += 10  # past the admission cache
    monitor.close_and_report(target)
    assert monitor.end_canary_report is not None and monitor.end_canary_report["passed"] is False
    requests = [e for e in lines(target) if e["type"] == "request"]
    assert len(requests) == 1, (
        "the refused closing canary produced no window: the analysis will see one canary, not two"
    )


@windows_only
def test_a_first_request_cannot_run_before_the_opening_beacon(tmp_path: Path) -> None:
    logman = FakeLogman()
    target, _report, env = started_capture(tmp_path, logman)
    monitor = monitor_for(admission_for(target, env, tmp_path))
    monitor.runner()([PY, "-I", "-c", "pass"], timeout_seconds=20.0, max_stdout_bytes=1024)
    kinds = [e["type"] for e in lines(target)]
    assert kinds[:2] == ["header", "beacon"], (
        "the header and opening beacon precede the first logged request"
    )
    assert kinds.index("beacon") < kinds.index("request")


def test_the_window_log_is_append_only_and_synced(tmp_path: Path) -> None:
    log = session.WindowLog(tmp_path / "windows.jsonl")
    log.write({"type": "a"})
    log.write({"type": "b"})
    assert [
        json.loads(line)["type"] for line in (tmp_path / "windows.jsonl").read_text().splitlines()
    ] == ["a", "b"]
    with pytest.raises(ValueError):
        log.write({"type": "nan", "x": float("nan")})


def test_the_session_command_line_refuses_to_run_elevated(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session.tokens, "current_process_elevated", lambda: True)
    code = session.main(["canary", "--capture-dir", str(tmp_path), "--run-id", "r"])
    out = capsys.readouterr().out
    assert code == 2 and "nothing_started" in out


def test_the_session_command_line_refuses_without_an_active_capture(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session.tokens, "current_process_elevated", lambda: False)
    code = session.main(["canary", "--capture-dir", str(tmp_path), "--run-id", "r"])
    assert code == 2 and "nothing_started" in capsys.readouterr().out


def test_stopped_capture_helper_is_stopped(tmp_path: Path) -> None:
    target, _report, env = stopped_capture(tmp_path, FakeLogman())
    assert control.capture_status(target, env=env)["state"] == "STOPPED"
