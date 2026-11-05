"""PR-QUAL-SYSTEM-840: the campaign coordinator end to end with simulated adapters (CPU only, no host, no model)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from tools.qualification.system840 import (
    cli,
    coordinator,
    dryrun,
    evidence,
)
from tools.qualification.system840 import (
    ledger as ledger_mod,
)
from tools.qualification.system840 import (
    plan as plan_mod,
)
from tools.qualification.system840.arms import ARM_BY_ID, STAGE_CANARY, STAGE_COVERAGE

LEDGER = ledger_mod.load_ledger()
NOW = lambda: dryrun.EPOCH + timedelta(minutes=10)  # noqa: E731


def _stage(
    tmp_path,
    arm="IMG-Q0",
    stage=STAGE_CANARY,
    *,
    scenario="success",
    probes=None,
    auth="valid",
    confirm=None,
    session=None,
    adapter=None,
    plan=None,
    cap=None,
):
    probes = probes or dryrun.fake_probes()
    plan = plan or dryrun.build_synthetic_plan(
        arm, stage, tmp_path / "assets", probes, LEDGER, [cap] if cap else None
    )
    record = dryrun.synthetic_authorization(plan) if auth == "valid" else auth
    adapter = adapter or coordinator.SimulatedAdapter(scenario)
    session = session or coordinator.Session()
    report = coordinator.run_stage(
        plan,
        record,
        adapter=adapter,
        probes=probes,
        evidence_root=tmp_path / "evidence",
        confirm=confirm or (lambda p: p),
        session=session,
        ledger=LEDGER,
        now=NOW,
    )
    return report, adapter, session, plan


def _attempts(tmp_path):
    return evidence.list_attempts(tmp_path / "evidence")


def test_representative_dry_campaign_runs_every_gate_and_dispatches_once_per_stage(
    tmp_path,
) -> None:
    report = dryrun.run_dry_campaign(tmp_path)
    ran = [r for r in report["reports"] if r["status"] == coordinator.RAN]
    assert [(r["arm_id"], r["stage"]) for r in ran] == [
        ("IMG-Q0", "canary"),
        ("IMG-Q0", "coverage"),
        ("IMG-Q1", "canary"),
        ("IMG-Q1", "coverage"),
        ("VID-Q0", "canary"),
        ("VID-Q0", "coverage"),
    ]
    assert all(r["verification"] == evidence.OK and r["verdict"]["overall"] == "PASS" for r in ran)
    assert all(
        r["verdict"]["human_review_pending"] for r in ran
    )  # quality and usability stay human
    assert report["promotion"] == "NOT AUTHORIZED" and report["ledger_changed"] is False
    assert report["counts"]["RAN"] == 6
    assert {r["arm_id"] for r in report["reports"]} == set(
        ARM_BY_ID
    )  # every arm gets a truthful outcome
    assert len(evidence.list_attempts(tmp_path / "evidence-root")) == 6


def test_campaign_does_not_change_the_ledger_file(tmp_path) -> None:
    before = hashlib.sha256(ledger_mod.LEDGER_PATH.read_bytes()).hexdigest()
    dryrun.run_dry_campaign(tmp_path)
    assert hashlib.sha256(ledger_mod.LEDGER_PATH.read_bytes()).hexdigest() == before


def test_missing_or_wrong_authorization_dispatches_nothing(tmp_path) -> None:
    report, adapter, _, plan = _stage(tmp_path, auth=None)
    assert (
        report["status"] == coordinator.HOLD
        and "authoriz" in report["reason"]
        and adapter.calls == 0
    )
    wrong = {**dryrun.synthetic_authorization(plan), "plan_digest": "0" * 64}
    report, adapter, _, _ = _stage(tmp_path, auth=wrong, plan=plan)
    assert report["status"] == coordinator.HOLD and adapter.calls == 0
    assert _attempts(tmp_path) == []  # not even a directory was created


def test_typed_launch_is_required_and_distinct_from_the_approval(tmp_path) -> None:
    probes = dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan("IMG-Q0", STAGE_CANARY, tmp_path / "assets", probes, LEDGER)
    for typed in ("", "yes", plan_mod.approval_phrase(plan), "RUN 000000000000"):
        report, adapter, _, _ = _stage(tmp_path, plan=plan, confirm=lambda p, t=typed: t)
        assert report["status"] == coordinator.NOT_RUN and adapter.calls == 0, typed
    assert _attempts(tmp_path) == []
    report, adapter, _, _ = _stage(tmp_path, plan=plan)
    assert report["status"] == coordinator.RAN and adapter.calls == 1


def test_an_edited_plan_never_runs(tmp_path) -> None:
    probes = dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan("IMG-Q0", STAGE_CANARY, tmp_path / "assets", probes, LEDGER)
    approval = dryrun.synthetic_authorization(plan)
    plan["cases"][0]["prompts"]["positive"] = "edited after approval"
    report, adapter, _, _ = _stage(tmp_path, plan=plan, auth=approval)
    assert (
        report["status"] == coordinator.HOLD and "digest" in report["reason"] and adapter.calls == 0
    )


def test_held_unknown_and_wrong_stage_requests_are_refused(tmp_path) -> None:
    probes = dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan("IMG-Q0", STAGE_CANARY, tmp_path / "assets", probes, LEDGER)
    held = {
        **plan,
        "arm_id": "VID-Q4",
        "cases": [{**plan["cases"][0], "capability_id": "VID-Q4.wan-a14b-480p"}],
    }
    report, adapter, _, _ = _stage(tmp_path, plan=held, auth={})
    assert (
        report["status"] == coordinator.HOLD
        and "HOLD-A14B-NEW-BUDGET" in report["reason"]
        and adapter.calls == 0
    )
    report, _, _, _ = _stage(tmp_path, plan={"arm_id": "NOPE", "stage": "canary"}, auth={})
    assert report["status"] == coordinator.HOLD and "unknown arm" in report["reason"]
    zimage = {
        **plan,
        "arm_id": "IMG-Q1",
        "cases": [{**plan["cases"][0], "capability_id": "IMG-Q1.zimage-turbo-fp8"}],
    }
    report, adapter, _, _ = _stage(tmp_path, plan=zimage, auth={})
    assert (
        report["status"] == coordinator.HOLD
        and "HOLD-ZIMAGE-STABILITY" in report["reason"]
        and adapter.calls == 0
    )
    coverage, adapter, _, _ = _stage(tmp_path, stage=STAGE_COVERAGE)
    assert (
        coverage["status"] == coordinator.HOLD
        and "canary" in coverage["reason"]
        and adapter.calls == 0
    )


def test_dependencies_need_accepted_evidence_and_stopped_dependencies_block(tmp_path) -> None:
    report, adapter, _, _ = _stage(tmp_path, arm="IMG-Q1")
    assert (
        report["status"] == coordinator.HOLD and "IMG-Q0" in report["reason"] and adapter.calls == 0
    )
    session = coordinator.Session(stopped_arms={"IMG-Q0"}, accepted={("IMG-Q0", STAGE_CANARY)})
    report, adapter, _, _ = _stage(tmp_path, arm="IMG-Q1", session=session)
    assert report["status"] == coordinator.HOLD and "stopped" in report["reason"]
    session = coordinator.Session(accepted={("IMG-Q0", STAGE_CANARY)})
    report, adapter, _, _ = _stage(tmp_path, arm="IMG-Q1", session=session)
    assert report["status"] == coordinator.RAN


@pytest.mark.parametrize(
    ("scenario", "stop", "status"),
    [
        ("device_loss", "device_loss", coordinator.NO_GO),
        ("oom", "allocation_failure", coordinator.NO_GO),
    ],
)
def test_resource_failures_stop_the_arm_dependents_and_later_gpu_work(
    scenario, stop, status, tmp_path
) -> None:
    session = coordinator.Session()
    report, adapter, session, _ = _stage(tmp_path, scenario=scenario, session=session)
    assert report["stop"] == stop and report["status"] == status and adapter.calls == 1
    assert report["verdict"]["dimensions"]["resource_runtime_safety"]["verdict"] == "NO-GO"
    assert (
        "IMG-Q0" in session.stopped_arms
        and {"IMG-Q1", "IMG-Q2", "IMG-Q3"} <= session.stopped_arms
        and session.gpu_blocked
    )
    assert ("IMG-Q0", STAGE_CANARY) not in session.accepted
    # No retry of the stopped arm, and an unrelated GPU arm is blocked for the rest of the session.
    again, adapter2, _, _ = _stage(tmp_path / "again", session=session)
    assert again["status"] == coordinator.HOLD and adapter2.calls == 0
    other, adapter3, _, _ = _stage(tmp_path / "other", arm="VID-Q0", session=session)
    assert (
        other["status"] == coordinator.HOLD
        and "safety stop" in other["reason"]
        and adapter3.calls == 0
    )


def test_timeout_is_a_failure_and_ambiguous_dispatch_is_never_replayed(tmp_path) -> None:
    report, adapter, session, _ = _stage(tmp_path / "t", scenario="timeout")
    assert (
        report["verdict"]["dimensions"]["resource_runtime_safety"]["verdict"] == "FAIL"
        and "IMG-Q0" in session.stopped_arms
    )
    report, adapter, session, _ = _stage(tmp_path / "a", scenario="ambiguous_dispatch")
    assert report["stop"] == "ambiguous_dispatch" and adapter.calls == 1 and session.gpu_blocked
    assert report["verdict"]["dimensions"]["functional_correctness"]["verdict"] == "INCONCLUSIVE"
    coordinator_retry, adapter2, _, _ = _stage(tmp_path / "a2", session=session)
    assert coordinator_retry["status"] == coordinator.HOLD and adapter2.calls == 0


def test_adapter_exceptions_are_recorded_classified_and_not_retried(tmp_path) -> None:
    class Exploding:
        simulated = True
        calls = 0

        def execute(self, plan, workdir):
            Exploding.calls += 1
            raise RuntimeError("CUDA error: device-side assert triggered")

    report, _, session, _ = _stage(tmp_path, adapter=Exploding())
    assert (
        Exploding.calls == 1
        and report["stop"] == "device_loss"
        and "IMG-Q0" in session.stopped_arms
    )
    assert report["verification"] == evidence.OK and report["verdict"]["overall"] != "PASS"


def test_missing_telemetry_or_teardown_is_inconclusive_not_pass(tmp_path) -> None:
    report, _, session, _ = _stage(tmp_path / "g", scenario="telemetry_gap")
    assert report["verdict"]["dimensions"]["resource_runtime_safety"]["verdict"] == "INCONCLUSIVE"
    assert ("IMG-Q0", STAGE_CANARY) not in session.accepted and "IMG-Q0" in session.stopped_arms
    report, _, session, _ = _stage(tmp_path / "t", scenario="teardown_unverified")
    assert report["verdict"]["dimensions"]["resource_runtime_safety"]["verdict"] == "INCONCLUSIVE"
    assert (
        report["verdict"]["overall"] == "INCONCLUSIVE"
        and ("IMG-Q0", STAGE_CANARY) not in session.accepted
    )


def test_corrupt_or_missing_artifacts_fail_functional_and_integrity(tmp_path) -> None:
    report, _, session, _ = _stage(tmp_path / "c", scenario="corrupt_media")
    assert report["verdict"]["dimensions"]["artifact_media_integrity"]["verdict"] == "FAIL"
    assert ("IMG-Q0", STAGE_CANARY) not in session.accepted
    report, _, _, _ = _stage(tmp_path / "p", scenario="partial_artifacts")
    assert report["verdict"]["dimensions"]["functional_correctness"]["verdict"] == "FAIL"


def test_resource_preflight_failure_runtime_ownership_and_active_generation_block_dispatch(
    tmp_path,
) -> None:
    cases = {
        "low RAM": dryrun.fake_probes(memory=lambda: {"available_gb": 1.0, "commit_used_gb": 5}),
        "occupied port": dryrun.fake_probes(
            endpoint=lambda u, k: {"state": "occupied", "busy_jobs": 0}
        ),
        "busy runtime": dryrun.fake_probes(
            endpoint=lambda u, k: {"state": "healthy", "busy_jobs": 1}
        ),
        "no telemetry": dryrun.fake_probes(telemetry_available=lambda: False),
        "prior stop": dryrun.fake_probes(
            unresolved_stops=lambda: [{"stop": "device_loss", "lane": "gpu_forge"}]
        ),
    }
    for label, probes in cases.items():
        plan = dryrun.build_synthetic_plan(
            "IMG-Q0", STAGE_CANARY, tmp_path / label.replace(" ", "-"), dryrun.fake_probes(), LEDGER
        )
        report, adapter, _, _ = _stage(tmp_path / label.replace(" ", "-"), probes=probes, plan=plan)
        assert report["status"] == coordinator.HOLD and adapter.calls == 0, label
        assert report["gates"], label
    assert not (tmp_path / "evidence").exists() or _attempts(tmp_path) == []


def test_gpu_and_cpu_inference_never_mix_in_one_session(tmp_path) -> None:
    probes = dryrun.fake_probes()
    session = coordinator.Session()
    gpu, _, session, _ = _stage(tmp_path / "gpu", session=session, probes=probes)
    assert gpu["status"] == coordinator.RAN
    cpu_plan = dryrun.build_synthetic_plan(
        "AI-Q3", STAGE_CANARY, tmp_path / "cpu", probes, None, ["AI-Q3.sam21-small"]
    )
    report, adapter, _, _ = _stage(
        tmp_path / "cpu", arm="AI-Q3", session=session, probes=probes, plan=cpu_plan
    )
    assert (
        report["status"] == coordinator.HOLD
        and "never mixes" in report["reason"]
        and adapter.calls == 0
    )
    fresh, adapter, _, _ = _stage(tmp_path / "cpu2", arm="AI-Q3", probes=probes, plan=cpu_plan)
    assert fresh["status"] == coordinator.RAN and adapter.calls == 1


def test_ai_inference_requires_its_own_protected_capture_and_per_model_approval(tmp_path) -> None:
    probes = dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan(
        "AI-Q1", STAGE_CANARY, tmp_path / "ai", probes, None, ["AI-Q1.qwen3.5-4b-q4_k_m-unsloth"]
    )
    # The ledger still holds every AI candidate, so a ledger-aware coordinator refuses before anything else.
    report, adapter, _, _ = _stage(
        tmp_path / "ai",
        arm="AI-Q1",
        plan=plan,
        session=coordinator.Session(accepted={("AI-Q0", "canary")}),
    )
    assert (
        report["status"] == coordinator.HOLD
        and "HOLD in the ledger" in report["reason"]
        and adapter.calls == 0
    )
    # Without a ledger the capture gate still holds when the protected capture is absent.
    no_capture = dryrun.fake_probes(ai_capture_state=lambda: {})
    ready = coordinator.run_stage(
        plan,
        dryrun.synthetic_authorization(plan),
        adapter=coordinator.SimulatedAdapter(),
        probes=no_capture,
        evidence_root=tmp_path / "e",
        confirm=lambda p: p,
        session=coordinator.Session(accepted={("AI-Q0", "canary")}),
        now=NOW,
    )
    assert ready["status"] == coordinator.HOLD and "ai_capture" in ready["reason"]
    # An approval for the Qwen model cannot launch an LFM3 plan.
    other = json.loads(json.dumps(plan))
    other["cases"][0]["cpu_inference"]["model_id"] = "lfm3-1.7b-q4_k_m-liquidai"
    other["digest"] = plan_mod.digest_of(other)
    reused = {
        **dryrun.synthetic_authorization(plan),
        "plan_digest": other["digest"],
        "approval_phrase": plan_mod.approval_phrase(other),
    }
    blocked = coordinator.run_stage(
        other,
        reused,
        adapter=coordinator.SimulatedAdapter(),
        probes=probes,
        evidence_root=tmp_path / "e2",
        confirm=lambda p: p,
        session=coordinator.Session(accepted={("AI-Q0", "canary")}),
        now=NOW,
    )
    assert blocked["status"] == coordinator.HOLD and "exactly this model" in blocked["reason"]


def test_unwired_adapter_refuses_and_a_physical_adapter_is_refused_under_pytest(tmp_path) -> None:
    report, _, _, _ = _stage(tmp_path / "pytest", adapter=coordinator.UnwiredAdapter())
    assert report["status"] == coordinator.HOLD and "CI and under pytest" in report["reason"]
    assert _attempts(tmp_path / "pytest") == []

    class Physical(coordinator.UnwiredAdapter):
        simulated = True  # pretend it is allowed past the CI/pytest refusal

    report, _, _, _ = _stage(tmp_path / "unwired", adapter=Physical())
    assert (
        report["status"] == coordinator.NOT_RUN
        and "no physical adapter is wired" in report["reason"]
    )
    attempts = _attempts(tmp_path / "unwired")
    assert len(attempts) == 1 and evidence.verify_attempt(attempts[0])["status"] == evidence.OK
    assert json.loads((attempts[0] / "dispatch.json").read_text())["dispatched"] is False


def test_arms_without_plans_report_truthful_outcomes(tmp_path) -> None:
    report = coordinator.run_campaign(
        [],
        {},
        {},
        probes=dryrun.fake_probes(),
        evidence_root=tmp_path / "e",
        confirm=lambda p: p,
        ledger=LEDGER,
        now=NOW,
    )
    by_arm = {r["arm_id"]: r for r in report["reports"]}
    assert (
        by_arm["IMG-Q4"]["status"] == coordinator.NOT_RUN
        and "offline" in by_arm["IMG-Q4"]["reason"]
    )  # assessed, never executed
    assert by_arm["AI-Q0"]["status"] == coordinator.HOLD
    assert (
        by_arm["AI-Q1"]["status"] == coordinator.HOLD
        and "HOLD-AI-ETW-CANARY" in by_arm["AI-Q1"]["reason"]
    )
    assert by_arm["AI-Q2"]["status"] == coordinator.HOLD
    assert by_arm["IMG-Q0"]["status"] == coordinator.NOT_RUN
    assert not (tmp_path / "e").exists()  # nothing was written for arms that did not run
    out = tmp_path / "out" / "report.json"
    coordinator.write_campaign_report(report, out)
    with pytest.raises(evidence.ArchiveRefused):
        coordinator.write_campaign_report(report, out)


def test_previous_accepted_evidence_survives_later_attempts(tmp_path) -> None:
    first, _, _, _ = _stage(tmp_path, scenario="success")
    path = tmp_path / "evidence" / first["attempt"]
    snapshot = {p.name: p.read_bytes() for p in path.rglob("*") if p.is_file()}
    later, _, _, _ = _stage(tmp_path, scenario="device_loss")
    assert later["attempt"] != first["attempt"]
    assert {p.name: p.read_bytes() for p in path.rglob("*") if p.is_file()} == snapshot
    assert evidence.verify_attempt(path)["status"] == evidence.OK
    assert len(_attempts(tmp_path)) == 2


# ----------------------------------------------------------------------------- hygiene: no network, download, GPU


def test_package_contains_no_download_network_or_gpu_code() -> None:
    package = Path(cli.__file__).parent
    forbidden = re.compile(
        r"hf_hub_download|snapshot_download|urlretrieve|urllib\.request|requests\.|socket\.|import torch|import requests"
    )
    for source in package.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not forbidden.search(text), source.name
        if source.name != "probes.py":
            assert "subprocess" not in text, f"{source.name} spawns processes"
    assert "nvidia-smi" not in (package / "coordinator.py").read_text(encoding="utf-8")


def test_cli_ledger_dry_run_verify_compare_and_refusals(tmp_path, capsys, monkeypatch) -> None:
    assert cli.main(["ledger", "--check", "--live"]) == 0
    out = capsys.readouterr().out
    assert "capabilities" in out and "PROBLEM" not in out and "DRIFT" not in out
    report_path = tmp_path / "dry.json"
    assert cli.main(["dry-run", "--out", str(report_path)]) == 0
    payload = json.loads(report_path.read_text())
    assert payload["simulated"] is True and payload["counts"]["RAN"] == 6
    # Approval from a non-interactive session is refused.
    plan = dryrun.build_synthetic_plan(
        "IMG-Q0", STAGE_CANARY, tmp_path / "a", dryrun.fake_probes(), LEDGER
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    monkeypatch.setattr("builtins.input", lambda prompt="": plan_mod.approval_phrase(plan))
    assert (
        cli.main(
            [
                "authorize",
                "--plan",
                str(plan_path),
                "--out",
                str(tmp_path / "auth.json"),
                "--approved-by",
                "owner",
            ]
        )
        == 3
    )
    assert not (tmp_path / "auth.json").exists()
    assert cli.main(["verify", str(tmp_path / "missing")]) == 1
    assert cli.main(["compare", str(tmp_path / "x"), str(tmp_path / "y")]) == 5
    # Plans and approvals may not be written inside the repository.
    with pytest.raises(SystemExit):
        cli._outside_repo(Path(evidence.REPO_ROOT) / "plan.json")
