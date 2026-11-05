"""PR-QUAL-SYSTEM-840: immutable evidence archives, verdict classification, status proposals, read-only comparator."""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from tools.qualification.system840 import compare, coordinator, dryrun, evidence, safety, verdict
from tools.qualification.system840.arms import STAGE_CANARY
from tools.qualification.system840.ledger import load_ledger
from tools.qualification.system840.statuses import EvidenceKind, Status

LEDGER = load_ledger()


def _plan(tmp_path: Path, arm: str = "IMG-Q0", stage: str = STAGE_CANARY):
    return dryrun.build_synthetic_plan(
        arm, stage, tmp_path / "assets", dryrun.fake_probes(), LEDGER
    )


def _open(tmp_path: Path, plan=None, token: str = "aaaaaa"):
    root = tmp_path / "root"
    return evidence.Attempt.open(root, plan or _plan(tmp_path), now=dryrun.EPOCH, token=token)


# ------------------------------------------------------------------------------------------------------- archives


def test_attempt_lifecycle_seals_verifies_and_saves_the_plan_first(tmp_path) -> None:
    attempt = _open(tmp_path)
    assert (
        attempt.partial / evidence.PLAN_FILE
    ).is_file()  # frozen plan exists before any dispatch
    src = tmp_path / "out.txt"
    src.write_text("evidence")
    attempt.add_file(src, "files/out.txt", role="artifact")
    final = attempt.seal({"stop": None}, now=dryrun.EPOCH)
    assert final.is_dir() and not attempt.partial.exists()
    report = evidence.verify_attempt(final)
    assert report["status"] == evidence.OK, report
    assert src.read_text() == "evidence"  # the original is copied, never moved


def test_evidence_is_never_overwritten_or_reused(tmp_path) -> None:
    attempt = _open(tmp_path)
    src = tmp_path / "a.txt"
    src.write_text("one")
    attempt.add_file(src, "a.txt", role="artifact")
    with pytest.raises(evidence.ArchiveRefused, match="never overwritten"):
        attempt.add_file(src, "a.txt", role="artifact")
    with pytest.raises(evidence.ArchiveRefused):
        attempt.write_json("plan.json", {}, role="x")
    with pytest.raises(evidence.ArchiveRefused, match="relative"):
        attempt.add_file(src, "../escape.txt", role="artifact")
    attempt.seal({}, now=dryrun.EPOCH)
    with pytest.raises(evidence.ArchiveRefused, match="sealed"):
        attempt.add_file(src, "late.txt", role="artifact")
    with pytest.raises(evidence.ArchiveRefused, match="already sealed"):
        attempt.seal({})
    # An attempt with an identical identity can never reuse or clobber an accepted archive.
    with pytest.raises(evidence.ArchiveRefused, match="already exists"):
        evidence.Attempt.open(tmp_path / "root", attempt.plan, now=dryrun.EPOCH, token="aaaaaa")


def test_a_failed_second_attempt_leaves_the_accepted_archive_untouched(tmp_path) -> None:
    first = _open(tmp_path, token="111111")
    path = first.seal({"stop": None}, now=dryrun.EPOCH)
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    second = evidence.Attempt.open(
        tmp_path / "root", first.plan, now=dryrun.EPOCH + timedelta(minutes=1), token="222222"
    )
    second.write_json("note.json", {"cancelled": True}, role="note")  # abandoned: never sealed
    assert {p.name: p.read_bytes() for p in path.iterdir()} == before
    assert evidence.verify_attempt(path)["status"] == evidence.OK
    assert evidence.verify_attempt(second.partial)["status"] == evidence.INCOMPLETE
    assert evidence.interrupted_attempts(tmp_path / "root") == [second.partial]
    assert evidence.list_attempts(tmp_path / "root", "IMG-Q0") == [path]


def test_tampering_truncation_and_extras_are_detected(tmp_path) -> None:
    attempt = _open(tmp_path)
    src = tmp_path / "x.png"
    src.write_bytes(b"0123456789")
    attempt.add_file(src, "x.png", role="artifact")
    final = attempt.seal({}, now=dryrun.EPOCH)
    target = final / "x.png"
    target.write_bytes(b"01234")
    report = evidence.verify_attempt(final)
    assert report["status"] == evidence.TAMPERED and any("x.png" in p for p in report["problems"])
    target.write_bytes(b"0123456789")
    assert evidence.verify_attempt(final)["status"] == evidence.OK
    (final / "stowaway.txt").write_text("x")
    assert evidence.verify_attempt(final)["status"] == evidence.TAMPERED
    (final / "stowaway.txt").unlink()
    (final / evidence.COMPLETE).write_text("0" * 64)
    assert evidence.verify_attempt(final)["status"] == evidence.TAMPERED
    (final / evidence.COMPLETE).unlink()
    assert evidence.verify_attempt(final)["status"] == evidence.INCOMPLETE
    assert evidence.verify_attempt(tmp_path / "nope")["status"] == evidence.MISSING


def test_evidence_root_inside_the_repository_is_refused() -> None:
    with pytest.raises(evidence.ArchiveRefused, match="inside the repository"):
        evidence.resolve_root(Path(evidence.REPO_ROOT) / "reports" / "qual")
    assert str(evidence.default_root()).endswith("QUAL-840")


def test_media_validation_decodes_pixels_not_just_headers(tmp_path) -> None:
    from PIL import Image

    good, bad = tmp_path / "good.png", tmp_path / "bad.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(good)
    data = good.read_bytes()
    bad.write_bytes(data[: len(data) // 2])  # truncated PNG
    attempt = _open(tmp_path)
    attempt.add_file(good, "good.png", role="artifact")
    attempt.add_file(bad, "bad.png", role="artifact")
    reports = evidence.validate_media_files(attempt.partial, {"files": attempt.files})
    assert {r["path"]: r["valid"] for r in reports} == {"good.png": True, "bad.png": False}


def test_verdict_files_are_written_beside_never_inside_or_over(tmp_path) -> None:
    final = _open(tmp_path).seal({}, now=dryrun.EPOCH)
    path = evidence.write_verdict(final, {"overall": "PASS"})
    assert path.parent == final.parent and path.name.endswith(".verdict.json")
    assert (
        evidence.verify_attempt(final)["status"] == evidence.OK
    )  # sibling file does not alter the sealed archive
    with pytest.raises(evidence.ArchiveRefused):
        evidence.write_verdict(final, {"overall": "FAIL"})


# -------------------------------------------------------------------------------------------------------- verdicts


def _good_observations(plan):
    return {
        "jobs_admitted": plan["jobs"],
        "artifacts": plan["artifacts"],
        "stop": None,
        "teardown_clean": True,
        "identity_verified": True,
        "provenance_complete": True,
        "telemetry": {"stop": None, "samples": 30},
    }


OK_REPORT = {"status": evidence.OK, "problems": []}
MEDIA_OK = [{"path": "a.png", "valid": True}]


def _dim(result, name):
    return result["dimensions"][name]["verdict"]


def test_clean_attempt_passes_automated_dimensions_but_leaves_human_dimensions_pending(
    tmp_path,
) -> None:
    plan = _plan(tmp_path)
    result = verdict.classify_attempt(
        plan, _good_observations(plan), verification=OK_REPORT, media_reports=MEDIA_OK
    )
    for name in (
        "functional_correctness",
        "resource_runtime_safety",
        "artifact_media_integrity",
        "reproducibility_provenance",
    ):
        assert _dim(result, name) == "PASS"
    assert _dim(result, "visual_or_suggestion_quality") == "PENDING_OPERATOR_REVIEW"
    assert result["human_review_pending"] and not result["complete"]


def test_high_automated_similarity_never_decides_quality(tmp_path) -> None:
    plan = _plan(tmp_path)
    obs = {
        **_good_observations(plan),
        "automated_measures": {"ssim": 0.999, "clip_similarity": 0.99},
    }
    result = verdict.classify_attempt(plan, obs, verification=OK_REPORT, media_reports=MEDIA_OK)
    assert _dim(result, "visual_or_suggestion_quality") == "PENDING_OPERATOR_REVIEW"
    assert (
        result["automated_measures"]["ssim"] == 0.999
    )  # recorded beside, not in place of, the human judgment
    rated = verdict.classify_attempt(
        plan,
        obs,
        verification=OK_REPORT,
        media_reports=MEDIA_OK,
        human_ratings={
            "quality": {"verdict": "FAIL", "rated_by": "rob"},
            "usability": {"verdict": "PASS", "rated_by": "rob"},
        },
    )
    assert _dim(rated, "visual_or_suggestion_quality") == "FAIL" and rated["overall"] == "FAIL"
    unsigned = verdict.classify_attempt(
        plan,
        obs,
        verification=OK_REPORT,
        media_reports=MEDIA_OK,
        human_ratings={"quality": {"verdict": "PASS"}},
    )
    assert _dim(unsigned, "visual_or_suggestion_quality") == "PENDING_OPERATOR_REVIEW"


@pytest.mark.parametrize("status", [evidence.INCOMPLETE, evidence.TAMPERED, evidence.MISSING])
def test_incomplete_evidence_is_inconclusive_never_pass(status, tmp_path) -> None:
    plan = _plan(tmp_path)
    result = verdict.classify_attempt(
        plan,
        _good_observations(plan),
        verification={"status": status, "problems": ["x"]},
        media_reports=MEDIA_OK,
    )
    assert result["overall"] == "INCONCLUSIVE" and not result["complete"]
    assert all(d["verdict"] == "INCONCLUSIVE" for d in result["dimensions"].values())


def test_resource_stops_classification(tmp_path) -> None:
    plan = _plan(tmp_path)

    def run(**changes):
        obs = {**_good_observations(plan), **changes}
        return verdict.classify_attempt(plan, obs, verification=OK_REPORT, media_reports=MEDIA_OK)

    device = run(stop="device_loss", artifacts=0)
    assert (
        _dim(device, "resource_runtime_safety") == "NO_GO"
        or _dim(device, "resource_runtime_safety") == "NO-GO"
    )
    assert _dim(device, "functional_correctness") == "FAIL"
    assert _dim(run(stop="allocation_failure", artifacts=0), "resource_runtime_safety") == "NO-GO"
    assert _dim(run(stop="timeout", artifacts=0), "resource_runtime_safety") == "FAIL"
    # Without proven teardown, telemetry or identity a refusal cannot be definitive.
    assert (
        _dim(run(stop="device_loss", teardown_clean=None), "resource_runtime_safety")
        == "INCONCLUSIVE"
    )
    assert (
        _dim(run(telemetry={"stop": "telemetry_gap"}), "resource_runtime_safety") == "INCONCLUSIVE"
    )
    assert _dim(run(identity_verified=None), "resource_runtime_safety") == "INCONCLUSIVE"
    assert (
        _dim(run(stop="ambiguous_dispatch", artifacts=0), "functional_correctness")
        == "INCONCLUSIVE"
    )
    assert _dim(run(artifacts=0), "functional_correctness") == "FAIL"
    assert _dim(run(identity_verified=False), "reproducibility_provenance") == "FAIL"
    assert _dim(run(provenance_complete=False), "reproducibility_provenance") == "INCONCLUSIVE"
    assert _dim(run(jobs_admitted=None), "functional_correctness") == "INCONCLUSIVE"


def test_media_integrity_dimension(tmp_path) -> None:
    plan = _plan(tmp_path)
    obs = _good_observations(plan)
    assert (
        _dim(
            verdict.classify_attempt(plan, obs, verification=OK_REPORT, media_reports=[]),
            "artifact_media_integrity",
        )
        == "INCONCLUSIVE"
    )
    bad = [{"path": "a.png", "valid": True}, {"path": "b.png", "valid": False}]
    assert (
        _dim(
            verdict.classify_attempt(plan, obs, verification=OK_REPORT, media_reports=bad),
            "artifact_media_integrity",
        )
        == "FAIL"
    )


def test_status_proposals_never_change_the_ledger_or_promote(tmp_path) -> None:
    plan = _plan(tmp_path)
    passed = verdict.classify_attempt(
        plan, _good_observations(plan), verification=OK_REPORT, media_reports=MEDIA_OK
    )
    proposal = verdict.propose_status(Status.NOT_TESTED, EvidenceKind.PRODUCTION_WORKFLOW, passed)
    assert proposal["proposed"] == "PARTIALLY QUALIFIED"
    assert (
        proposal["requires_owner_acceptance"]
        and proposal["ledger_changed"] is False
        and proposal["promotion"] == "NOT AUTHORIZED"
    )
    assert not proposal["eligible_for_promotion_review"]
    standalone = verdict.propose_status(
        Status.NOT_TESTED, EvidenceKind.STANDALONE_FEASIBILITY, passed
    )
    assert standalone["proposed"] == "FEASIBLE"
    offline = verdict.propose_status(Status.NOT_TESTED, EvidenceKind.OFFLINE_CONTRACT, passed)
    assert offline["proposed"] == "NOT TESTED"
    rated = verdict.classify_attempt(
        plan,
        _good_observations(plan),
        verification=OK_REPORT,
        media_reports=MEDIA_OK,
        human_ratings={
            "quality": {"verdict": "PASS", "rated_by": "rob"},
            "usability": {"verdict": "PASS", "rated_by": "rob"},
        },
    )
    eligible = verdict.propose_status(
        Status.PARTIALLY_QUALIFIED,
        EvidenceKind.PRODUCTION_WORKFLOW,
        rated,
        prior_dimensions_qualified=True,
    )
    assert (
        eligible["proposed"] == "QUALIFIED"
        and eligible["eligible_for_promotion_review"]
        and eligible["promotion"] == "NOT AUTHORIZED"
    )
    refused = verdict.propose_status(
        Status.NOT_TESTED,
        EvidenceKind.PRODUCTION_WORKFLOW,
        verdict.classify_attempt(
            plan,
            {**_good_observations(plan), "stop": "device_loss", "artifacts": 0},
            verification=OK_REPORT,
            media_reports=MEDIA_OK,
        ),
    )
    assert refused["proposed"] == "NO-GO"
    unknown = verdict.propose_status(
        Status.HOLD,
        EvidenceKind.PRODUCTION_WORKFLOW,
        verdict.classify_attempt(
            plan,
            _good_observations(plan),
            verification={"status": evidence.INCOMPLETE, "problems": []},
            media_reports=[],
        ),
    )
    assert unknown["proposed"] == "HOLD"


# ------------------------------------------------------------------------------------------------------ comparator


def _ran(
    tmp_path: Path,
    name: str,
    *,
    scenario: str = "success",
    wall: float = 60.0,
    mutate=None,
    probes=None,
):
    root = tmp_path / name
    probes = probes or dryrun.fake_probes()
    plan = dryrun.build_synthetic_plan("IMG-Q0", STAGE_CANARY, root / "assets", probes, LEDGER)
    if mutate:
        mutate(plan)
        plan["digest"] = compare_digest(plan)
    auth = dryrun.synthetic_authorization(plan)
    session = coordinator.Session()
    report = coordinator.run_stage(
        plan,
        auth,
        adapter=coordinator.SimulatedAdapter(scenario, wall_seconds=wall),
        probes=probes,
        evidence_root=root / "ev",
        confirm=lambda phrase: phrase,
        session=session,
        ledger=LEDGER,
        now=lambda: dryrun.EPOCH + timedelta(minutes=10),
        verify_hashes=False,
    )
    assert report["status"] in (coordinator.RAN, coordinator.NO_GO), report
    return root / "ev" / report["attempt"]


def compare_digest(plan):
    from tools.qualification.system840 import plan as plan_mod

    return plan_mod.digest_of(plan)


def test_identical_conditions_compare_unchanged_and_never_claim_significance(tmp_path) -> None:
    before, after = _ran(tmp_path, "a"), _ran(tmp_path, "b")
    report = compare.compare(before, after)
    assert report["claims_significance"] is False
    verdicts = {m["metric"]: m["verdict"] for m in report["metrics"]}
    assert verdicts["execution_duration_seconds"] == "unchanged"
    assert verdicts["artifacts_per_admitted_attempt"] == "unchanged"
    assert verdicts["image_quality_rating"] == "inconclusive"  # no ratings recorded
    assert compare.exit_code(report) == compare.EXIT_OK


def test_degradation_and_improvement_are_detected_within_tolerance_rules(tmp_path) -> None:
    fast, slow = _ran(tmp_path, "fast", wall=60.0), _ran(tmp_path, "slow", wall=120.0)
    worse = {m["metric"]: m["verdict"] for m in compare.compare(fast, slow)["metrics"]}
    better = {m["metric"]: m["verdict"] for m in compare.compare(slow, fast)["metrics"]}
    assert (
        worse["execution_duration_seconds"] == "degraded"
        and better["execution_duration_seconds"] == "improved"
    )
    assert compare.exit_code(compare.compare(fast, slow)) == compare.EXIT_DEGRADED
    nearly = _ran(tmp_path, "near", wall=62.0)
    assert {m["metric"]: m["verdict"] for m in compare.compare(fast, nearly)["metrics"]}[
        "execution_duration_seconds"
    ] == "unchanged"
    broken = _ran(tmp_path, "broken", scenario="device_loss")
    result = {m["metric"]: m["verdict"] for m in compare.compare(fast, broken)["metrics"]}
    assert (
        result["artifacts_per_admitted_attempt"] == "degraded"
        and result["crash_count"] == "degraded"
    )
    assert result["error_count"] == "degraded"


def test_different_prompt_seed_model_or_benchmark_is_not_comparable(tmp_path) -> None:
    base = _ran(tmp_path, "base")
    for label, change in {
        "seed": lambda p: p["cases"][0]["seeds"].append(7),
        "prompt": lambda p: p["cases"][0]["prompts"].update(positive="other"),
        "model": lambda p: p["cases"][0]["model"].update(sha256="1" * 64),
        "settings": lambda p: p["cases"][0]["settings"].update(steps=30),
    }.items():
        other = _ran(tmp_path, f"other-{label}", mutate=change)
        with pytest.raises(compare.Incomparable, match="not aligned"):
            compare.compare(base, other)


def test_a_different_benchmark_version_is_never_aligned(tmp_path) -> None:
    plan = _plan(tmp_path)
    other = copy.deepcopy(plan)
    other["benchmark_version"] = "9.9"
    assert any("benchmark_version" in p for p in compare.alignment_problems(plan, other))
    assert compare.alignment_problems(plan, copy.deepcopy(plan)) == []


def test_hardware_or_runtime_differences_make_timing_and_resources_inconclusive(tmp_path) -> None:
    before = _ran(tmp_path, "h1")
    other_gpu = dryrun.fake_probes(
        gpu=lambda: {
            "name": "RTX 5090",
            "driver": "2",
            "total_mib": 32768.0,
            "used_mib": 100.0,
            "free_mib": 30000.0,
            "uuid": "x",
        }
    )
    after = _ran(tmp_path, "h2", wall=10.0, probes=other_gpu)
    report = compare.compare(before, after)
    verdicts = {m["metric"]: m["verdict"] for m in report["metrics"]}
    assert report["context_differences"]
    assert verdicts["execution_duration_seconds"] == "inconclusive"
    assert verdicts["gpu_vram_peak_mib"] == "inconclusive"
    assert (
        verdicts["artifacts_per_admitted_attempt"] == "unchanged"
    )  # hardware-independent metrics still compare


def test_single_stochastic_sample_is_not_an_improvement(tmp_path) -> None:
    metric = next(m for m in compare.METRICS if m.name == "image_quality_rating")
    single = compare._judge(metric, 2.0, 4.5, same_hardware=True, old_n=1, new_n=1)
    assert single["verdict"] == "inconclusive" and "single stochastic sample" in single["reason"]
    many = compare._judge(metric, 2.0, 4.5, same_hardware=True, old_n=3, new_n=3)
    assert many["verdict"] == "improved"


def test_unsealed_or_tampered_evidence_is_refused_and_raw_evidence_is_untouched(tmp_path) -> None:
    before, after = _ran(tmp_path, "r1"), _ran(tmp_path, "r2")
    snapshot = {p: p.read_bytes() for p in after.rglob("*") if p.is_file()}
    report = compare.compare(before, after)
    out = tmp_path / "out" / "comparison.json"
    compare.write_comparison(report, out)
    assert json.loads(out.read_text())["arm_id"] == "IMG-Q0"
    assert {
        p: p.read_bytes() for p in after.rglob("*") if p.is_file()
    } == snapshot  # raw evidence unchanged
    assert evidence.verify_attempt(after)["status"] == evidence.OK
    with pytest.raises(evidence.ArchiveRefused, match="already exists"):
        compare.write_comparison(report, out)
    with pytest.raises(evidence.ArchiveRefused, match="inside the evidence"):
        compare.write_comparison(report, after / "comparison.json")
    (after / "artifacts" / "artifact-0.png").write_bytes(b"tampered")
    with pytest.raises(compare.Incomparable, match="TAMPERED"):
        compare.compare(before, after)
    (before / evidence.COMPLETE).unlink()
    with pytest.raises(compare.Incomparable, match="INCOMPLETE"):
        compare.compare(before, tmp_path / "missing")


def test_value_absent_on_one_side_is_inconclusive() -> None:
    metric = next(m for m in compare.METRICS if m.name == "operator_interventions")
    assert (
        compare._judge(metric, None, 1, same_hardware=True, old_n=0, new_n=0)["verdict"]
        == "inconclusive"
    )
    assert (
        compare._judge(metric, 0, 2, same_hardware=True, old_n=0, new_n=0)["verdict"] == "degraded"
    )
    flag = next(m for m in compare.METRICS if m.name == "queue_history_integrity")
    assert (
        compare._judge(flag, True, False, same_hardware=True, old_n=0, new_n=0)["verdict"]
        == "degraded"
    )
    assert (
        compare._judge(flag, False, True, same_hardware=True, old_n=0, new_n=0)["verdict"]
        == "improved"
    )


def test_simulated_adapter_telemetry_helper_roundtrip() -> None:
    samples = [
        {"t": float(t), "commit_fraction": 0.5, "available_ram_mib": 16000, "vram_used_mib": 9000}
        for t in range(0, 61, 2)
    ]
    assert (
        safety.evaluate_telemetry(
            samples,
            dryrun.LIMITS_GPU,
            {"cadence_seconds": 2, "max_gap_seconds": 5, "required_availability": 0.99},
        )["stop"]
        is None
    )
    assert copy.deepcopy(samples) == samples
