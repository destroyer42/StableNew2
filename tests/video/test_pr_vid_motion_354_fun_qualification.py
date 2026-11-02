"""PR-VID-MOTION-354: the Fun Control 5B qualification proposal is frozen, offline and cannot reach a GPU by accident.

Every executor here is a fake.  No Comfy, model, GPU, download or network is involved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.video.workflow_catalog import build_builtin_workflow_specs
from src.video.workflow_catalog_fun_control import FUN_ASSETS, FUN_ID, FUN_MODEL
from tools.qualification.fun354 import harness, q0
from tools.qualification.fun354 import plan as plan_module
from tools.qualification.fun354.__main__ import main as cli_main
from tools.qualification.fun354.harness import (
    FEASIBLE,
    INCONCLUSIVE,
    NO_GO,
    NOT_RUN,
    Authorization,
    CaseObservation,
    run_qualification,
)
from tools.qualification.fun354.plan import (
    CASE_Q1,
    CASE_Q2_A,
    CASE_Q2_B,
    CASE_Q2_CANCEL,
    STOP_ALLOCATION,
    STOP_DEVICE_LOSS,
    STOP_OPERATOR,
    STOP_TEARDOWN,
    build_plan,
)

HOST = q0.HostFacts(32768, 20000, 49152, 50 * 1024**3)
SPEC_DIGEST_BEFORE = None


def _spec():
    return next(s for s in build_builtin_workflow_specs() if s.workflow_id == FUN_ID)


def _inputs(tmp_path: Path):
    clip = tmp_path / "drive.mp4"
    ref = tmp_path / "ref.png"
    clip.write_bytes(b"clip bytes")
    ref.write_bytes(b"reference bytes")
    plan = build_plan(
        driving_clip_sha256=hashlib.sha256(clip.read_bytes()).hexdigest(),
        driving_clip_size=clip.stat().st_size,
        reference_sha256=hashlib.sha256(ref.read_bytes()).hexdigest(),
        reference_size=ref.stat().st_size,
    )
    return plan, {"driving_clip": clip, "reference_image": ref}


def _ready_report(plan, inputs):
    return q0.run_q0(
        plan,
        folders={},
        host=HOST,
        inputs=inputs,
        runtime_commit=plan.runtime_commit,
        verifier=lambda spec, folders: (),
    )


class FakeExecutor:
    """Scripted per-case behaviour; records every call so a test can prove nothing ran."""

    def __init__(self, **overrides: dict[str, object]) -> None:
        self.calls: list[str] = []
        self.overrides = overrides

    def run_case(self, plan, phase, case):
        self.calls.append(case.case_id)
        fields = {
            "phase_id": phase.phase_id,
            "case_id": case.case_id,
            "completed": True,
            "frames_expected": case.frames,
            "frames_delivered": case.frames,
            "peak_host_commit_fraction": 0.6,
            "min_available_ram_mib": 4000,
            "peak_vram_mib": 9000,
            "wall_seconds": 120.0,
        }
        fields.update(self.overrides.get(case.case_id, {}))
        return CaseObservation(**fields)


def _authorization(plan):
    return Authorization(plan.digest, "owner")


# --- the frozen plan ---------------------------------------------------------------------------------


def test_the_plan_pins_exact_assets_phases_and_stop_conditions() -> None:
    plan = build_plan()
    assert {a.name: (a.size, a.sha256) for a in plan.assets} == {
        n: (v["size"], v["sha256"]) for n, v in FUN_ASSETS.items()
    }
    assert [p.phase_id for p in plan.phases] == ["Q0", "Q1", "Q2"] and not plan.phase("Q0").physical
    assert [(c.case_id, c.frames) for c in plan.physical_cases] == [
        (CASE_Q1, 17), (CASE_Q2_A, 49), (CASE_Q2_B, 49), (CASE_Q2_CANCEL, 49),
    ]  # fmt: skip
    assert {c.seed for c in plan.physical_cases} == set(plan_module.SEEDS)
    codes = {s.code for s in plan.stops}
    assert {STOP_DEVICE_LOSS, STOP_ALLOCATION, STOP_TEARDOWN, STOP_OPERATOR} <= codes
    record = plan.to_record()
    assert record["physical_execution"] == "NOT AUTHORIZED"
    assert plan.runtime_commit == "6b747c0428c343e1417219641db93a4fb7cb69ae"
    assert plan.launch_flags == ("--disable-pinned-memory", "--disable-auto-launch")


def test_every_planned_length_is_legal_for_the_workflow_and_the_digest_is_canonical() -> None:
    from src.video.workflow_frame_count import legal_frame_counts

    legal = legal_frame_counts(_spec())
    plan = build_plan()
    assert all(c.frames in legal for c in plan.physical_cases)
    expected = hashlib.sha256(
        json.dumps(plan.to_record(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert plan.digest == expected == build_plan().digest


def test_any_change_to_the_plan_changes_its_digest() -> None:
    base = build_plan()
    assert build_plan(driving_clip_sha256="a" * 64).digest != base.digest
    assert replace(base, runtime_commit="b" * 40).digest != base.digest
    assert replace(base, stops=base.stops[:-1]).digest != base.digest
    other = replace(base, assets=(replace(base.assets[0], sha256="c" * 64), *base.assets[1:]))
    assert other.digest != base.digest


def test_the_immutable_catalog_entry_is_untouched_and_still_blocks_execution() -> None:
    spec = _spec()
    readiness = spec.backend_defaults["resource_readiness"]
    assert spec.workflow_version == "1.0.0" and spec.governance_state == "experimental"
    assert readiness["qualification_status"] == "not_qualified"
    build_plan()  # building a proposal must not alter the spec
    assert _spec().backend_defaults["resource_readiness"] == readiness
    assert spec.backend_defaults["frame_count_policy"]["maximum"] == 49


def test_planning_refuses_a_catalog_that_no_longer_matches_the_reviewed_spec(monkeypatch) -> None:
    spec = _spec()
    forged = replace(
        spec,
        backend_defaults={
            **spec.backend_defaults,
            "resource_readiness": {"qualification_status": "qualified"},
        },
    )
    monkeypatch.setattr(plan_module, "fun_control_spec", lambda: forged)
    with pytest.raises(plan_module.PlanError, match="not_qualified"):
        build_plan()


# --- Q0 ------------------------------------------------------------------------------------------------


def test_a_missing_fun_control_model_is_a_named_blocker(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    folders = {
        "diffusion_models": [tmp_path / "models" / "diffusion_models"],
        "text_encoders": [],
        "vae": [],
    }
    report = q0.run_q0(
        plan, folders=folders, host=HOST, inputs=inputs, runtime_commit=plan.runtime_commit
    )
    weights = next(c for c in report.checks if c.check_id == "pinned_weights")
    assert (
        weights.status == q0.BLOCKED
        and FUN_MODEL in weights.detail
        and "no automatic download" in weights.detail
    )
    assert report.status == q0.NOT_READY and not report.ready
    assert not (tmp_path / "models").exists()  # nothing was created or fetched


def test_q0_blocks_on_unpinned_or_changed_inputs_and_flags_unknowns(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    unpinned = q0.run_q0(
        build_plan(),
        folders={},
        host=HOST,
        inputs=inputs,
        runtime_commit=plan.runtime_commit,
        verifier=lambda s, f: (),
    )
    assert {c.check_id for c in unpinned.blockers} == {
        "input_driving_clip",
        "input_reference_image",
    }
    inputs["driving_clip"].write_bytes(b"replaced")
    changed = q0.run_q0(
        plan,
        folders={},
        host=HOST,
        inputs=inputs,
        runtime_commit=plan.runtime_commit,
        verifier=lambda s, f: (),
    )
    assert [c.check_id for c in changed.blockers] == ["input_driving_clip"]
    unread = q0.run_q0(plan, inputs=inputs)
    statuses = {c.check_id: c.status for c in unread.checks}
    assert (
        statuses["pinned_weights"]
        == statuses["runtime_identity"]
        == statuses["host_facts"]
        == q0.UNKNOWN
    )
    assert unread.status != q0.READY and unread.host is None


def test_a_wrong_runtime_commit_or_a_full_disk_blocks(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    wrong = q0.run_q0(
        plan,
        folders={},
        host=HOST,
        inputs=inputs,
        runtime_commit="f" * 40,
        verifier=lambda s, f: (),
    )
    assert [c.check_id for c in wrong.blockers] == ["runtime_identity"]
    tight = replace(HOST, free_disk_bytes=10)
    full = q0.run_q0(
        plan,
        folders={},
        host=tight,
        inputs=inputs,
        runtime_commit=plan.runtime_commit,
        verifier=lambda s, f: (),
    )
    assert [c.check_id for c in full.blockers] == ["host_facts"]


def test_a_fully_satisfied_q0_is_ready_but_still_not_authorized(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    report = _ready_report(plan, inputs)
    assert report.ready and report.to_record()["physical_execution"] == "NOT AUTHORIZED"
    assert report.host is not None and report.host.gpu.startswith("not read")
    assert any(c.check_id == "authorization" and c.status == q0.INFO for c in report.checks)


def test_host_facts_read_counters_without_a_gpu(tmp_path: Path) -> None:
    facts = q0.read_host_facts(tmp_path)
    assert (
        facts.total_ram_mib > 0 and facts.free_disk_bytes > 0 and facts.gpu.startswith("not read")
    )


# --- the guarded runner with fake executors -----------------------------------------------------------


def test_nothing_runs_without_an_authorization_bound_to_this_plan(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    report = _ready_report(plan, inputs)
    for auth in (
        None,
        Authorization("0" * 64, "owner"),
        Authorization(plan.digest, "owner", scope="read_only"),
    ):
        executor = FakeExecutor()
        outcome = run_qualification(plan, report, executor, auth)
        assert (
            outcome.verdict == NOT_RUN
            and executor.calls == []
            and "not authorized" in outcome.reason
        )


def test_a_blocked_q0_never_reaches_the_executor_even_when_authorized(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    folders = {"diffusion_models": [], "text_encoders": [], "vae": []}
    blocked = q0.run_q0(
        plan, folders=folders, host=HOST, inputs=inputs, runtime_commit=plan.runtime_commit
    )
    executor = FakeExecutor()
    outcome = run_qualification(plan, blocked, executor, _authorization(plan))
    assert outcome.verdict == NOT_RUN and executor.calls == [] and FUN_MODEL in outcome.reason


def test_a_q0_for_another_plan_is_refused(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    other = replace(plan, runtime_commit="e" * 40)
    outcome = run_qualification(
        plan, _ready_report(other, inputs), FakeExecutor(), _authorization(plan)
    )
    assert outcome.verdict == NOT_RUN and "different plan" in outcome.reason


def test_all_cases_clean_is_feasible_and_says_nothing_about_quality(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    executor = FakeExecutor()
    outcome = run_qualification(plan, _ready_report(plan, inputs), executor, _authorization(plan))
    assert outcome.verdict == FEASIBLE and executor.calls == [
        c.case_id for c in plan.physical_cases
    ]
    assert "not visual quality" in outcome.to_record()["scope"]  # type: ignore[operator]


def test_an_allocation_failure_with_complete_telemetry_is_no_go_and_stops_without_retry(
    tmp_path: Path,
) -> None:
    plan, inputs = _inputs(tmp_path)
    executor = FakeExecutor(
        **{CASE_Q1: {"completed": False, "frames_delivered": 0, "stop_code": STOP_ALLOCATION}}
    )
    outcome = run_qualification(plan, _ready_report(plan, inputs), executor, _authorization(plan))
    assert outcome.verdict == NO_GO and executor.calls == [
        CASE_Q1
    ]  # Q2 is never attempted and nothing is retried


def test_a_q2_device_loss_is_no_go_after_q1_passed(tmp_path: Path) -> None:
    plan, inputs = _inputs(tmp_path)
    executor = FakeExecutor(
        **{CASE_Q2_A: {"completed": False, "frames_delivered": 3, "stop_code": STOP_DEVICE_LOSS}}
    )
    outcome = run_qualification(plan, _ready_report(plan, inputs), executor, _authorization(plan))
    assert outcome.verdict == NO_GO and executor.calls == [CASE_Q1, CASE_Q2_A]


@pytest.mark.parametrize(
    "fields",
    [
        {"telemetry_complete": False},
        {"identity_verified": False},
        {"teardown_clean": False, "stop_code": STOP_TEARDOWN},
        {"completed": False, "frames_delivered": 0, "stop_code": STOP_OPERATOR},
        {"frames_delivered": 16},
        {
            "stop_code": STOP_ALLOCATION,
            "completed": False,
            "telemetry_complete": False,
            "frames_delivered": 0,
        },
    ],
)
def test_unreliable_evidence_is_inconclusive_never_feasible(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    plan, inputs = _inputs(tmp_path)
    executor = FakeExecutor(**{CASE_Q1: fields})
    outcome = run_qualification(plan, _ready_report(plan, inputs), executor, _authorization(plan))
    assert outcome.verdict == INCONCLUSIVE and executor.calls == [CASE_Q1]


def test_an_executor_exception_or_wrong_case_answer_is_recorded_and_not_retried(
    tmp_path: Path,
) -> None:
    plan, inputs = _inputs(tmp_path)

    class Boom:
        calls = 0

        def run_case(self, plan, phase, case):
            Boom.calls += 1
            raise RuntimeError("driver exploded")

    outcome = run_qualification(plan, _ready_report(plan, inputs), Boom(), _authorization(plan))
    assert (
        outcome.verdict == INCONCLUSIVE
        and Boom.calls == 1
        and "driver exploded" in outcome.observations[0].note
    )

    class Liar(FakeExecutor):
        def run_case(self, plan, phase, case):
            obs = super().run_case(plan, phase, case)
            return replace(obs, case_id="something_else")

    liar = Liar()
    outcome = run_qualification(plan, _ready_report(plan, inputs), liar, _authorization(plan))
    assert outcome.verdict == INCONCLUSIVE and liar.calls == [CASE_Q1]


def test_judge_without_observations_is_not_run_and_partial_runs_are_inconclusive(
    tmp_path: Path,
) -> None:
    plan, _ = _inputs(tmp_path)
    assert harness.judge(plan, [])[0] == NOT_RUN
    only_q1 = [FakeExecutor().run_case(plan, plan.phase("Q1"), plan.phase("Q1").cases[0])]
    verdict, reason = harness.judge(plan, only_q1)
    assert verdict == INCONCLUSIVE and "Not every planned case ran" in reason


# --- CLI -----------------------------------------------------------------------------------------------


def test_the_cli_proposes_and_checks_read_only_and_has_no_run_command(
    tmp_path: Path, capsys
) -> None:
    plan_file = tmp_path / "evidence" / "plan.json"
    assert cli_main(["propose", "--out", str(plan_file)]) == 0
    stored = json.loads(plan_file.read_text(encoding="utf-8"))
    assert (
        stored["digest"] == build_plan().digest and stored["physical_execution"] == "NOT AUTHORIZED"
    )

    code = cli_main(
        ["check", "--plan", str(plan_file), "--out", str(tmp_path / "evidence" / "q0.json")]
    )
    output = capsys.readouterr().out
    assert code == 2 and "NOT AUTHORIZED" in output and "[BLOCKED] input_driving_clip" in output
    assert json.loads((tmp_path / "evidence" / "q0.json").read_text(encoding="utf-8"))[
        "status"
    ] in {q0.NOT_READY, q0.INCOMPLETE}

    with pytest.raises(SystemExit):
        cli_main(["run", "--plan", str(plan_file)])


def test_the_cli_refuses_to_write_evidence_into_the_repository(tmp_path: Path) -> None:
    repo_target = Path(plan_module.__file__).resolve().parents[3] / "reports" / "fun354_plan.json"
    with pytest.raises(SystemExit, match="outside the repository"):
        cli_main(["propose", "--out", str(repo_target)])
    assert not repo_target.exists()


def test_the_cli_rejects_a_stored_plan_that_no_longer_matches(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    cli_main(["propose", "--out", str(plan_file)])
    record = json.loads(plan_file.read_text(encoding="utf-8"))
    record["digest"] = "0" * 64
    plan_file.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(SystemExit, match="does not match"):
        cli_main(["check", "--plan", str(plan_file), "--out", str(tmp_path / "q0.json")])
