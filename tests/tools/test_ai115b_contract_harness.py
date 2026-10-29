"""Synthetic artifacts, inert runners and mock capture evidence only. No runtime/model/ETW execution."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ai_assist.argv import ALLOWED_FLAGS, RunLimits, Sampling, build_argv
from src.ai_assist.contracts import OutcomeCode
from src.ai_assist.runtime import AiRuntime
from src.utils.managed_process import ProcessOutcome
from tests.ai_assist.conftest import request_for
from tools.qualification.ai111 import d12a, physical
from tools.qualification.ai111 import lfm3_contract as lfm
from tools.qualification.ai111 import stage_b_captures as stage_b
from tools.qualification.ai111.capture_analysis import ANALYZER_VERSION, analyzer_sha256
from tools.qualification.ai111.capture_control import provider_config_sha256, tool_sha256
from tools.qualification.ai111.capture_evidence import capture_problems
from tools.qualification.ai111.execution_contract import select_contract
from tools.qualification.ai111.plan import digest, frozen_plan
from tools.qualification.ai111.readiness import (
    approval_records,
    dependency_problems,
    readiness_problems,
)
from tools.qualification.ai111.stage_a_contract import sensitivity_selection

SPEC = select_contract("lfm3-v1")
ARMS = [a["arm_id"] for a in SPEC.document["arms"] if a["kind"] != "baseline"]
ARM = ARMS[0]
MEMBER = "llama-completion.exe"


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _disposition(profile="lfm3_vendor"):
    return {
        "stage": "A",
        "contract_sha256": SPEC.sha256,
        "advance": True,
        "sampling_profile": profile,
        "protected_token_malformed": {
            ARMS[0]: 1 if profile == "lfm3_no_repeat" else 0,
            ARMS[-1]: 0,
        },
    }


def _plan(tmp_path, **kwargs):
    return stage_b.build_plan(
        SPEC,
        arms=kwargs.pop("arms", [ARM]),
        disposition=kwargs.pop("disposition", _disposition()),
        evidence_root=tmp_path.resolve(),
        plan_id="20261029T201500Z-tests",
        cases_per_capture=kwargs.pop("cases_per_capture", 10),
        approval_reference="owner-S4-separate",
        **kwargs,
    )


def test_contract_separation_and_immutability():
    qwen = select_contract()
    assert qwen.document == frozen_plan()
    assert qwen.runtime["tag"] == "b11840"
    assert SPEC.runtime["tag"] == "b11960" and len(SPEC.runtime["files"]) == 51
    for arm in ARMS:
        resolved = SPEC.arm(arm)
        assert resolved.contract.runtime["tag"] == "b11960"
        if "qwen" in arm:
            assert (
                resolved.profile == "qwen_frozen" and resolved.sampling == frozen_plan()["sampling"]
            )
    mutable = SPEC.document
    mutable["runtime"]["selected"] = "b99999"
    assert SPEC.runtime["tag"] == "b11960"
    assert len(SPEC.cases("A")) == 30 and len(SPEC.cases("B")) == 460
    assert digest(lfm.contract()) == lfm.FROZEN_CONTRACT_SHA256


@pytest.mark.parametrize(
    "selector,sha",
    [("lfm3-v2", None), ("unknown", None), ("lfm3-v1", "0" * 64), ("qwen-frozen", SPEC.sha256)],
)
def test_unknown_or_mixed_contract_refused(selector, sha):
    with pytest.raises(ValueError):
        select_contract(selector, sha)


def test_all_profiles_and_legacy_argv_identical():
    paths = [Path("model"), Path("prompt"), Path("schema")]
    limits = RunLimits()
    legacy = build_argv(*paths, limits, Sampling())
    assert (
        select_contract().arm("qwen3.5-4b-q4_k_m-unsloth").argv(*paths, limits, Sampling())
        == legacy
    )
    assert SPEC.arm(ARMS[1]).argv(*paths, limits, Sampling()) == legacy
    for arm in (ARMS[0], ARMS[-1]):
        selected = SPEC.arm(arm)
        argv = selected.argv(*paths, limits, Sampling())
        assert argv == lfm.lfm3_argv(selected.profile, *paths, limits)
        assert argv[argv.index("--min-p") + 1] == "0.0"
        assert argv[argv.index("--repeat-penalty") + 1] == ("1.0" if arm == ARMS[-1] else "1.1")


@pytest.mark.parametrize(
    "flag", ["--rpc", "--host", "--port", "--connect", "--server", "--unexpected"]
)
def test_injected_builder_cannot_escape_allowlist(tmp_path, flag):
    calls = []
    runtime = AiRuntime(
        tmp_path, runner=lambda *a, **k: calls.append(a), argv_builder=lambda *a: [flag]
    )
    verification = SimpleNamespace(
        ok=True,
        executable=tmp_path / "fake.exe",
        model_path=tmp_path / "fake.gguf",
        build=SimpleNamespace(build_id="fake"),
    )
    with pytest.raises(ValueError):
        runtime.run_once(
            verification,
            request_for("prompt_rewrite"),
            RunLimits(),
            Sampling(),
            lambda: False,
            lambda: (OutcomeCode.CANCELLED, "test"),
        )
    assert calls == []


def test_default_runtime_builder_uses_existing_runner(tmp_path):
    calls = []
    runtime = AiRuntime(
        tmp_path,
        runner=lambda command, **kw: calls.append(command)
        or ProcessOutcome(returncode=0, stdout=b"{}", contained=True),
        environ={},
    )
    verification = SimpleNamespace(
        ok=True,
        executable=tmp_path / "fake.exe",
        model_path=tmp_path / "fake.gguf",
        build=SimpleNamespace(build_id="fake"),
    )
    result = runtime.run_once(
        verification,
        request_for("prompt_rewrite"),
        RunLimits(),
        Sampling(),
        lambda: False,
        lambda: (OutcomeCode.CANCELLED, "test"),
    )
    assert result.code is None and len(calls) == 1
    expected = build_argv(
        verification.model_path,
        Path(calls[0][calls[0].index("-f") + 1]),
        Path(calls[0][calls[0].index("--json-schema-file") + 1]),
        RunLimits(),
        Sampling(),
    )
    assert calls[0] == [str(verification.executable), *expected]


@pytest.mark.parametrize(
    "text,truncated,verdict",
    [
        ("", False, "INCONCLUSIVE"),
        ("--offline", False, "FAIL"),
        ("--offline", True, "INCONCLUSIVE"),
        (" ".join(lfm.LFM3_ALLOWED_FLAGS), True, "INCONCLUSIVE"),
        (" ".join(lfm.LFM3_ALLOWED_FLAGS), False, "PASS"),
    ],
)
def test_help_is_complete_and_requires_lfm_flags(text, truncated, verdict):
    assert (
        d12a.analyze_help(text, truncated=truncated, required_flags=lfm.LFM3_ALLOWED_FLAGS)[
            "verdict"
        ]
        == verdict
    )
    assert lfm.help_flag_report(text, truncated=truncated)["verdict"] == verdict
    if not truncated:
        assert (
            d12a.analyze_help(
                " ".join(ALLOWED_FLAGS), truncated=False, required_flags=lfm.LFM3_ALLOWED_FLAGS
            )["verdict"]
            == "FAIL"
        )


def _archive(tmp_path, change=None):
    files = {MEMBER: b"inert completion", "llama-completion-impl.dll": b"inert implementation"}
    pins = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
    if change == "extra":
        files["extra.dll"] = b"extra"
    if change == "missing":
        files.pop("llama-completion-impl.dll")
    path = tmp_path / "inert.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
        if change in ("unsafe", "duplicate", "link"):
            name = (
                "../escape.dll"
                if change == "unsafe"
                else MEMBER.upper()
                if change == "duplicate"
                else "redirect.dll"
            )
            info = zipfile.ZipInfo(name)
            if change == "link":
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, b"inert")
    intent = {
        **SPEC.runtime,
        "files": pins,
        "members": {MEMBER: pins[MEMBER]},
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    spec = SimpleNamespace(runtime=intent, members=intent["members"])
    return path, spec


@pytest.mark.parametrize(
    "change", ["extra", "missing", "unsafe", "duplicate", "link", "hash", "executable", "fallback"]
)
def test_contract_archive_rejects_every_integrity_drift(tmp_path, change):
    path, spec = _archive(tmp_path, change)
    intent = spec.runtime
    executable = MEMBER
    if change == "hash":
        intent["sha256"] = "0" * 64
    if change == "executable":
        spec.members[MEMBER] = "0" * 64
    if change == "fallback":
        executable = None
    with pytest.raises((physical.ImportRefused, d12a.D12aRefused, KeyError)):
        physical.derive_runtime_build(path, intent, executable, spec=spec)


def test_archive_post_extraction_drift(tmp_path):
    path, spec = _archive(tmp_path)
    build = physical.derive_runtime_build(path, spec.runtime, MEMBER, spec=spec)
    assert build.files == spec.runtime["files"]
    with zipfile.ZipFile(path) as bundle:
        members = {
            n: (hashlib.sha256(bundle.read(n)).hexdigest(), len(bundle.read(n)))
            for n in bundle.namelist()
        }
    target = tmp_path / "inert-tree"
    d12a.extract_archive(path, target)
    assert not d12a.verify_extracted(target, members, members)
    (target / MEMBER).write_bytes(b"changed")
    assert d12a.verify_extracted(target, members, members)


@pytest.mark.parametrize("stage", ["S2_d12a_b11960", "S3_stage_a", "S4_stage_b"])
def test_readiness_never_creates_authority(stage):
    problems = readiness_problems(SPEC, stage, {}, executable=MEMBER)
    assert any("authorization" in p for p in problems)
    assert "protected_python measured protection proof absent" in problems
    assert "fresh applicable canary proof absent" in problems
    assert readiness_problems(
        SPEC,
        stage,
        {"approvals": "all approved", "approval_records": True, "protected_runtime": True},
        executable=MEMBER,
    )


def test_old_digest_and_old_or_future_grants_fail():
    now = datetime(2026, 10, 29, 20, tzinfo=UTC)
    for issued, text in [
        ("2026-10-28T20:00:00Z", SPEC.sha256),
        ("2026-10-30T00:00:00Z", SPEC.sha256),
        ("2026-10-29T19:00:00Z", "0" * 64),
    ]:
        evidence = {
            "approval_records": {
                s: {
                    "authority": "owner",
                    "decision": "APPROVE",
                    "issued_utc": issued,
                    "reference": "independent",
                    "text": s + text,
                }
                for s in SPEC.document["approvals"]
            }
        }
        assert approval_records(SPEC, evidence, "S4_stage_b", now)
    assert dependency_problems({"status": "PASS", "operator_attested": True}) == [
        "host dependency closure unmeasured"
    ]


def _reports():
    return [
        {
            "stage": "A",
            "contract_sha256": SPEC.sha256,
            "case_ids_sha256": digest([c.case_id for c in SPEC.cases("A")]),
            "attribution_problems": [],
            "capture_id": f"capture-{i}",
            "models": {arm: {"judgement": {"recommendation": "ADVANCE"}}},
            "selection_counts": {arm: 0},
        }
        for i, arm in enumerate(ARMS)
    ]


def test_stage_a_selection_is_exact_and_boundary_frozen():
    reports = _reports()
    assert sensitivity_selection(reports, SPEC)["sampling_profile"] == "lfm3_vendor"
    reports[0]["selection_counts"][ARM] = 1
    assert sensitivity_selection(reports, SPEC)["sampling_profile"] == "lfm3_no_repeat"
    reports[-1]["selection_counts"][ARMS[-1]] = 1
    assert sensitivity_selection(reports, SPEC)["sampling_profile"] == "lfm3_vendor"
    for invalid in (reports[:-1], reports + [reports[0]]):
        with pytest.raises(ValueError):
            sensitivity_selection(invalid, SPEC)
    reports[0]["attribution_problems"] = ["wrong case list"]
    with pytest.raises(ValueError):
        sensitivity_selection(reports, SPEC)


def test_stage_b_deterministic_capacity_and_exact_order(tmp_path):
    first = _plan(tmp_path)
    assert first == _plan(tmp_path)
    assert len(first["segments"]) == 46
    assert [c for s in first["segments"] for c in s["case_ids"]] == [
        c.case_id for c in SPEC.cases("B")
    ]
    assert len({s["capture_id"] for s in first["segments"]}) == 46
    assert stage_b.verify_plan(first, SPEC, source_evidence=False) == []
    assert stage_b.verify_plan(
        first, SPEC
    )  # No synthetic Stage A report can authorize physical work.
    with pytest.raises(ValueError, match="capacity"):
        _plan(tmp_path, cases_per_capture=460)
    first["segments"][1]["case_ids"][0] = first["segments"][0]["case_ids"][0]
    assert stage_b.verify_plan(first, SPEC, source_evidence=False)


def _synthetic_flow(tmp_path, monkeypatch, profile="lfm3_vendor"):
    # Revalidation of Stage A source is exercised separately. This explicit seam
    # provides simulated Stage A disposition; all rows retain a synthetic marker.
    disposition = _disposition(profile)
    monkeypatch.setattr(stage_b, "load_selection", lambda *args: disposition)
    plan = _plan(tmp_path, disposition=disposition)
    cases = {c.case_id: c for c in SPEC.cases("B")}
    for segment in plan["segments"]:
        root = Path(segment["evidence_root"])
        minute = segment["index"] * 2
        start = datetime(2026, 10, 29, 10, tzinfo=UTC).timestamp() + minute * 60

        def stamp(seconds, start=start):
            return datetime.fromtimestamp(start + seconds, UTC).isoformat()

        capture = {
            "capture_id": segment["capture_id"],
            "run_id": segment["run_id"],
            "created_utc": stamp(0),
            "deadline_utc": stamp(90),
            "max_mb_per_session": 1024,
        }
        stopped = {"state": "STOPPED", "sessions_left": [], "stopped_utc": stamp(60)}
        _write(root / "capture/capture.json", capture)
        _write(root / "capture/state-02-active.json", {"state": "ACTIVE"})
        _write(root / "capture/state-04-stopped.json", stopped)
        _write(root / "capture/verification.json", {"state": "VERIFIED", "verdict": "PASS"})
        rows, requests = [], [{"number": 0, "canary": True, "canary_problems": []}]
        for i, case_id in enumerate(segment["case_ids"], 1):
            c = cases[case_id]
            overall = segment["offset"] + i
            rows.append(
                {
                    **plan["arms"][ARM],
                    "case_id": case_id,
                    "outcome": "suggestion",
                    "reason": "",
                    "elapsed_ms": 1000,
                    "details": {"child_observed": True, "priority_verified": True},
                    "positive": c.positive,
                    "negative": c.negative,
                    "monitor_kind": "host",
                    "capture_id": segment["capture_id"],
                    "run_id": segment["run_id"],
                    "monitor_request_numbers": [i],
                    "process_complete": True,
                    "active_after_teardown": 0,
                    "arm_request_index": overall,
                    "capture_request_index": i,
                    "phase": "cold" if overall == 1 else "warm",
                    "synthetic": True,
                }
            )
            requests.append(
                {
                    "number": i,
                    "canary": False,
                    "executable": MEMBER,
                    "executable_sha256": SPEC.members[MEMBER],
                    "owned_connection_events": 0,
                    "ambiguous_events": 0,
                    "violations": [],
                }
            )
        requests.append({"number": len(rows) + 1, "canary": True, "canary_problems": []})
        analysis = {
            "capture_id": segment["capture_id"],
            "run_id": segment["run_id"],
            "kind": "qualification_capture",
            "verdict": "PASS",
            "analyzer_version": ANALYZER_VERSION,
            "analyzer_sha256": analyzer_sha256(),
            "tool_sha256": tool_sha256(),
            "provider_config_sha256": provider_config_sha256(),
            "capture_problems": [],
            "state": "STOPPED",
            "stop_record": stopped,
            "traces": {k: {"header_ok": True} for k in ("file", "network", "dns")},
            "requests": requests,
        }
        _write(root / "capture/analysis.json", analysis)
        _write(
            root / "physical-B/execution-manifest.json",
            {
                "stage": "B",
                "contract_sha256": SPEC.sha256,
                "run_id": segment["run_id"],
                "capture_id": segment["capture_id"],
                "capture_segment": {"manifest_sha256": plan["manifest_sha256"]},
            },
        )
        _write(root / "physical-B/result.json", {"teardown_verified": True, "abort_reason": ""})
        path = root / "physical-B/records.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return plan


def test_end_to_end_synthetic_plan_and_aggregate_never_go(tmp_path, monkeypatch):
    plan = _synthetic_flow(tmp_path, monkeypatch)
    result = stage_b.aggregate(plan)
    assert len(result["captures"]) == 46 and len(result["records"][ARM]) == 460
    assert result["arms"][ARM]["verdict"] == "INCONCLUSIVE"
    assert any("attribution" in p for p in result["problems"])
    assert result["blind"][ARM]["preference"] is None
    assert all(
        set(p) == {"pair_id", "left", "right"} for p in result["blind"][ARM]["operator_view"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "459",
        "461",
        "duplicate",
        "wrong_capture",
        "expired",
        "connection",
        "loopback",
        "file",
        "survivor",
        "loss",
        "contradiction",
        "sampling",
        "runtime",
        "chronology",
        "replacement",
    ],
)
def test_stage_b_negative_capture_classes(tmp_path, monkeypatch, mutation):
    plan = _synthetic_flow(tmp_path, monkeypatch)
    root = Path(plan["segments"][0]["evidence_root"])
    rows = [
        json.loads(line) for line in (root / "physical-B/records.jsonl").read_text().splitlines()
    ]
    analysis = json.loads((root / "capture/analysis.json").read_text())
    if mutation == "459":
        rows.pop()
    if mutation == "461":
        rows.append({**rows[-1], "case_id": "extra"})
    if mutation == "duplicate":
        rows[-1] = rows[0]
    if mutation == "wrong_capture":
        analysis["capture_id"] = "stale"
    if mutation == "expired":
        stopped = json.loads((root / "capture/state-04-stopped.json").read_text())
        stopped["stopped_utc"] = "2026-10-30T00:00:00+00:00"
        _write(root / "capture/state-04-stopped.json", stopped)
    if mutation in ("connection", "loopback"):
        analysis["requests"][1]["owned_connection_events"] = 1
    if mutation == "file":
        analysis["requests"][1]["violations"] = ["forbidden_file"]
    if mutation == "survivor":
        rows[0]["active_after_teardown"] = 1
    if mutation == "loss":
        analysis["capture_problems"] = ["lost events"]
    if mutation == "contradiction":
        _write(root / "capture/analysis-2.json", {"verdict": "FAIL"})
    if mutation == "sampling":
        rows[0]["sampling_values"] = {}
    if mutation == "runtime":
        rows[0]["runtime_asset_sha256"] = "0" * 64
    if mutation == "chronology":
        rows[0]["arm_request_index"] = 999
    if mutation == "replacement":
        plan["segments"][0]["capture_id"] = "20261029T201500Z-deadbeef"
    (root / "physical-B/records.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    _write(root / "capture/analysis.json", analysis)
    result = stage_b.aggregate(plan)
    assert result["problems"] and result["arms"][ARM]["verdict"] != "GO"
    expected = {
        "459": "capture case list",
        "461": "capture case list",
        "duplicate": "capture case list",
        "wrong_capture": "capture capture_id",
        "expired": "expired",
        "connection": "attribution",
        "loopback": "attribution",
        "file": "attribution",
        "survivor": "attribution",
        "loss": "capture capture_problems",
        "contradiction": "contradictory",
        "sampling": "sampling drift",
        "runtime": "sampling drift",
        "chronology": "chronology",
        "replacement": "plan changed",
    }[mutation]
    assert any(expected in p for p in result["problems"]), result["problems"]


def test_no_repeat_stage_b_binds_both_quantizations(tmp_path):
    disposition = _disposition("lfm3_no_repeat")
    for arm in (ARMS[0], ARMS[2]):
        selected = stage_b.selected_arm(SPEC, arm, disposition)
        identity = selected.identity(MEMBER)
        row = {**identity, "monitor_kind": "host", "case_id": "one"}
        assert not lfm.record_problems(
            [row], SPEC.document, arm, ["one"], stage_a_disposition=disposition
        )
        assert lfm.record_problems([row], SPEC.document, arm, ["one"])


def test_fewer_than_100_decisive_and_incomplete_blind_data(tmp_path):
    cases = list(SPEC.cases("B"))
    rows = []
    for c in cases:
        for arm in (ARM, "B1_engine"):
            rows.append(
                {
                    "case_id": c.case_id,
                    "arm": arm,
                    "outcome": "suggestion",
                    "positive": c.positive,
                    "negative": c.negative,
                }
            )
    data = stage_b._blind(cases, rows, ARM, "B1_engine", {"p0001": "left"})
    assert data["preference"]["decided"] == 1
    with pytest.raises(ValueError):
        stage_b._blind(cases, rows, ARM, "B1_engine", {"p9999": "left"})


def test_preallocated_capture_identity_uses_same_bounded_operator_surface(tmp_path):
    from tests.tools.ai114e_support import FakeLogman, make_env
    from tools.qualification.ai111 import capture_control as control

    fake = FakeLogman()
    env = make_env(tmp_path, fake)
    identity = "20261029T201500Z-a0b1c2d3"
    target = env.reports_root / "planned" / "capture"
    result = control.start_capture(target, run_id="planned", capture_id=identity, env=env)
    assert result["capture_id"] == identity
    assert all(identity in name for name in fake.sessions)
    before = len(fake.calls)
    with pytest.raises(control.CaptureRefused):
        control.start_capture(
            env.reports_root / "other", run_id="other", capture_id="../../escape", env=env
        )
    assert len(fake.calls) == before


def test_absent_authorization_refuses_before_artifact_or_runner_access(tmp_path, monkeypatch):
    monitor = SimpleNamespace(kind="host", provider_problems=lambda: [])
    result = physical._run_session(
        plan=SPEC.execution_plan(),
        paths=physical.SessionPaths(tmp_path, tmp_path / "absent.zip", {}),
        stage="A",
        arms=[ARM],
        cases=list(SPEC.cases("A")),
        authorization_text="implementation only",
        contract_spec=SPEC,
        monitor=monitor,
        executable=MEMBER,
        strict_offline=True,
        gpu_probe=lambda: [],
    )
    assert result["verdict"] == "NOT TESTED"
    assert not (tmp_path / "physical-A").exists()
    with pytest.raises(d12a.D12aRefused, match="authorization"):
        d12a.run_d12a(
            archive=tmp_path / "absent.zip",
            passive_manifest=None,
            evidence_root=tmp_path,
            monitor=monitor,
            authorization_text="implementation only",
            attestation="operator statement",
            contract_spec=SPEC,
            executable=MEMBER,
        )


def test_capture_attribution_positive_simulation_is_distinct_from_synthetic_go(
    tmp_path, monkeypatch
):
    from tools.qualification.ai111.capture_evidence import read_json, read_rows

    plan = _synthetic_flow(tmp_path, monkeypatch)
    s = plan["segments"][0]
    root = Path(s["evidence_root"])
    rows = read_rows(root / "physical-B/records.jsonl")
    assert capture_problems(
        root / "capture",
        read_json(root / "capture/analysis.json"),
        rows,
        run_id=s["run_id"],
        capture_id=s["capture_id"],
    )
    # Removing a synthetic marker must not promote self-asserted host labels.
    # The independent repair suite covers complete raw owned-window provenance.
    for row in rows:
        row.pop("synthetic")
    assert any(
        "provenance" in problem
        for problem in capture_problems(
            root / "capture",
            read_json(root / "capture/analysis.json"),
            rows,
            run_id=s["run_id"],
            capture_id=s["capture_id"],
        )
    )
    rows[0].pop("process_complete")
    assert any(
        "teardown" in p
        for p in capture_problems(
            root / "capture",
            read_json(root / "capture/analysis.json"),
            rows,
            run_id=s["run_id"],
            capture_id=s["capture_id"],
        )
    )


def _stage_a_world(tmp_path, monkeypatch):
    from tools.qualification.ai111 import stage_a_contract as report
    from tools.qualification.ai111.corpus import corpus_digest

    monkeypatch.setattr(report, "capture_problems", lambda *a, **k: [])
    monkeypatch.setattr(report, "readiness_problems", lambda *a, **k: [])
    monkeypatch.setattr(report, "d12a_problems", lambda *a, **k: [])
    evidence = tmp_path / "physical-A"
    _write(
        evidence / "execution-manifest.json",
        {
            "stage": "A",
            "arms": [ARM],
            "executable": MEMBER,
            "contract_sha256": SPEC.sha256,
            "corpus_sha256": corpus_digest(list(SPEC.cases("A"))),
            "capture_id": "simulated",
            "run_id": "simulated",
        },
    )
    _write(evidence.parent / "capture/capture.json", {"created_utc": "2026-10-29T20:00:00Z"})
    _write(
        evidence / "result.json",
        {"teardown_verified": True, "abort_reason": "", "monitoring": {"violations": []}},
    )
    rows = [
        {
            **SPEC.arm(ARM).identity(MEMBER),
            "case_id": c.case_id,
            "outcome": c.expected_outcome or "suggestion",
            "reason": "",
            "elapsed_ms": 1000,
            "details": {"child_observed": True, "priority_verified": True},
            "choice": c.oracle or next(iter(c.allowed_targets or c.allowed_workflows), None),
            "positive": c.positive.replace(c.canary, "") if c.canary else c.positive,
            "negative": c.negative.replace(c.canary, "") if c.canary else c.negative,
            "monitor_kind": "host",
            "phase": "cold" if i == 0 else "warm",
        }
        for i, c in enumerate(SPEC.cases("A"))
    ]
    for name, values in (
        ("records.jsonl", rows),
        ("telemetry.jsonl", []),
        (
            "lifecycle-probes.jsonl",
            [
                {"arm": ARM, "probe": p, "stopped_as_intended": True, "teardown_verified": True}
                for p in ("timeout", "cancel")
            ],
        ),
        (
            "arm-integrity.jsonl",
            [{"arm": ARM, "phase": p, "problems": []} for p in ("before", "after")],
        ),
    ):
        (evidence / name).write_text("\n".join(json.dumps(r) for r in values), encoding="utf-8")
    d12a_result = {"members": {MEMBER: {"verdict": "PASS"}}}
    return evidence, rows, d12a_result


@pytest.mark.parametrize(
    "mutation", [None, "duplicate", "unknown", "comparator", "sampling", "missing"]
)
def test_contract_stage_a_report_uses_frozen_cases_and_judge(tmp_path, monkeypatch, mutation):
    from tools.qualification.ai111.stage_a_contract import build_contract_report

    evidence, rows, compatible = _stage_a_world(tmp_path, monkeypatch)
    if mutation == "duplicate":
        rows[-1] = rows[0]
    if mutation == "unknown":
        rows[0]["case_id"] = "unknown"
    if mutation == "comparator":
        rows[0]["model_sha256"] = SPEC.arm(ARMS[1]).model.sha256
    if mutation == "sampling":
        rows[0]["sampling_profile"] = "qwen_frozen"
    if mutation == "missing":
        rows.pop()
    (evidence / "records.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    result = build_contract_report(evidence, SPEC, compatible, {}, {})
    if mutation is None:
        assert result["attribution_problems"] == []
        assert result["models"][ARM]["judgement"]["recommendation"] == "ADVANCE"
    else:
        assert result["attribution_problems"]
        assert result["models"][ARM]["judgement"]["recommendation"] == "INCONCLUSIVE"
