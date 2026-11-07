"""Mode, plan, authorization, readiness and physical-gate contracts of the golden-path suite (PR-TEST-DESKTOP-830).

Pure logic over injected probes: no display, no model runtime, no GPU, no network.
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tools.operator_journey import cli
from tools.operator_journey.evidence import HOLD, NO_GO, PASS, JourneyEvidence
from tools.operator_journey.golden import definitions
from tools.operator_journey.golden.host import HostProbes
from tools.operator_journey.golden.modes import ModeRefusal, validate_combination
from tools.operator_journey.golden.physical import (
    ResourceMonitor,
    classify_job_failure,
    confirmation_phrase,
    run_physical,
)
from tools.operator_journey.golden.plan import (
    build_plan,
    environment_diffs,
    plan_digest,
    shape_problems,
)
from tools.operator_journey.golden.readiness import ReadinessContext, evaluate_readiness
from tools.operator_journey.golden.suite import redact

LIMITS = {
    "max_jobs": 3,
    "max_artifacts": 4,
    "max_width": 1024,
    "max_height": 1024,
    "max_steps": 30,
    "max_frames": 33,
    "timeout_seconds": 900,
    "min_available_ram_gb": 8,
    "max_commit_gb": 60,
    "max_vram_used_mib": 3000,
    "min_free_disk_gb": 5,
}
GPU = {
    "name": "Test GPU",
    "driver": "1.0",
    "total_mib": 12000.0,
    "used_mib": 800.0,
    "free_mib": 11000.0,
    "uuid": "GPU-1",
}
MEM = {"available_gb": 30.0, "total_gb": 64.0, "commit_used_gb": 20.0, "commit_limit_gb": 100.0}


def make_probes(tmp_path: Path, **over: Any) -> HostProbes:
    values: dict[str, Any] = {
        "repo_sha": lambda: "a" * 40,
        "gpu": lambda: dict(GPU),
        "memory": lambda: dict(MEM),
        "disk_free_gb": lambda _p: 500.0,
        "endpoint": lambda _u, _k: {"state": "healthy", "busy_jobs": 0},
        "processes": lambda: [],
        "file_sha256": lambda p: "sha:" + Path(p).name,
        "python": lambda: "3.14.2",
        "hostname": lambda: "testhost",
        "os_name": lambda: "TestOS 1",
    }
    values.update(over)
    return HostProbes(**values)


@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    path = tmp_path / "model.safetensors"
    path.write_bytes(b"model")
    return path


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "ref.png"
    path.write_bytes(b"png")
    return path


def targets(model_file: Path, source_file: Path) -> dict[str, Any]:
    return {
        "image": {
            "runtime": {
                "kind": "forge",
                "ownership": "external",
                "base_url": "http://127.0.0.1:7860",
                "identity": "forge_webui@d70373ebcf1a",
            },
            "model": {
                "name": "m.safetensors",
                "path": str(model_file),
                "sha256": "sha:model.safetensors",
            },
            "settings": {"width": 512, "height": 512, "steps": 8, "seed": 1},
            "job_count": 1,
            "expected_artifacts": 1,
        },
        "video": {
            "runtime": {
                "kind": "comfy",
                "ownership": "managed",
                "base_url": "http://127.0.0.1:8188",
                "identity": "comfyui v0.38.0 0.38.0",
            },
            "workflow": {"id": "wan22_ti2v_5b_i2v_v1", "version": "1.3.0"},
            "source_assets": [{"path": str(source_file), "sha256": "sha:ref.png"}],
            "settings": {"frames": 9, "width": 480, "height": 480},
            "job_count": 1,
            "expected_artifacts": 1,
        },
    }


def ctx_for(probes: HostProbes, **over: Any) -> ReadinessContext:
    base = {
        "probes": probes,
        "workflow_info": lambda _i, _v: ("approved", ("--disable-pinned-memory",)),
        "comfy_launch": lambda: {
            "command": ["python", "main.py", "--disable-pinned-memory"],
            "environment_command": [],
            "saved_command": ["python"],
            "contract_problems": [],
            "identity": "comfyui v0.38.0 0.38.0",
        },
        "forge_identity": lambda: "forge_webui@d70373ebcf1a",
    }
    base.update(over)
    return ReadinessContext(**base)


def frozen(tmp_path, model_file, source_file, probes=None, journeys=("image",)):
    probes = probes or make_probes(tmp_path)
    all_targets = targets(model_file, source_file)
    plan = build_plan(
        targets={k: all_targets[k] for k in journeys},
        limits=dict(LIMITS),
        evidence_dir=str(tmp_path),
        probes=probes,
    )
    return plan, probes


def authorize(plan: dict[str, Any], journeys=("image",), *, hours: float = 4) -> dict[str, Any]:
    plan = deepcopy(plan)
    plan["authorization"] = {
        "state": "approved",
        "approved_by": "owner",
        "plan_digest": plan["digest"],
        "journeys": list(journeys),
        "expires_at": (datetime.now(UTC) + timedelta(hours=hours)).isoformat(),
    }
    return plan


def gate(report: dict[str, Any], gate_id: str) -> dict[str, str]:
    return next(g for g in report["gates"] if g["id"] == gate_id)


# --- 1. CLI defaults and invalid combinations -------------------------------------------------------------------


def test_defaults_are_simulated_tk_and_all_journeys() -> None:
    args = cli.build_parser().parse_args(["--suite", "golden-paths"])
    assert (args.mode, args.desktop_driver, args.golden_journey, args.plan) == (
        "simulated",
        "tk",
        "all",
        None,
    )


@pytest.mark.parametrize(
    ("mode", "driver", "plan", "env", "message"),
    [
        ("physical", "windows", None, {}, "requires --plan"),
        ("readiness", "tk", None, {}, "requires --plan"),
        ("simulated", "tk", "p.json", {}, "only valid with"),
        ("physical", "tk", "p.json", {}, "visible Windows desktop driver"),
        ("physical", "windows", "p.json", {"CI": "true"}, "never used in CI"),
        ("physical", "tk", "p.json", {"CI": "true"}, "refused in CI"),
        ("simulated", "windows", None, {"GITHUB_ACTIONS": "true"}, "never used in CI"),
        ("bogus", "tk", None, {}, "unknown mode"),
    ],
)
def test_invalid_combinations_are_refused_before_anything_starts(
    mode, driver, plan, env, message, monkeypatch
) -> None:
    # Isolate the combination rules from the "this process is pytest" guard, which has its own test below.
    monkeypatch.setattr(
        "tools.operator_journey.golden.modes.running_under_pytest", lambda *_a, **_k: False
    )
    with pytest.raises(ModeRefusal, match=message):
        validate_combination(mode=mode, driver=driver, plan=plan, env=env)


def test_physical_mode_is_refused_under_pytest_discovery() -> None:
    # This very process is pytest: PYTEST_CURRENT_TEST / the pytest module make physical execution impossible.
    with pytest.raises(ModeRefusal, match="pytest"):
        validate_combination(mode="physical", driver="windows", plan="p.json", env={})


def test_cli_refuses_real_backend_options_with_the_suite() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--suite", "golden-paths", "--real-backend"])
    with pytest.raises(SystemExit):
        cli.main(["--suite", "golden-paths", "--webui-url", "http://127.0.0.1:7860"])
    with pytest.raises(SystemExit):
        cli.main(["--plan", "x.json", "learning-lora-strength"])  # golden options need the suite


def test_cli_returns_a_refusal_code_for_physical_without_a_plan(capsys) -> None:
    assert cli.main(["--suite", "golden-paths", "--mode", "physical"]) == 4
    assert "requires --plan" in capsys.readouterr().err


def test_journey_definitions_cover_the_three_products() -> None:
    assert [j.id for j in definitions.select("all")] == ["IMG-01", "VID-01", "LRN-01"]
    assert all(len(j.steps) >= 12 and j.physical_acceptance for j in definitions.select("all"))


# --- plan, digest, authorization ---------------------------------------------------------------------------------


def test_plan_digest_is_stable_and_detects_any_edit(tmp_path, model_file, source_file) -> None:
    plan, _ = frozen(tmp_path, model_file, source_file)
    assert plan["digest"] == plan_digest(plan) and not shape_problems(plan)
    edited = deepcopy(plan)
    edited["targets"]["image"]["settings"]["steps"] = 9
    assert shape_problems(edited) and "edited after freezing" in shape_problems(edited)[0]
    authorized = authorize(plan)
    assert plan_digest(authorized) == plan["digest"]  # authorization is outside the digest


def test_plan_without_explicit_limits_or_identity_is_invalid(
    tmp_path, model_file, source_file
) -> None:
    probes = make_probes(tmp_path)
    t = targets(model_file, source_file)["image"]
    t["model"].pop("sha256")
    plan = build_plan(
        targets={"image": t}, limits={"max_jobs": 1}, evidence_dir=str(tmp_path), probes=probes
    )
    problems = " ".join(shape_problems(plan))
    assert "limits missing" in problems and "SHA-256 identity" in problems


def test_settings_over_the_plan_limits_are_invalid(tmp_path, model_file, source_file) -> None:
    t = targets(model_file, source_file)["image"]
    t["settings"]["steps"] = 99
    plan = build_plan(
        targets={"image": t},
        limits=dict(LIMITS),
        evidence_dir=str(tmp_path),
        probes=make_probes(tmp_path),
    )
    assert any("steps 99 exceeds max_steps" in p for p in shape_problems(plan))


# --- 15-17 readiness ---------------------------------------------------------------------------------------------


def test_readiness_passes_when_everything_matches_and_starts_nothing(
    tmp_path, model_file, source_file, monkeypatch
) -> None:
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("readiness must not start a process")
    )
    plan, probes = frozen(tmp_path, model_file, source_file, journeys=("image", "video"))
    plan["targets"]["video"]["runtime"]["ownership"] = "managed"
    plan["digest"] = plan_digest(plan)
    probes2 = make_probes(
        tmp_path,
        endpoint=lambda _u, k: {"state": "free" if k == "comfy" else "healthy", "busy_jobs": 0},
    )
    plan["environment"] = build_plan(
        targets=plan["targets"], limits=plan["limits"], evidence_dir=str(tmp_path), probes=probes2
    )["environment"]
    plan["digest"] = plan_digest(plan)
    report = evaluate_readiness(plan, ctx_for(probes2))
    assert report["verdict"] == PASS, [g for g in report["gates"] if g["state"] != PASS]
    assert report["started_runtime"] is False and report["physical_run_authorized"] is False


def test_missing_model_file_is_a_hold(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    model_file.unlink()
    report = evaluate_readiness(plan, ctx_for(probes))
    assert (
        report["verdict"] == HOLD
        and "model_sha256" in gate(report, "environment_matches_plan")["detail"]
    )


def test_source_identity_mismatch_is_a_hold(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file, journeys=("video",))
    changed = make_probes(tmp_path, file_sha256=lambda p: "sha:CHANGED")
    diffs = environment_diffs(plan, changed)
    assert any("sources" in d for d in diffs)


def test_unqualified_workflow_is_no_go(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(
        tmp_path,
        model_file,
        source_file,
        journeys=("video",),
        probes=make_probes(tmp_path, endpoint=lambda _u, _k: {"state": "free", "busy_jobs": 0}),
    )
    ctx = ctx_for(probes, workflow_info=lambda _i, _v: ("experimental", ()))
    assert gate(evaluate_readiness(plan, ctx), "video:workflow_governance")["state"] == NO_GO


def test_wrong_managed_runtime_identity_and_missing_flags_are_reported(
    tmp_path, model_file, source_file
) -> None:
    probes = make_probes(tmp_path, endpoint=lambda _u, _k: {"state": "free", "busy_jobs": 0})
    plan, _ = frozen(tmp_path, model_file, source_file, journeys=("video",), probes=probes)
    launch = {
        "command": ["python", "main.py"],
        "environment_command": [],
        "saved_command": [],
        "contract_problems": ["runtime folder missing: X"],
        "identity": "comfyui v0.37.0 0.37.0",
    }
    report = evaluate_readiness(plan, ctx_for(probes, comfy_launch=lambda: launch))
    assert gate(report, "video:runtime_identity")["state"] == HOLD
    assert gate(report, "video:managed_install")["state"] == HOLD
    assert (
        gate(report, "video:launch_flags")["state"] == NO_GO
        and "--disable-pinned-memory" in gate(report, "video:launch_flags")["detail"]
    )
    assert report["verdict"] == NO_GO


def test_environment_override_of_the_launch_command_is_a_hold(
    tmp_path, model_file, source_file
) -> None:
    probes = make_probes(tmp_path, endpoint=lambda _u, _k: {"state": "free", "busy_jobs": 0})
    plan, _ = frozen(tmp_path, model_file, source_file, journeys=("video",), probes=probes)
    launch = {
        "command": ["python", "main.py", "--disable-pinned-memory"],
        "environment_command": ["other", "--disable-pinned-memory"],
        "saved_command": ["python"],
        "contract_problems": [],
        "identity": "comfyui v0.38.0 0.38.0",
    }
    assert (
        gate(
            evaluate_readiness(plan, ctx_for(probes, comfy_launch=lambda: launch)),
            "video:environment_override",
        )["state"]
        == HOLD
    )


# --- 10, 23 safety: ownership, competing generation, telemetry ---------------------------------------------------


def test_managed_plan_against_an_externally_served_endpoint_is_no_go_and_never_touches_it(
    tmp_path, model_file, source_file, monkeypatch
) -> None:
    killed: list[Any] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: killed.append(a))
    probes = make_probes(
        tmp_path,
        endpoint=lambda _u, _k: {"state": "healthy", "busy_jobs": 0},
        processes=lambda: [{"pid": 4242, "name": "python.exe", "cmdline": "webui"}],
    )
    plan, _ = frozen(tmp_path, model_file, source_file, journeys=("video",), probes=probes)
    report = evaluate_readiness(plan, ctx_for(probes))
    assert (
        gate(report, "video:ownership")["state"] == NO_GO
        and "never adopted" in gate(report, "video:ownership")["detail"]
    )
    assert gate(report, "existing_runtime_processes")["state"] == NO_GO
    assert killed == []  # no process was started, stopped or signalled


def test_competing_generation_gpu_pressure_and_missing_telemetry_are_no_go(
    tmp_path, model_file, source_file
) -> None:
    plan, _ = frozen(tmp_path, model_file, source_file)
    busy = make_probes(tmp_path, endpoint=lambda _u, _k: {"state": "healthy", "busy_jobs": 2})
    assert (
        gate(evaluate_readiness(plan, ctx_for(busy)), "image:no_competing_generation")["state"]
        == NO_GO
    )
    pressured = make_probes(tmp_path, gpu=lambda: {**GPU, "used_mib": 9000.0})
    assert gate(evaluate_readiness(plan, ctx_for(pressured)), "gpu_idle_vram")["state"] == NO_GO
    blind = make_probes(tmp_path, gpu=lambda: None)
    assert gate(evaluate_readiness(plan, ctx_for(blind)), "gpu_telemetry")["state"] == NO_GO
    low = make_probes(tmp_path, memory=lambda: {**MEM, "available_gb": 2.0})
    assert gate(evaluate_readiness(plan, ctx_for(low)), "host_available_ram")["state"] == NO_GO
    committed = make_probes(tmp_path, memory=lambda: {**MEM, "commit_used_gb": 99.0})
    assert gate(evaluate_readiness(plan, ctx_for(committed)), "system_commit")["state"] == NO_GO


# --- 18-20 physical gates ----------------------------------------------------------------------------------------


def run_gate(tmp_path, plan, probes, ctx, *, confirm=None, executor=None, journeys=("image",)):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, default=str), "utf-8")
    chosen = definitions.select("image") if journeys == ("image",) else definitions.select("all")
    return run_physical(
        path,
        journeys=chosen,
        evidence_root=tmp_path / "ev",
        confirm=confirm,
        ctx=ctx,
        executor=executor,
        probes=probes,
    )


def boom(*_a, **_k):
    raise AssertionError("the executor must not run")


def test_missing_authorization_is_a_hold_and_runs_nothing(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    verdict, run_dir = run_gate(
        tmp_path,
        plan,
        probes,
        ctx_for(probes),
        executor=boom,
        confirm=lambda _p: confirmation_phrase(plan),
    )
    assert verdict == HOLD and "not authorized" in (run_dir / "summary.md").read_text()
    assert (
        json.loads((run_dir / "evidence.json").read_text())["outcomes"]["physical_execution"]
        == "NOT RUN"
    )


def test_changed_plan_after_authorization_requires_renewal(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    approved = authorize(plan)
    approved["targets"]["image"]["settings"]["steps"] = (
        12  # edited after approval, digest not refrozen
    )
    verdict, _ = run_gate(
        tmp_path, approved, probes, ctx_for(probes), executor=boom, confirm=lambda _p: "x"
    )
    assert verdict == HOLD


def test_authorization_for_another_digest_or_expired_is_refused(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    other = authorize(plan)
    other["authorization"]["plan_digest"] = "0" * 64
    assert run_gate(tmp_path, other, probes, ctx_for(probes), executor=boom)[0] == HOLD
    expired = authorize(plan, hours=-1)
    assert run_gate(tmp_path, expired, probes, ctx_for(probes), executor=boom)[0] == HOLD


def test_environment_drift_since_freezing_is_a_hold(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    drifted = make_probes(tmp_path, repo_sha=lambda: "b" * 40)
    verdict, run_dir = run_gate(tmp_path, authorize(plan), drifted, ctx_for(drifted), executor=boom)
    assert verdict == HOLD and "renew authorization" in (run_dir / "summary.md").read_text()


def test_no_typed_confirmation_is_no_deliberate_launch(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    assert (
        run_gate(
            tmp_path,
            authorize(plan),
            probes,
            ctx_for(probes),
            executor=boom,
            confirm=lambda _p: "yes",
        )[0]
        == HOLD
    )
    assert (
        run_gate(tmp_path, authorize(plan), probes, ctx_for(probes), executor=boom, confirm=None)[0]
        == HOLD
    )


def test_authorized_matching_confirmed_plan_runs_once_with_three_outcomes(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    approved = authorize(plan)
    calls: list[str] = []

    def executor(journey, target, monitor, run_dir):
        calls.append(journey.id)
        ev = JourneyEvidence(journey_id=journey.id, backend_mode="physical")
        ev.observe("image_media", {"path": "x.png", "valid": True, "sha256": "ab"})
        return ev

    verdict, run_dir = run_gate(
        tmp_path,
        approved,
        probes,
        ctx_for(probes),
        executor=executor,
        confirm=lambda _p: confirmation_phrase(plan),
    )
    evidence = json.loads((run_dir / "evidence.json").read_text())
    assert calls == ["IMG-01"] and verdict == PASS
    assert evidence["outcomes"]["functional"] == PASS and evidence["outcomes"]["safety"] == PASS
    assert evidence["outcomes"]["visual_quality"] == "PENDING_OPERATOR_REVIEW"
    assert (run_dir / "resource_telemetry.jsonl").read_text().strip()
    for name in ("plan.json", "evidence.json", "summary.md", "actions.jsonl", "artifacts.json"):
        assert (run_dir / name).is_file(), name
    assert json.loads((run_dir / "artifacts.json").read_text())[0]["sha256"] == "ab"


# --- delegated launch: the owner's authorization may delegate the launch phrase to a named delegate ------------------


def delegate(plan: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    approved = authorize(plan)
    approved["authorization"]["launch"] = {
        "mode": "delegated",
        "delegate": "Claude Code session",
        "owner_instruction": "I authorize the run; I need you to run this.",
        **overrides,
    }
    return approved


def ok_executor(journey, target, monitor, run_dir):
    ev = JourneyEvidence(journey_id=journey.id, backend_mode="physical")
    ev.observe("image_media", {"path": "x.png", "valid": True, "sha256": "ab"})
    return ev


def run_delegated(tmp_path, plan, probes, phrase, executor):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, default=str), "utf-8")
    return run_physical(
        path,
        journeys=definitions.select("image"),
        evidence_root=tmp_path / "ev",
        ctx=ctx_for(probes),
        executor=executor,
        probes=probes,
        launch_phrase=phrase,
    )


def test_a_delegated_launch_runs_once_and_is_attributed(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    approved = delegate(plan)
    verdict, run_dir = run_delegated(
        tmp_path, approved, probes, confirmation_phrase(plan), ok_executor
    )
    launch = json.loads((run_dir / "evidence.json").read_text())["outcomes"]["launch"]
    assert verdict == PASS
    assert launch["method"] == "delegated" and launch["delegate"] == "Claude Code session"
    assert "authorize the run" in launch["owner_instruction"]
    marker = tmp_path / f"{plan['digest'][:12]}.delegated-launch.json"
    assert marker.is_file()
    # A second delegated launch of the same digest is refused and runs nothing.
    again, again_dir = run_delegated(tmp_path, approved, probes, confirmation_phrase(plan), boom)
    assert again == HOLD and "already launched" in (again_dir / "summary.md").read_text()


def test_a_typed_launch_is_recorded_as_typed(tmp_path, model_file, source_file) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    verdict, run_dir = run_gate(
        tmp_path,
        authorize(plan),
        probes,
        ctx_for(probes),
        executor=ok_executor,
        confirm=lambda _p: confirmation_phrase(plan),
    )
    assert verdict == PASS
    assert json.loads((run_dir / "evidence.json").read_text())["outcomes"]["launch"] == {
        "method": "typed"
    }


@pytest.mark.parametrize(
    ("overrides", "phrase_ok", "message"),
    [
        ({"mode": "typed"}, True, "does not delegate"),
        ({"delegate": " "}, True, "names no delegate"),
        ({"owner_instruction": ""}, True, "quotes no owner instruction"),
        ({}, False, "does not name this plan digest"),
    ],
)
def test_a_delegated_launch_without_a_complete_delegation_or_exact_phrase_is_a_hold(
    tmp_path, model_file, source_file, overrides, phrase_ok, message
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    phrase = confirmation_phrase(plan) if phrase_ok else "RUN 000000000000"
    verdict, run_dir = run_delegated(tmp_path, delegate(plan, **overrides), probes, phrase, boom)
    assert verdict == HOLD and message in (run_dir / "summary.md").read_text()
    assert not list(tmp_path.glob("*.delegated-launch.json"))


def test_a_phrase_cannot_launch_a_plan_that_did_not_delegate(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    verdict, _ = run_delegated(tmp_path, authorize(plan), probes, confirmation_phrase(plan), boom)
    assert verdict == HOLD


def test_delegation_does_not_bypass_expiry_digest_or_environment_gates(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file)
    expired = delegate(plan)
    expired["authorization"]["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert run_delegated(tmp_path, expired, probes, confirmation_phrase(plan), boom)[0] == HOLD
    drifted = make_probes(tmp_path, repo_sha=lambda: "b" * 40)
    assert (
        run_delegated(tmp_path, delegate(plan), drifted, confirmation_phrase(plan), boom)[0] == HOLD
    )
    assert not list(tmp_path.glob("*.delegated-launch.json"))


def test_the_launch_phrase_option_applies_only_to_physical_mode() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--suite", "golden-paths", "--launch-phrase", "RUN abc"])


# --- 21-22, 24 stop conditions and resource evidence --------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("CUDA error: device-side assert / device lost", "device_loss"),
        ("torch.cuda.OutOfMemoryError: CUDA out of memory", "oom"),
        ("Comfy history wait timed out after 900s", "timeout"),
        ("DispatchOutcomeUnknown: POST /prompt outcome unknown", "ambiguous_dispatch"),
        (None, None),
    ],
)
def test_stop_conditions_are_classified(error, expected) -> None:
    assert (
        classify_job_failure(
            {"error_message": error, "retry_attempts": 0, "return_to_queue_count": 0}
        )
        == expected
    )


def test_a_retry_or_requeue_is_treated_as_ambiguous_dispatch_and_never_repeated() -> None:
    assert (
        classify_job_failure({"error_message": None, "retry_attempts": 1}) == "ambiguous_dispatch"
    )
    assert (
        classify_job_failure({"error_message": None, "return_to_queue_count": 1})
        == "ambiguous_dispatch"
    )


def test_device_loss_stops_the_run_with_no_go_and_no_second_attempt(
    tmp_path, model_file, source_file
) -> None:
    plan, probes = frozen(tmp_path, model_file, source_file, journeys=("image", "video"))
    approved = authorize(plan, journeys=("image", "video"))
    calls: list[str] = []

    def executor(journey, target, monitor, run_dir):
        calls.append(journey.id)
        ev = JourneyEvidence(journey_id=journey.id, backend_mode="physical")
        ev.observe(
            "job_row",
            {"status": "failed", "error_message": "CUDA error: device lost", "retry_attempts": 0},
        )
        return ev

    ctx = ctx_for(probes, endpoint=None) if False else ctx_for(probes)
    verdict, run_dir = run_gate(
        tmp_path,
        approved,
        probes,
        ctx,
        executor=executor,
        confirm=lambda _p: confirmation_phrase(plan),
        journeys=("all",),
    )
    assert verdict in {NO_GO, HOLD}
    if verdict == NO_GO:
        assert calls == ["IMG-01"]  # the second journey never started
        assert (
            "never retried"
            in json.loads((run_dir / "evidence.json").read_text())["outcomes"]["reason"]
        )


def test_monitor_trips_on_vram_ram_commit_timeout_and_blind_telemetry(tmp_path) -> None:
    clock = {"t": 0.0}
    cases = {
        "VRAM": {"gpu": lambda: {**GPU, "used_mib": 5000.0}},
        "available RAM": {"memory": lambda: {**MEM, "available_gb": 1.0}},
        "commit": {"memory": lambda: {**MEM, "commit_used_gb": 70.0}},
        "unavailable": {"gpu": lambda: None},
    }
    for needle, over in cases.items():
        monitor = ResourceMonitor(
            LIMITS,
            make_probes(tmp_path, **over),
            tmp_path / f"{needle[:3]}.jsonl",
            clock=lambda: clock["t"],
        )
        monitor.sample_once()
        assert monitor.tripped and needle in monitor.tripped
    ok = ResourceMonitor(
        LIMITS, make_probes(tmp_path), tmp_path / "ok.jsonl", clock=lambda: clock["t"]
    )
    ok.sample_once()
    assert ok.tripped is None and ok.peaks["vram_used_mib"] == 800.0
    clock["t"] = 901.0
    ok.sample_once()
    assert "timeout" in ok.tripped
    lines = (tmp_path / "ok.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["tripped"].startswith("execution exceeded")


# --- 25 reports --------------------------------------------------------------------------------------------------


def test_reports_are_redacted_and_bounded(monkeypatch) -> None:
    home = str(Path.home())
    text = f"path {home}\\secret and token=abc123 api_key: zzz Bearer eyJhbGci.x"
    cleaned = redact(text)
    assert (
        home not in cleaned
        and "abc123" not in cleaned
        and "zzz" not in cleaned
        and "eyJhbGci" not in cleaned
    )
    assert len(redact("x" * 100_000, limit=1000)) < 1100


def test_readiness_command_writes_a_complete_report_without_starting_anything(
    tmp_path, model_file, source_file, monkeypatch
) -> None:
    from tools.operator_journey.golden.suite import run_readiness

    monkeypatch.setattr("tools.operator_journey.golden.suite.repo_sha", lambda: "a" * 40)
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("readiness must not start a process")
    )
    plan, probes = frozen(tmp_path, model_file, source_file)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, default=str), "utf-8")
    verdict, run_dir = run_readiness(path, evidence_root=tmp_path / "ev", ctx=ctx_for(probes))
    assert verdict == PASS
    report = json.loads((run_dir / "evidence.json").read_text())["readiness"]
    assert report["started_runtime"] is False and report["physical_run_authorized"] is False
    assert "No runtime was started" in (run_dir / "summary.md").read_text()
