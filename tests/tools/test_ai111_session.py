"""PR-AI-111 physical session machinery driven end to end by a fake runtime (no model, GPU or network).

The "runtime" is a tiny Python script launched through the real ``AiAssistService`` and ``run_bounded``, so containment,
priority read-back, memory observation, incremental records, teardown verification and scoring are all exercised for real.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ai_assist.manifests import ModelRegistry  # noqa: E402
from tests.ai_assist.conftest import (  # noqa: E402
    FAKE_CHILD,
    FILES,
    MODEL_BYTES,
    build_archive,
    make_entry,
    roomy,
    sha,
)
from tools.qualification.ai111 import physical  # noqa: E402
from tools.qualification.ai111 import plan as plan_module  # noqa: E402
from tools.qualification.ai111.corpus import Case  # noqa: E402

AUTHORIZATION = "Owner: run Stage A for the fake arm against plan <digest>."


def _case(i: int, mode: str = "ok") -> Case:
    return Case(
        case_id=f"t-{i:03d}",
        stratum="rewrite_tokens",
        kind="prompt_rewrite",
        positive=f"a barn <lora:barn:0.8> [[season]]\nTEST_MODE:{mode}\nTEST_SLEEP:0.6",
        negative="blurry",
        target_policy_id="sdxl",
    )


@pytest.fixture
def world(tmp_path: Path):
    archive_bytes = build_archive(FILES)
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(archive_bytes)
    model = tmp_path / "model.gguf"
    model.write_bytes(MODEL_BYTES)
    entry = make_entry(qualified=False)
    child = tmp_path / "fake_child.py"
    child.write_text(FAKE_CHILD, encoding="utf-8")
    plan = copy.deepcopy(plan_module.frozen_plan())
    plan["runtime_intent"].update(
        tag="b0000",
        asset="fake.zip",
        bytes=len(archive_bytes),
        sha256=sha(archive_bytes),
        compute="cpu",
    )
    plan["limits"]["timeout_seconds"] = 30.0
    plan["safety"].update(quiet_host_required=False, teardown_wait_seconds=10.0)
    paths = physical.SessionPaths(tmp_path / "evidence", archive, {entry.model_id: model})
    return {
        "plan": plan,
        "paths": paths,
        "registry": ModelRegistry((entry,)),
        "entry": entry,
        "child": child,
        "model": model,
        "archive": archive,
    }


def _factory(world):
    return lambda _exe, argv: [sys.executable, str(world["child"]), *argv]


def _run(world, cases, *, stage="A", authorization=AUTHORIZATION, busy=None, arms=None, **kwargs):
    return physical.run_session(
        plan=world["plan"],
        paths=world["paths"],
        stage=stage,
        arms=arms or ["B0_identity", "B1_engine", world["entry"].model_id],
        cases=cases,
        authorization_text=authorization,
        registry=world["registry"],
        command_factory=_factory(world),
        busy_provider=(lambda: busy or []),
        memory_probe=kwargs.pop("memory_probe", roomy),
        **kwargs,
    )


def test_a_session_runs_scores_and_records_everything_incrementally(world) -> None:
    cases = [_case(i) for i in range(4)]
    result = _run(world, cases)
    evidence = world["paths"].evidence_root / "physical-A"
    manifest = json.loads((evidence / "execution-manifest.json").read_text(encoding="utf-8"))
    assert manifest["owner_authorization"] == AUTHORIZATION and manifest[
        "plan_sha256"
    ] == plan_module.digest(world["plan"])
    rows = [
        json.loads(line)
        for line in (evidence / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 4 * 3 and {r["arm"] for r in rows} == {
        "B0_identity",
        "B1_engine",
        world["entry"].model_id,
    }
    model_rows = [r for r in rows if r["arm"] == world["entry"].model_id]
    assert all(
        r["outcome"] == "suggestion" and r["details"]["child_observed"] is True for r in model_rows
    )
    assert all("egress_connections" in r["details"] for r in model_rows)
    derived = json.loads((evidence / "derived-runtime-build.json").read_text(encoding="utf-8"))
    assert (
        derived["files"] == {name: sha(data) for name, data in FILES.items()}
        and derived["executable"] == "llama-cli.exe"
    )
    assert (evidence / "telemetry.jsonl").exists() and (evidence / "summary.json").exists()
    assert result["teardown_verified"] is True and result["abort_reason"] == ""
    assert result["verdict"] == "INCONCLUSIVE", (
        "four cases and no preference ratings can never be a PASS"
    )
    assert "enough_cases_for_rates" in result["arm_verdicts"][world["entry"].model_id]["unmet"]
    assert result["egress_connections_observed"] == 0


def test_blind_pairs_hide_the_arms_and_pair_the_model_with_the_engine_baseline(world) -> None:
    _run(world, [_case(i) for i in range(6)])
    evidence = world["paths"].evidence_root / "physical-A"
    manifest = json.loads((evidence / "blind-pairs-manifest.json").read_text(encoding="utf-8"))
    pairs = manifest[world["entry"].model_id]
    assert len(pairs) == 6 and {p["left"] for p in pairs} | {p["right"] for p in pairs} == {
        world["entry"].model_id,
        "B1_engine",
    }
    views = list(evidence.glob("blinded-view-*.json"))
    assert views
    text = views[0].read_text(encoding="utf-8")
    assert "B1_engine" not in text and world["entry"].model_id not in text


def test_a_stage_is_claimed_exclusively_and_survives_a_second_attempt(world) -> None:
    _run(world, [_case(0)])
    before = (world["paths"].evidence_root / "physical-A" / "result.json").read_text(
        encoding="utf-8"
    )
    with pytest.raises(FileExistsError):
        _run(world, [_case(0)])
    assert (world["paths"].evidence_root / "physical-A" / "result.json").read_text(
        encoding="utf-8"
    ) == before


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda w: w["model"].write_bytes(MODEL_BYTES + b"!"),
            "does not match the frozen size/SHA-256",
        ),
        (lambda w: w["model"].unlink(), "missing model file"),
        (lambda w: w["archive"].write_bytes(b"not the archive"), "runtime archive does not match"),
    ],
)
def test_preflight_refuses_before_anything_is_imported_or_run(world, break_it, expected) -> None:
    break_it(world)
    result = _run(world, [_case(0)])
    evidence = world["paths"].evidence_root / "physical-A"
    assert result["verdict"] == "INCONCLUSIVE" and any(expected in p for p in result["refused"])
    assert (evidence / "preflight-refusal.json").exists()
    assert (
        not (evidence / "records.jsonl").exists()
        and not (evidence / "ai-root" / "runtimes").exists()
    )


def test_a_missing_authorization_statement_or_a_busy_host_refuses(world) -> None:
    assert any("authorization" in p for p in _run(world, [_case(0)], authorization="  ")["refused"])
    world["paths"] = physical.SessionPaths(
        world["paths"].evidence_root, world["archive"], world["paths"].model_files
    )
    world["plan"]["safety"]["quiet_host_required"] = True
    busy = _run(world, [_case(0)], stage="B", busy=["busy host: pytest"])
    assert busy["refused"] == ["busy host: pytest"]


def test_strict_offline_needs_the_operator_attestation(world) -> None:
    refused = _run(world, [_case(0)], strict_offline=True)
    assert any("attestation" in p for p in refused["refused"])
    allowed = _run(
        world,
        [_case(0)],
        stage="B",
        strict_offline=True,
        attest="Windows Firewall outbound block on llama-cli.exe",
    )
    assert allowed.get("refused") is None and allowed["teardown_verified"] is True


def test_a_child_tree_that_outlives_its_request_ends_the_session_as_unverified(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(physical, "_tree_gone", lambda _marker, _wait: False)
    result = _run(world, [_case(0), _case(1)])
    assert result["teardown_verified"] is False and "still present" in result["abort_reason"]
    assert result["verdict"] == "INCONCLUSIVE"
    rows = (
        (world["paths"].evidence_root / "physical-A" / "records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert sum(1 for line in rows if json.loads(line)["arm"] == world["entry"].model_id) == 1, (
        "stopped after the first request"
    )


def test_repeated_infrastructure_failures_abort_instead_of_burning_the_corpus(world) -> None:
    cases = [_case(i, mode="exit3") for i in range(8)]
    result = _run(world, cases)
    assert (
        "consecutive infrastructure failures" in result["abort_reason"]
        and result["verdict"] == "INCONCLUSIVE"
    )
    rows = [
        json.loads(line)
        for line in (world["paths"].evidence_root / "physical-A" / "records.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert sum(1 for r in rows if r["arm"] == world["entry"].model_id) == 3


def test_the_runtime_archive_is_pinned_by_digest_before_any_file_is_trusted(world) -> None:
    intent = copy.deepcopy(world["plan"]["runtime_intent"])
    build = physical.derive_runtime_build(world["archive"], intent)
    assert (
        build.qualified is False
        and set(build.files) == set(FILES)
        and build.build_id == "b0000-cpu"
    )
    intent["sha256"] = "0" * 64
    with pytest.raises(Exception, match="runtime_archive_mismatch"):
        physical.derive_runtime_build(world["archive"], intent)


def test_quiet_host_detection_names_what_is_running() -> None:
    rows = [
        (1, "python run_pr_gate.py --full"),
        (2, "C:/ComfyUI/main.py"),
        (3, "notepad"),
        (physical.os.getpid(), "pytest self"),
    ]
    found = physical.quiet_host_refusals(lambda: rows)
    assert (
        found == ["busy host: comfyui", "busy host: run_pr_gate"]
        and "busy host: pytest" not in found
    )


def test_injected_memory_probe_reaches_admission_and_session_sampling(world):
    calls = []

    def probe():
        calls.append(True)
        return roomy()

    result = _run(world, [_case(0)], memory_probe=probe)
    evidence = world["paths"].evidence_root / "physical-A"
    rows = [
        json.loads(line)
        for line in (evidence / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    model = next(row for row in rows if row["arm"] == world["entry"].model_id)
    assert model["outcome"] == "suggestion" and result["abort_reason"] == ""
    samples = [
        json.loads(line)
        for line in (evidence / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert samples and all(row["available_gib"] == 24.0 for row in samples)
    assert len(calls) >= 2


def test_unreadable_injected_memory_still_refuses_model_requests(world):
    result = _run(world, [_case(i) for i in range(4)], memory_probe=lambda: None)
    evidence = world["paths"].evidence_root / "physical-A"
    rows = [
        json.loads(line)
        for line in (evidence / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    model_rows = [row for row in rows if row["arm"] == world["entry"].model_id]
    assert len(model_rows) == 3
    assert all(
        row["outcome"] == "resource_insufficient" and row["reason"] == "memory_unreadable"
        for row in model_rows
    )
    assert result["abort_reason"] == "3 consecutive infrastructure failures"
