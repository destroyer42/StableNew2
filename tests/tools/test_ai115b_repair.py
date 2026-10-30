"""AI-QUAL-115B-R regressions. All runners, services and capture queries are inert."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai_assist.argv import RunLimits, Sampling
from src.ai_assist.contracts import OutcomeCode
from tools.qualification.ai111 import capture_control, capture_session, d12a, physical, readiness
from tools.qualification.ai111.capture_analysis import ANALYZER_VERSION, analyzer_sha256
from tools.qualification.ai111.capture_evidence import capture_problems
from tools.qualification.ai111.capture_session import CaptureAdmission, RetrospectiveMonitor
from tools.qualification.ai111.execution_contract import select_contract
from tools.qualification.ai111.execution_evidence import (
    childless_record_problems,
    monitor_problems,
    record_execution,
    verified_contract_rows,
)
from tools.qualification.ai111.lfm3_contract import record_problems
from tools.qualification.ai111.ownership import OwnershipPolicy

SPEC = select_contract("lfm3-v1")
ARM = SPEC.document["arms"][1]["arm_id"]
MEMBER = "llama-completion.exe"


def monitor_for(tmp_path, monkeypatch):
    admission = CaptureAdmission(tmp_path / "capture", "repair-test")
    monkeypatch.setattr(admission, "problems", lambda: [])
    admission.manifest = {"capture_id": "20261029T210000Z-1234abcd"}
    monitor = RetrospectiveMonitor(OwnershipPolicy(), admission, self_elevated=lambda: False)
    monkeypatch.setattr(monitor, "run_canary", lambda: None)
    monkeypatch.setattr(monitor, "readiness", lambda: [])
    return monitor


@pytest.fixture
def windows_capture_host(monkeypatch):
    # Simulate only this module's host platform; the real shared os module stays intact.
    monkeypatch.setattr(
        capture_session, "os", SimpleNamespace(**{**vars(capture_session.os), "name": "nt"})
    )


def test_authentic_retrospective_monitor_reaches_d12a_preflight(
    tmp_path, monkeypatch, windows_capture_host
):
    monitor = monitor_for(tmp_path, monkeypatch)
    monkeypatch.setattr(readiness, "readiness_problems", lambda *a, **k: [])

    class InertArchive:
        def read_bytes(self):
            raise RuntimeError("identity admission passed; no archive accessed")

    with pytest.raises(RuntimeError, match="identity admission passed"):
        d12a.run_d12a(
            archive=InertArchive(),
            passive_manifest=None,
            evidence_root=tmp_path,
            monitor=monitor,
            authorization_text="test",
            attestation="test",
            contract_spec=SPEC,
            executable=MEMBER,
        )


def session_world(tmp_path, monkeypatch):
    monitor = monitor_for(tmp_path, monkeypatch)
    monkeypatch.setattr(readiness, "readiness_problems", lambda *a, **k: [])
    monkeypatch.setattr(monitor, "provider_problems", lambda: [])
    monkeypatch.setattr(physical, "preflight", lambda *a, **k: [])
    monkeypatch.setattr(physical, "resource_check", lambda *a: ({}, []))
    monkeypatch.setattr(physical, "_deep_problems", lambda *a: [])
    monkeypatch.setattr(physical, "_arm_preconditions", lambda *a: [])
    monkeypatch.setattr(physical, "import_runtime", lambda *a: None)
    monkeypatch.setattr(physical, "import_model", lambda *a: None)
    monkeypatch.setattr(physical, "record_active", lambda *a: None)
    build = SimpleNamespace(
        build_id="inert",
        executable=MEMBER,
        asset_sha256=SPEC.runtime["sha256"],
        files=SPEC.runtime["files"],
    )
    monkeypatch.setattr(physical, "derive_runtime_build", lambda *a, **k: build)
    monkeypatch.setattr(
        physical,
        "_Sampler",
        lambda *a, **k: SimpleNamespace(start=lambda: None, close=lambda: None, abort_reason=""),
    )
    calls = []
    cases = list(SPEC.cases("A"))

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, request):
            case = cases[len(calls)]
            calls.append(case.case_id)
            if case.expected_outcome == "invalid_request":
                return SimpleNamespace(
                    code=OutcomeCode.INVALID_REQUEST,
                    reason="reserved_marker_in_text",
                    suggestion=None,
                    elapsed_ms=0,
                    details={},
                )
            monitor.records.append(
                SimpleNamespace(
                    number=len(monitor.records) + 1,
                    process={"complete": True, "active_after_teardown": 0},
                    violations=[],
                    connections=[],
                    files=[],
                    canary=False,
                )
            )
            return SimpleNamespace(
                code=OutcomeCode.SUGGESTION, reason="", suggestion=None, elapsed_ms=1, details={}
            )

    monkeypatch.setattr(physical, "AiAssistService", Service)
    return monitor, cases, calls


def test_expected_childless_cases_keep_all_frozen_cases_and_continue(tmp_path, monkeypatch):
    monitor, cases, calls = session_world(tmp_path, monkeypatch)
    result = physical._run_session(
        plan=SPEC.execution_plan(),
        paths=physical.SessionPaths(
            tmp_path,
            tmp_path / "absent.zip",
            {SPEC.arm(ARM).model.model_id: tmp_path / "absent.gguf"},
        ),
        stage="A",
        arms=[ARM],
        cases=cases,
        authorization_text="test",
        contract_spec=SPEC,
        monitor=monitor,
        executable=MEMBER,
        strict_offline=True,
        gpu_probe=lambda: [],
        busy_provider=lambda: [],
    )
    assert result["abort_reason"] == ""
    assert calls == [c.case_id for c in cases]
    rows = [
        json.loads(line)
        for line in (tmp_path / "physical-A/records.jsonl").read_text().splitlines()
    ]
    assert [r["case_id"] for r in rows] == calls
    assert sum(r["outcome"] == "invalid_request" for r in rows) == 3


def test_uncertain_timeout_teardown_stops_before_cancellation_probe(tmp_path, monkeypatch):
    monitor = SimpleNamespace(records=[], kind="inert", runner=lambda: None)
    calls = []

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, *args):
            calls.append("run")
            monitor.records.append(
                SimpleNamespace(
                    number=len(calls),
                    process={"complete": False, "active_after_teardown": 1},
                    violations=["teardown_not_verified"],
                )
            )
            return SimpleNamespace(
                code=OutcomeCode.TIMEOUT, reason="wall_clock_limit", elapsed_ms=1
            )

    monkeypatch.setattr(physical, "AiAssistService", Service)
    monkeypatch.setattr(
        physical.threading,
        "Timer",
        lambda *a: SimpleNamespace(start=lambda: None, cancel=lambda: None),
    )
    rows = physical._lifecycle_probes(
        SPEC.cases("A")[3],
        ARM,
        tmp_path,
        SimpleNamespace(),
        SPEC.arm(ARM).model,
        monitor,
        lambda: None,
        Sampling(),
        RunLimits(),
        None,
        True,
    )
    assert len(calls) == 1
    assert len(rows) == 1 and rows[0]["teardown_verified"] is False


def capture_fixture(tmp_path):
    directory = tmp_path / "capture"
    directory.mkdir()
    identity = {"capture_id": "20261029T210000Z-1234abcd", "run_id": "repair-test"}
    stop = {"state": "STOPPED", "sessions_left": [], "stopped_utc": "2026-10-29T21:01:00Z"}
    header = {
        "type": "header",
        **identity,
        "monitor_implementation": "host_retrospective",
        "host": platform.node(),
        "tool_sha256": capture_control.tool_sha256(),
        "provider_config_sha256": capture_control.provider_config_sha256(),
    }
    real = {
        "type": "request",
        "number": 2,
        "canary": False,
        "start_ns": 100,
        "end_ns": 200,
        "root_pid": 42,
        "members": [{"pid": 42, "start_ns": 110, "end_ns": 190}],
        "process_complete": True,
        "active_after_teardown": 0,
        "token_elevated": False,
        "provider_errors": {},
        "realtime_violations": [],
        "executable": MEMBER,
        "executable_sha256": SPEC.members[MEMBER],
    }
    analysis = {
        **identity,
        "host": platform.node(),
        "kind": "qualification_capture",
        "verdict": "PASS",
        "analyzer_version": ANALYZER_VERSION,
        "analyzer_sha256": analyzer_sha256(),
        "tool_sha256": capture_control.tool_sha256(),
        "provider_config_sha256": capture_control.provider_config_sha256(),
        "capture_problems": [],
        "state": "STOPPED",
        "stop_record": stop,
        "traces": {kind: {"header_ok": True} for kind in ("file", "network", "dns")},
        "requests": [
            {"number": 1, "canary": True, "canary_problems": []},
            {
                "number": 2,
                "canary": False,
                "members": 1,
                "executable": MEMBER,
                "executable_sha256": SPEC.members[MEMBER],
                "owned_connection_events": 0,
                "ambiguous_events": 0,
                "violations": [],
            },
            {"number": 3, "canary": True, "canary_problems": []},
        ],
    }
    for name, data in {
        "capture.json": {**identity, "deadline_utc": "2026-10-29T21:02:00Z"},
        "state-02-active.json": {"state": "ACTIVE"},
        "state-04-stopped.json": stop,
        "verification.json": {"state": "VERIFIED", "verdict": "PASS"},
        "analysis.json": analysis,
    }.items():
        (directory / name).write_text(json.dumps(data), encoding="utf-8")
    (directory / "windows.jsonl").write_text(
        "\n".join(json.dumps(r) for r in (header, real, {"type": "end"})), encoding="utf-8"
    )
    case = next(c for c in SPEC.cases("A") if c.expected_outcome is None)
    row = {
        **SPEC.arm(ARM).identity(MEMBER),
        **identity,
        "case_id": case.case_id,
        "monitor_kind": "host_retrospective",
        "execution_state": "launched",
        "monitor_request_numbers": [2],
        "process_complete": True,
        "active_after_teardown": 0,
        "elapsed_ms": 1,
        "outcome": "suggestion",
        "reason": "",
        "details": {},
    }
    return directory, identity, analysis, row, real


def test_complete_retrospective_evidence_normalizes_only_derived_copy(tmp_path):
    directory, identity, analysis, row, _ = capture_fixture(tmp_path)
    problems = capture_problems(directory, analysis, [row], **identity)
    assert problems == []
    normalized = verified_contract_rows([row], problems)
    assert row["monitor_kind"] == "host_retrospective"
    assert (
        normalized[0]["monitor_kind"] == "host"
        and normalized[0]["monitor_implementation"] == "host_retrospective"
    )
    assert record_problems(normalized, SPEC.document, ARM, [row["case_id"]]) == []


@pytest.mark.parametrize(
    "defect",
    [
        "pending",
        "FAIL",
        "INCONCLUSIVE",
        "host_label",
        "capture_id",
        "missing_process",
        "interval",
        "connection",
        "file",
        "synthetic",
    ],
)
def test_retrospective_proof_cannot_promote_missing_or_invalid_evidence(tmp_path, defect):
    directory, identity, analysis, row, raw = capture_fixture(tmp_path)
    if defect in ("FAIL", "INCONCLUSIVE"):
        analysis["verdict"] = defect
    if defect == "pending":
        analysis = None
    if defect == "host_label":
        row["monitor_kind"] = "host"
    if defect == "capture_id":
        row["capture_id"] = "stale"
    if defect == "missing_process":
        raw["members"] = []
    if defect == "interval":
        raw["members"][0]["end_ns"] = None
    if defect == "connection":
        analysis["requests"][1]["owned_connection_events"] = 1
    if defect == "file":
        analysis["requests"][1]["violations"] = ["file_access_outside_policy"]
    if defect == "synthetic":
        row["synthetic"] = True
    entries = [json.loads(line) for line in (directory / "windows.jsonl").read_text().splitlines()]
    entries[1] = raw
    (directory / "windows.jsonl").write_text(
        "\n".join(json.dumps(r) for r in entries), encoding="utf-8"
    )
    problems = capture_problems(directory, analysis, [row], **identity)
    assert problems
    assert verified_contract_rows([row], problems)[0]["monitor_kind"] == row["monitor_kind"]


def test_host_label_or_cooperative_provider_is_not_monitor_authority(
    tmp_path, monkeypatch, windows_capture_host
):
    assert monitor_problems(SimpleNamespace(kind="host", admission=True))
    assert monitor_problems(SimpleNamespace(kind="host_retrospective", admission=True))
    authentic = monitor_for(tmp_path, monkeypatch)
    assert monitor_problems(authentic) == []
    authentic.providers[0].coverage = "cooperative"
    assert monitor_problems(authentic)


@pytest.mark.parametrize(
    "host_name,elevated,expected",
    [
        ("posix", False, "Windows job object"),
        ("nt", True, "elevated or unreadable"),
        ("nt", None, "elevated or unreadable"),
    ],
)
def test_authentic_monitor_still_requires_windows_and_standard_user(
    tmp_path, monkeypatch, host_name, elevated, expected
):
    monitor = monitor_for(tmp_path, monkeypatch)
    monkeypatch.setattr(
        capture_session, "os", SimpleNamespace(**{**vars(capture_session.os), "name": host_name})
    )
    monkeypatch.setattr(monitor, "_self_elevated", lambda: elevated)
    assert any(expected in problem for problem in monitor_problems(monitor))


def test_childless_frozen_cases_are_independently_prelaunch_rejected(tmp_path):
    from src.ai_assist.runtime import AiRuntime

    calls = []
    runtime = AiRuntime(tmp_path, runner=lambda *a, **k: calls.append(a))
    verification = SimpleNamespace(
        ok=True,
        executable=tmp_path / "inert.exe",
        model_path=tmp_path / "inert.gguf",
        build=SimpleNamespace(),
    )
    count = 0
    for case in SPEC.cases("B"):
        if case.expected_outcome != "invalid_request":
            continue
        count += 1
        outcome = runtime.run_once(
            verification,
            case.request("test"),
            RunLimits(),
            Sampling(),
            lambda: False,
            lambda: (OutcomeCode.CANCELLED, "test"),
        )
        assert (outcome.code.value, outcome.reason) == (
            "invalid_request",
            "reserved_marker_in_text",
        )
        fields, problems = record_execution(case.case_id, outcome.code.value, outcome.reason, [])
        assert not problems
        assert not childless_record_problems(
            {
                "case_id": case.case_id,
                "outcome": outcome.code.value,
                "reason": outcome.reason,
                **fields,
            }
        )
    assert count == 10 and calls == []


def test_childless_record_retains_case_without_fabricated_process(tmp_path):
    directory, identity, analysis, launched, _ = capture_fixture(tmp_path)
    case = next(c for c in SPEC.cases("A") if c.expected_outcome == "invalid_request")
    fields, errors = record_execution(
        case.case_id, "invalid_request", "reserved_marker_in_text", []
    )
    childless = {
        **launched,
        **fields,
        "case_id": case.case_id,
        "outcome": "invalid_request",
        "reason": "reserved_marker_in_text",
    }
    assert (
        errors == []
        and childless["process_complete"] is None
        and childless["monitor_request_numbers"] == []
    )
    problems = capture_problems(directory, analysis, [childless, launched], **identity)
    assert problems == []
    normalized = verified_contract_rows([childless, launched], problems)
    assert (
        record_problems(normalized, SPEC.document, ARM, [case.case_id, launched["case_id"]]) == []
    )
    childless["process_complete"] = True
    assert capture_problems(directory, analysis, [childless, launched], **identity)
    assert record_execution(launched["case_id"], "suggestion", "", [])[1]


@pytest.mark.parametrize(
    "failed_probe,mode,expected_calls",
    [
        (None, "complete", 2),
        (0, "missing", 1),
        (0, "unreadable", 1),
        (0, "survivor", 1),
        (0, "violation", 1),
        (1, "survivor", 2),
    ],
)
def test_probe_sequence_records_partial_evidence_and_stops(
    tmp_path, monkeypatch, failed_probe, mode, expected_calls
):
    monitor = monitor_for(tmp_path, monkeypatch)
    calls = []

    class Service:
        def __init__(self, **kwargs):
            pass

        def run(self, *args):
            index = len(calls)
            calls.append(index)
            process = {"complete": True, "active_after_teardown": 0}
            violations = []
            if index == failed_probe:
                if mode == "unreadable":
                    process = {}
                if mode == "survivor":
                    process["active_after_teardown"] = 1
                if mode == "violation":
                    violations = ["ownership_unreadable"]
            if not (index == failed_probe and mode == "missing"):
                monitor.records.append(
                    SimpleNamespace(number=index + 1, process=process, violations=violations)
                )
            return SimpleNamespace(
                code=OutcomeCode.TIMEOUT if index == 0 else OutcomeCode.CANCELLED,
                reason="original_reason",
                elapsed_ms=1,
            )

    monkeypatch.setattr(physical, "AiAssistService", Service)
    monkeypatch.setattr(
        physical.threading,
        "Timer",
        lambda *a: SimpleNamespace(start=lambda: None, cancel=lambda: None),
    )
    rows = physical._lifecycle_probes(
        SPEC.cases("A")[3],
        ARM,
        tmp_path,
        SimpleNamespace(),
        SPEC.arm(ARM).model,
        monitor,
        lambda: None,
        Sampling(),
        RunLimits(),
        None,
        True,
    )
    assert len(calls) == expected_calls and len(rows) == expected_calls
    assert rows[-1]["reason"] == "original_reason"
    if failed_probe is not None:
        assert rows[-1]["stop_reason"] and monitor._executable_stop_reason
        later = []
        outcome = monitor.runner(lambda *a, **k: later.append(a))(["inert"])
        assert outcome.launch_error and later == []


def test_uncertain_owned_interval_never_launches_closing_canary(tmp_path, monkeypatch):
    monitor = monitor_for(tmp_path, monkeypatch)
    monitor.admission.capture_dir.mkdir()
    monitor._begun = True
    launched = []
    monkeypatch.setattr(monitor, "_canary_child", lambda *a: launched.append(a))
    monitor.block_executable_work("teardown not verified")
    monitor.close_and_report(None)
    assert launched == []
    entries = [
        json.loads(line)
        for line in (monitor.admission.capture_dir / "windows.jsonl").read_text().splitlines()
    ]
    assert any(r["type"] == "end_failed" for r in entries)


def test_next_capture_cannot_admit_an_unresolved_previous_segment(tmp_path, monkeypatch):
    from tests.tools.test_ai115b_contract_harness import _plan
    from tools.qualification.ai111 import stage_b_captures

    plan = _plan(tmp_path)
    monkeypatch.setattr(stage_b_captures, "verify_plan", lambda *a: [])
    monkeypatch.setattr(stage_b_captures, "capture_problems", lambda *a, **k: [])
    previous, current = plan["segments"][:2]
    root = Path(current["evidence_root"])
    capture = root / "capture"
    capture.mkdir(parents=True)
    (capture / "capture.json").write_text(
        json.dumps(
            {
                "capture_id": current["capture_id"],
                "max_mb_per_session": 1024,
                "minutes": plan["capture_minutes"],
            }
        )
    )
    previous_root = Path(previous["evidence_root"])
    (previous_root / "capture").mkdir(parents=True)
    (previous_root / "physical-B").mkdir()
    (previous_root / "capture/analysis.json").write_text(json.dumps({"verdict": "PASS"}))
    (previous_root / "physical-B/records.jsonl").write_text(
        "\n".join(json.dumps({"case_id": c}) for c in previous["case_ids"])
    )
    (previous_root / "physical-B/result.json").write_text(
        json.dumps({"abort_reason": "lifecycle teardown uncertain", "teardown_verified": False})
    )
    approvals = {
        "approval_records": {
            "S4_stage_b": {"reference": plan["approval_reference"], "text": plan["manifest_sha256"]}
        }
    }
    with pytest.raises(ValueError, match="previous capture"):
        stage_b_captures.execution_segment(plan, SPEC, 1, current["run_id"], root, approvals)


@pytest.mark.parametrize("failure", ["exception", "canary_ownership_missing", "provider_refusal"])
def test_every_unsafe_runner_path_fences_closing_children(tmp_path, monkeypatch, failure):
    from src.utils.managed_process import ProcessOutcome

    monitor = monitor_for(tmp_path, monkeypatch)
    monitor.admission.capture_dir.mkdir()
    monitor._begun = True
    monkeypatch.setattr(monitor.admission, "live_problems", lambda: [])
    monkeypatch.setattr(monitor.admission, "projection_problems", lambda *a: [])
    closing = []
    monkeypatch.setattr(monitor, "_canary_child", lambda *a: closing.append(a))
    inner_calls = []

    def inner(*args, **kwargs):
        inner_calls.append(args)
        if failure == "exception":
            raise RuntimeError("original runner failure")
        return ProcessOutcome(returncode=0)

    if failure == "provider_refusal":

        def refuse():
            raise OSError("provider unavailable")

        monkeypatch.setattr(monitor.providers[0], "begin", refuse)
    if failure == "exception":
        with pytest.raises(RuntimeError, match="original runner failure"):
            monitor.runner(inner, canary=True)(["inert"])
    else:
        monitor.runner(inner, canary=True)(["inert"])
    assert monitor._executable_stop_reason
    assert monitor.records and monitor.records[-1].process == {}
    monitor.close_and_report(None)
    assert closing == []
    assert len(inner_calls) == (0 if failure == "provider_refusal" else 1)


@pytest.mark.parametrize("probes_requested", [False, True])
def test_real_frozen_prelaunch_only_segment_preserves_every_case(
    tmp_path, monkeypatch, probes_requested
):
    from tests.tools.test_ai115b_contract_harness import _plan
    from tools.qualification.ai111 import stage_b_captures
    from tools.qualification.ai111.execution_evidence import session_teardown_problems

    monitor, cases, calls = session_world(tmp_path, monkeypatch)
    plan = _plan(tmp_path)
    segment = plan["segments"][44]
    cases[:] = [c for c in SPEC.cases("B") if c.case_id in segment["case_ids"]]
    assert len(cases) == 10 and all(c.expected_outcome == "invalid_request" for c in cases)
    monkeypatch.setattr(stage_b_captures, "execution_segment", lambda *a: segment)
    result = physical._run_session(
        plan=SPEC.execution_plan(),
        paths=physical.SessionPaths(
            tmp_path,
            tmp_path / "absent.zip",
            {SPEC.arm(ARM).model.model_id: tmp_path / "absent.gguf"},
        ),
        stage="B",
        arms=[ARM],
        cases=cases,
        authorization_text="test",
        contract_spec=SPEC,
        monitor=monitor,
        executable=MEMBER,
        strict_offline=True,
        gpu_probe=lambda: [],
        busy_provider=lambda: [],
        capture_plan=plan,
        capture_segment=segment,
        lifecycle_probes=probes_requested,
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "physical-B/records.jsonl").read_text().splitlines()
    ]
    manifest = json.loads((tmp_path / "physical-B/execution-manifest.json").read_text())
    assert calls == segment["case_ids"] and len(rows) == 10
    assert monitor.session_records() == []
    assert (
        result["no_processes_launched"] is True
        and result["teardown_verified"] is None
        and result["abort_reason"] == ""
    )
    assert session_teardown_problems(result, rows) == []
    assert (
        manifest["lifecycle_probes"] is False
        and manifest["lifecycle_probes_requested"] == probes_requested
    )


def test_prelaunch_only_capture_is_verified_without_fabricating_teardown(tmp_path):
    from tools.qualification.ai111.execution_evidence import session_teardown_problems

    directory, identity, analysis, prototype, _ = capture_fixture(tmp_path)
    rows = []
    for case in SPEC.cases("B")[440:450]:
        fields, errors = record_execution(
            case.case_id, "invalid_request", "reserved_marker_in_text", []
        )
        assert errors == []
        rows.append(
            {
                **prototype,
                **fields,
                "case_id": case.case_id,
                "outcome": "invalid_request",
                "reason": "reserved_marker_in_text",
            }
        )
    analysis["kind"] = "canary_capture"
    analysis["requests"] = [r for r in analysis["requests"] if r["canary"]]
    (directory / "analysis.json").write_text(json.dumps(analysis))
    entries = [json.loads(line) for line in (directory / "windows.jsonl").read_text().splitlines()]
    (directory / "windows.jsonl").write_text(
        "\n".join(json.dumps(r) for r in entries if r["type"] != "request")
    )
    assert capture_problems(directory, analysis, rows, **identity) == []
    result = {"abort_reason": "", "no_processes_launched": True, "teardown_verified": None}
    assert session_teardown_problems(result, rows) == []
    result["teardown_verified"] = True
    assert session_teardown_problems(result, rows)
    rows[0]["reason"] = "unverified_reason"
    assert capture_problems(directory, analysis, rows, **identity)
