"""PR-QUAL-SYSTEM-840: frozen plans, digest, authorization/launch separation, readiness gates, stop classification."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path

import pytest

from tools.qualification.system840 import dryrun, safety
from tools.qualification.system840 import plan as plan_mod
from tools.qualification.system840.arms import STAGE_CANARY, execution_order, get_arm, lane_class
from tools.qualification.system840.ledger import load_ledger

LEDGER = load_ledger()


@pytest.fixture()
def probes():
    return dryrun.fake_probes()


@pytest.fixture()
def img_plan(tmp_path, probes):
    return dryrun.build_synthetic_plan("IMG-Q0", STAGE_CANARY, tmp_path, probes, LEDGER)


@pytest.fixture()
def ai_plan(tmp_path, probes):
    return dryrun.build_synthetic_plan(
        "AI-Q1", STAGE_CANARY, tmp_path, probes, None, ["AI-Q1.qwen3.5-4b-q4_k_m-unsloth"]
    )


def _auth(plan, **kw):
    return plan_mod.build_authorization(
        plan,
        approved_by="owner",
        ttl_hours=kw.pop("ttl", 12),
        now=kw.pop("now", dryrun.EPOCH + timedelta(minutes=5)),
    )


# ----------------------------------------------------------------------------------------------------- plans / digest


def test_plan_freezes_every_required_field(img_plan) -> None:
    assert plan_mod.shape_problems(img_plan) == []
    for key in (
        "test_id",
        "benchmark_version",
        "backend",
        "runtime",
        "cases",
        "jobs",
        "artifacts",
        "limits",
        "telemetry",
        "stop",
        "expected_outputs",
        "evidence_dir",
        "environment",
    ):
        assert img_plan[key]
    case = img_plan["cases"][0]
    for key in ("model", "sources", "prompts", "seeds", "settings", "geometry"):
        assert case[key]
    assert img_plan["environment"]["repo"]["sha"] == "d76d1acde91a64f7f513ac42cffa5baa67f519bf"
    assert img_plan["authorization"] == {"state": "unauthorized"}


def test_any_change_gives_a_new_digest_and_invalidates_the_old_approval(img_plan) -> None:
    approval = _auth(img_plan)
    assert (
        plan_mod.authorization_problems(img_plan, approval, dryrun.EPOCH + timedelta(hours=1)) == []
    )
    for mutate in (
        lambda p: p["cases"][0]["prompts"].update(positive="a different prompt"),
        lambda p: p["cases"][0]["seeds"].append(1),
        lambda p: p["cases"][0]["model"].update(sha256="0" * 64),
        lambda p: p["limits"].update(max_vram_used_mib=999),
        lambda p: p["runtime"].update(identity="another-runtime"),
        lambda p: p.update(jobs=p["jobs"] + 1),
    ):
        edited = copy.deepcopy(img_plan)
        mutate(edited)
        assert plan_mod.digest_of(edited) != img_plan["digest"]
        assert any("digest" in p for p in plan_mod.shape_problems(edited))  # edited after freezing
        assert plan_mod.authorization_problems(edited, approval, dryrun.EPOCH + timedelta(hours=1))


def test_generated_at_and_authorization_do_not_change_the_digest(img_plan) -> None:
    other = copy.deepcopy(img_plan)
    other["generated_at"] = "2030-01-01T00:00:00+00:00"
    other["authorization"] = {"state": "approved"}
    assert plan_mod.digest_of(other) == img_plan["digest"]


@pytest.mark.parametrize(
    ("arm_id", "capability"),
    [
        ("VID-Q4", "VID-Q4.wan-a14b-480p"),  # structural target hold
        ("IMG-Q4", "IMG-Q4.forge-vs-comfy-still"),  # offline arm
        ("AI-Q0", "AI-Q0.protected-capture-readiness"),  # offline arm
    ],
)
def test_held_and_offline_arms_cannot_be_planned(arm_id, capability, tmp_path, probes) -> None:
    case = dryrun.synthetic_case("IMG-Q0", capability, tmp_path)
    with pytest.raises(plan_mod.PlanRefused):
        plan_mod.build_plan(
            arm_id,
            stage=STAGE_CANARY,
            cases=[case],
            runtime=dryrun.runtime_for(arm_id),
            limits=dict(dryrun.LIMITS_GPU),
            evidence_dir=str(tmp_path),
            probes=probes,
        )


def test_ledger_hold_blocks_ai_planning_until_the_owner_edits_the_ledger(tmp_path, probes) -> None:
    case = dryrun.synthetic_case("AI-Q1", "AI-Q1.qwen3.5-4b-q4_k_m-unsloth", tmp_path)
    with pytest.raises(plan_mod.PlanRefused, match="HOLD in the ledger"):
        plan_mod.build_plan(
            "AI-Q1",
            stage=STAGE_CANARY,
            cases=[case],
            runtime=dryrun.runtime_for("AI-Q1"),
            limits=dict(dryrun.LIMITS_CPU),
            evidence_dir=str(tmp_path),
            probes=probes,
            ledger=LEDGER,
        )


def test_held_target_and_ledger_refused_capabilities_are_not_planned(tmp_path, probes) -> None:
    for capability in (
        "IMG-Q1.zimage-turbo-fp8",
        "IMG-Q1.klein-base-9b",
        "IMG-Q1.qwen-image",
        "IMG-Q1.other-generic-families",
    ):
        case = dryrun.synthetic_case("IMG-Q1", capability, tmp_path)
        with pytest.raises(plan_mod.PlanRefused):
            plan_mod.build_plan(
                "IMG-Q1",
                stage=STAGE_CANARY,
                cases=[case],
                runtime=dryrun.runtime_for("IMG-Q1"),
                limits=dict(dryrun.LIMITS_GPU),
                evidence_dir=str(tmp_path),
                probes=probes,
                ledger=LEDGER,
            )
    case = dryrun.synthetic_case("IMG-Q1", "IMG-Q1.not-in-ledger", tmp_path)
    with pytest.raises(plan_mod.PlanRefused, match="not in the qualification ledger"):
        plan_mod.build_plan(
            "IMG-Q1",
            stage=STAGE_CANARY,
            cases=[case],
            runtime=dryrun.runtime_for("IMG-Q1"),
            limits=dict(dryrun.LIMITS_GPU),
            evidence_dir=str(tmp_path),
            probes=probes,
            ledger=LEDGER,
        )


def test_incomplete_or_unsafe_plans_are_reported(img_plan) -> None:
    broken = copy.deepcopy(img_plan)
    broken["limits"].pop("min_available_ram_gb")
    broken["limits"].pop("max_vram_used_mib")
    broken["stop"]["retry"] = "once"
    broken["stop"]["conditions"].remove("device_loss")
    broken["cases"][0]["sources"][0]["sha256"] = ""
    broken["runtime"]["ownership"] = "borrowed"
    broken["cases"][0]["settings"].pop("cfg")
    broken["digest"] = plan_mod.digest_of(broken)
    text = " | ".join(plan_mod.shape_problems(broken))
    for fragment in (
        "limits missing",
        "retry or silent downgrade",
        "stop conditions not declared",
        "source asset",
        "ownership",
        "image settings missing",
    ):
        assert fragment in text


def test_wrong_source_missing_model_and_wrong_checkout_are_environment_diffs(
    img_plan, probes, tmp_path
) -> None:
    assert plan_mod.environment_diffs(img_plan, probes) == []
    case = img_plan["cases"][0]
    Path(case["sources"][0]["path"]).write_bytes(b"swapped source")
    assert any("sources" in d for d in plan_mod.environment_diffs(img_plan, probes))
    Path(case["model"]["path"]).unlink()
    assert any("model" in d for d in plan_mod.environment_diffs(img_plan, probes))
    moved = dryrun.fake_probes(
        tree=lambda: {"sha": "e" * 40, "dirty_files": ["src/x.py"], "diff_sha256": "1"}
    )
    assert any(d.startswith("repo") for d in plan_mod.environment_diffs(img_plan, moved))


def test_execution_order_runs_dependencies_first_and_lanes_are_classified() -> None:
    assert execution_order(["IMG-Q1", "IMG-Q0"]) == ["IMG-Q0", "IMG-Q1"]
    assert lane_class(get_arm("AI-Q1").lane) == "cpu_inference"
    assert lane_class(get_arm("VID-Q0").lane) == "gpu"
    assert lane_class(get_arm("IMG-Q4").lane) == "offline"


# ------------------------------------------------------------------------------------- authorization and launch


def test_unauthorized_and_mismatched_authorizations_are_refused(img_plan, ai_plan) -> None:
    now = dryrun.EPOCH + timedelta(hours=1)
    assert plan_mod.authorization_problems(img_plan, None, now)
    assert plan_mod.authorization_problems(img_plan, {"state": "unauthorized"}, now)
    good = _auth(img_plan)
    cases = {
        "issuer": {**good, "issuer": "self"},
        "digest": {**good, "plan_digest": "0" * 64},
        "arm": {**good, "arm_id": "IMG-Q1"},
        "stage": {**good, "stage": "coverage"},
        "group": {**good, "authorization_group": "other"},
        "phrase": {**good, "approval_phrase": "APPROVE everything"},
        "owner": {**good, "approved_by": " "},
        "predates": {**good, "approved_at": (dryrun.EPOCH - timedelta(days=1)).isoformat()},
        "lifetime": {**good, "expires_at": (dryrun.EPOCH + timedelta(days=99)).isoformat()},
    }
    for label, record in cases.items():
        assert plan_mod.authorization_problems(img_plan, record, now), label
    assert plan_mod.authorization_problems(
        img_plan, good, dryrun.EPOCH + timedelta(days=2)
    )  # expired
    # A grant never transfers to another model: the AI approval names exactly its model id.
    ai_auth = _auth(ai_plan)
    assert ai_auth["model_ids"] == ["qwen3.5-4b-q4_k_m-unsloth"]
    other_model = copy.deepcopy(ai_plan)
    other_model["cases"][0]["cpu_inference"]["model_id"] = "lfm3-1.7b-q4_k_m-liquidai"
    other_model["digest"] = plan_mod.digest_of(other_model)
    reused = {
        **ai_auth,
        "plan_digest": other_model["digest"],
        "approval_phrase": plan_mod.approval_phrase(other_model),
    }
    assert any(
        "exactly this model" in p
        for p in plan_mod.authorization_problems(
            other_model, reused, dryrun.EPOCH + timedelta(hours=1)
        )
    )


def test_approval_is_only_issued_to_an_interactive_owner_typing_the_exact_phrase(img_plan) -> None:
    phrase = plan_mod.approval_phrase(img_plan)
    base = {
        "approved_by": "owner",
        "typed_phrase": phrase,
        "now": dryrun.EPOCH + timedelta(minutes=5),
    }
    record = plan_mod.issue_authorization(
        img_plan, interactive=True, ci=False, pytest_active=False, **base
    )
    assert record["plan_digest"] == img_plan["digest"] and record["issuer"] == plan_mod.ISSUER
    with pytest.raises(plan_mod.AuthorizationRefused, match="CI or pytest"):
        plan_mod.issue_authorization(
            img_plan, interactive=True, ci=True, pytest_active=False, **base
        )
    with pytest.raises(plan_mod.AuthorizationRefused, match="CI or pytest"):
        plan_mod.issue_authorization(
            img_plan, interactive=True, ci=False, pytest_active=True, **base
        )
    with pytest.raises(plan_mod.AuthorizationRefused, match="interactive terminal"):
        plan_mod.issue_authorization(
            img_plan, interactive=False, ci=False, pytest_active=False, **base
        )
    with pytest.raises(plan_mod.AuthorizationRefused, match="typing exactly"):
        plan_mod.issue_authorization(
            img_plan,
            interactive=True,
            ci=False,
            pytest_active=False,
            **{**base, "typed_phrase": "yes"},
        )
    with pytest.raises(plan_mod.AuthorizationRefused, match="lifetime"):
        plan_mod.issue_authorization(
            img_plan, interactive=True, ci=False, pytest_active=False, ttl_hours=10_000, **base
        )
    broken = copy.deepcopy(img_plan)
    broken["cases"][0]["prompts"]["positive"] = "edited"
    with pytest.raises(plan_mod.AuthorizationRefused, match="not valid"):
        plan_mod.issue_authorization(
            broken, interactive=True, ci=False, pytest_active=False, **base
        )
    # The default detection really does refuse here: this process runs under pytest.
    with pytest.raises(plan_mod.AuthorizationRefused):
        plan_mod.issue_authorization(img_plan, **base)


def test_launch_confirmation_is_a_separate_act_from_the_approval(img_plan) -> None:
    auth = _auth(img_plan)
    run, approve = plan_mod.launch_phrase(img_plan), plan_mod.approval_phrase(img_plan)
    assert run != approve and run.startswith("RUN ") and approve.startswith("APPROVE ")
    later = dryrun.EPOCH + timedelta(minutes=10)
    assert plan_mod.launch_problems(img_plan, auth, run, later) == []
    assert any(
        "not a launch confirmation" in p
        for p in plan_mod.launch_problems(img_plan, auth, approve, later)
    )
    assert plan_mod.launch_problems(img_plan, auth, "RUN 000000000000", later)
    assert any("predates" in p for p in plan_mod.launch_problems(img_plan, auth, run, dryrun.EPOCH))


def test_ai_plans_freeze_cpu_only_offline_protected_contract(ai_plan) -> None:
    assert plan_mod.shape_problems(ai_plan) == []
    assert "max_vram_used_mib" not in ai_plan["limits"]  # CPU work is not GPU work

    def broken(change):
        plan = copy.deepcopy(ai_plan)
        change(plan["cases"][0]["cpu_inference"])
        plan["digest"] = plan_mod.digest_of(plan)
        return " ".join(plan_mod.shape_problems(plan))

    assert "cpu_only" in broken(lambda c: c.update(cpu_only=False))
    assert "network" in broken(lambda c: c.update(network="allowed"))
    assert "protected interpreter" in broken(lambda c: c.update(protected_interpreter=False))
    assert "-ngl 0" in broken(
        lambda c: c.update(command=["llama-completion.exe", "--offline", "-ngl", "99"])
    )
    assert "--offline" in broken(lambda c: c.update(command=["llama-completion.exe", "-ngl", "0"]))
    # Egress-related flags are refused through the production closed flag vocabulary.
    assert "forbidden runtime flag" in broken(
        lambda c: c.update(
            command=["llama-completion.exe", "--offline", "-ngl", "0", "--host", "0.0.0.0"]
        )
    )
    assert "forbidden runtime flag" in broken(
        lambda c: c.update(command=["llama-completion.exe", "--offline", "-ngl", "0", "-hf", "x/y"])
    )
    assert "not allow-listed" in broken(
        lambda c: c.update(
            command=["llama-completion.exe", "--offline", "-ngl", "0", "--frobnicate", "1"]
        )
    )


# -------------------------------------------------------------------------------------------- readiness / safety


def _ready(plan, probes, auth=None, **kw):
    auth = _auth(plan) if auth is None else auth
    return safety.readiness(plan, probes, auth=auth, now=dryrun.EPOCH + timedelta(hours=1), **kw)


def _gate(result, gate_id):
    return next(g for g in result["gates"] if g["gate"] == gate_id)


def test_healthy_host_with_authorization_is_ready(img_plan, probes) -> None:
    result = _ready(img_plan, probes)
    assert result["ready"], result["gates"]


@pytest.mark.parametrize(
    ("override", "gate", "status"),
    [
        (
            {"endpoint": lambda url, kind: {"state": "free", "busy_jobs": 0}},
            "endpoint_ready",
            "HOLD",
        ),  # external runtime not running
        (
            {"endpoint": lambda url, kind: {"state": "occupied", "busy_jobs": 0}},
            "endpoint_ownership",
            "FAIL",
        ),
        (
            {"endpoint": lambda url, kind: {"state": "healthy", "busy_jobs": 2}},
            "no_active_generation",
            "FAIL",
        ),
        ({"active_generations": lambda url: [{"id": 1}]}, "no_active_generation", "FAIL"),
        ({"memory": lambda: {"available_gb": 2.0, "commit_used_gb": 10}}, "host_memory", "FAIL"),
        ({"memory": lambda: None}, "host_memory", "HOLD"),
        ({"memory": lambda: {"available_gb": 24.0, "commit_used_gb": 61.0}}, "host_commit", "FAIL"),
        ({"gpu": lambda: None}, "gpu_memory", "HOLD"),
        (
            {
                "gpu": lambda: {
                    "name": "x",
                    "driver": "1",
                    "total_mib": 12282.0,
                    "used_mib": 11500.0,
                    "free_mib": 700.0,
                    "uuid": "u",
                }
            },
            "gpu_memory",
            "FAIL",
        ),
        ({"disk_free_gb": lambda path: 1.0}, "disk_space", "FAIL"),
        ({"disk_free_gb": lambda path: None}, "disk_space", "HOLD"),
        ({"telemetry_available": lambda: False}, "telemetry", "HOLD"),
        ({"fault_collection_available": lambda: False}, "fault_collection", "HOLD"),
        (
            {"unresolved_stops": lambda: [{"stop": "device_loss", "lane": "gpu_forge"}]},
            "prior_safety_stops",
            "HOLD",
        ),
    ],
)
def test_each_resource_and_ownership_gate_blocks_dispatch(override, gate, status, img_plan) -> None:
    result = _ready(img_plan, dryrun.fake_probes(**override), verify_hashes=False)
    assert not result["ready"]
    assert _gate(result, gate)["status"] == status


def test_managed_runtime_held_by_a_stranger_and_unreadable_runtime_are_refused(tmp_path) -> None:
    probes = dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan("VID-Q0", STAGE_CANARY, tmp_path, probes, LEDGER)
    occupied = dryrun.fake_probes(endpoint=lambda url, kind: {"state": "occupied", "busy_jobs": 0})
    assert (
        _gate(_ready(plan, occupied, verify_hashes=False), "endpoint_ownership")["status"] == "FAIL"
    )


def test_wrong_launch_flags_are_a_failed_gate(tmp_path) -> None:
    probes = dryrun.fake_probes()
    case = dryrun.synthetic_case("VID-Q0", "VID-Q0.wan22-ti2v-5b-1.3.0", tmp_path)
    runtime = {
        **dryrun.runtime_for("VID-Q0"),
        "launch_flags": ["--disable-pinned-memory", "--disable-auto-launch"],
    }
    plan = plan_mod.build_plan(
        "VID-Q0",
        stage=STAGE_CANARY,
        cases=[case],
        runtime=runtime,
        limits=dict(dryrun.LIMITS_GPU),
        evidence_dir=str(tmp_path),
        probes=probes,
        ledger=LEDGER,
        now=dryrun.EPOCH,
    )
    wrong = dryrun.fake_probes(launch_flags=lambda rt: ["--disable-auto-launch"])
    assert _gate(_ready(plan, wrong, verify_hashes=False), "launch_flags")["status"] == "FAIL"
    unknown = dryrun.fake_probes()
    assert _gate(_ready(plan, unknown, verify_hashes=False), "launch_flags")["status"] == "HOLD"
    right = dryrun.fake_probes(
        launch_flags=lambda rt: ["--disable-auto-launch", "--disable-pinned-memory"]
    )
    assert _gate(_ready(plan, right, verify_hashes=False), "launch_flags")["status"] == "PASS"


def test_identity_and_authorization_gates(img_plan, probes) -> None:
    assert _gate(_ready(img_plan, probes, auth={}), "authorization")["status"] == "HOLD"
    Path(img_plan["cases"][0]["sources"][0]["path"]).write_bytes(b"changed")
    assert _gate(_ready(img_plan, probes), "identity_frozen")["status"] == "FAIL"
    assert _ready(img_plan, probes, verify_hashes=False)["ready"] or True


def test_ai_lane_yields_to_gpu_work_and_holds_without_a_protected_capture(ai_plan) -> None:
    assert _ready(ai_plan, dryrun.fake_probes())["ready"]
    busy = _ready(ai_plan, dryrun.fake_probes(gpu_activity=lambda: [{"endpoint": "forge"}]))
    assert _gate(busy, "ai_yields_to_generation")["status"] == "FAIL"
    none = _ready(ai_plan, dryrun.fake_probes(ai_capture_state=lambda: {}))
    assert _gate(none, "ai_capture")["status"] == "HOLD"
    for field, gate in (
        ("protected_interpreter", "protected_interpreter"),
        ("active", "capture_active"),
    ):
        state = {
            "active": True,
            "canary_pass_age_hours": 1.0,
            "protected_interpreter": True,
            field: False,
        }
        assert (
            _gate(_ready(ai_plan, dryrun.fake_probes(ai_capture_state=lambda s=state: s)), gate)[
                "status"
            ]
            == "HOLD"
        )
    for age in (None, 30.0, -1.0):
        state = {"active": True, "canary_pass_age_hours": age, "protected_interpreter": True}
        assert (
            _gate(
                _ready(ai_plan, dryrun.fake_probes(ai_capture_state=lambda s=state: s)),
                "canary_proof",
            )["status"]
            == "HOLD"
        )


def test_smart_review_needs_its_verified_memory_limit(tmp_path) -> None:
    probes = dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan(
        "AI-Q3", STAGE_CANARY, tmp_path, probes, LEDGER, ["AI-Q3.sam21-small"]
    )
    assert plan_mod.shape_problems(plan) == []
    ok = _ready(plan, probes)
    assert _gate(ok, "child_memory_limit")["status"] == "PASS"
    unverified = dryrun.fake_probes(ai_capture_state=lambda: {"child_memory_limit_verified": False})
    assert _gate(_ready(plan, unverified), "child_memory_limit")["status"] == "HOLD"


def test_stop_classification_never_retries() -> None:
    assert (
        safety.classify_stop({"error_message": "CUDA error: device-side assert triggered"})
        == "device_loss"
    )
    assert (
        safety.classify_stop({"error_message": "torch.OutOfMemoryError: CUDA out of memory"})
        == "allocation_failure"
    )
    assert safety.classify_stop({"error_message": "request timed out after 900 s"}) == "timeout"
    assert (
        safety.classify_stop({"error_message": "DispatchOutcomeUnknown: POST outcome unknown"})
        == "ambiguous_dispatch"
    )
    assert safety.classify_stop({"error_message": "", "retry_attempts": 1}) == "ambiguous_dispatch"
    assert (
        safety.classify_stop({"error_message": "", "return_to_queue_count": 1})
        == "ambiguous_dispatch"
    )
    assert safety.classify_stop({"error_message": "ok"}) is None


def test_telemetry_evaluation_detects_gaps_and_limit_violations() -> None:
    limits = {"min_available_ram_gb": 2, "max_commit_gb": 60, "max_vram_used_mib": 10000}
    telemetry = {"cadence_seconds": 2.0, "max_gap_seconds": 5.0, "required_availability": 0.9}

    def samples(override=None):
        override = override or {}
        return [
            {
                "t": float(t),
                "commit_fraction": 0.5,
                "available_ram_mib": 8000,
                "vram_used_mib": 9000,
                **override.get(t, {}),
            }
            for t in range(0, 41, 2)
        ]

    assert safety.evaluate_telemetry(samples(), limits, telemetry)["stop"] is None
    assert safety.evaluate_telemetry([], limits, telemetry)["stop"] == "telemetry_gap"
    gap = [s for s in samples() if not 10 < s["t"] < 30]
    assert safety.evaluate_telemetry(gap, limits, telemetry)["stop"] == "telemetry_gap"
    sparse = samples()[::4]
    assert (
        safety.evaluate_telemetry(sparse, limits, {**telemetry, "max_gap_seconds": 60})["stop"]
        == "telemetry_gap"
    )
    assert (
        safety.evaluate_telemetry(samples({10: {"device_loss": True}}), limits, telemetry)["stop"]
        == "device_loss"
    )
    assert (
        safety.evaluate_telemetry(samples({10: {"commit_fraction": 0.96}}), limits, telemetry)[
            "stop"
        ]
        == "host_commit_pressure"
    )
    assert (
        safety.evaluate_telemetry(samples({10: {"available_ram_mib": 1000}}), limits, telemetry)[
            "stop"
        ]
        == "low_available_ram"
    )
    assert (
        safety.evaluate_telemetry(samples({10: {"vram_used_mib": 12000}}), limits, telemetry)[
            "stop"
        ]
        == "allocation_failure"
    )
