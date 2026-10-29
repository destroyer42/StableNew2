"""Synthetic qualification proof; no backend, operator data or invented historical pairs."""

import copy

import pytest

from src.gui.learning_state import LearningExperiment, LearningVariant
from src.learning.evidence_proposals import freeze_proposal_context
from src.learning.experiment_execution import freeze_snapshot, snapshot_digest
from src.learning.qualification_review import project_qualification


@pytest.fixture
def study(tmp_path):
    identity = {
        "kind": "model",
        "key": "model:sdxl:model",
        "model_key": "model",
        "display_name": "model.safetensors",
        "sha256": "a" * 64,
        "family": "sdxl",
    }
    snapshot = {
        "stage": "txt2img",
        "variable_under_test": "Steps",
        "variant_values": [20, 24],
        "images_per_value": 6,
        "model_identity": identity,
        "baseline_config": {"txt2img": {"model": "model.safetensors", "steps": 20}},
        "prompt_text": "lighthouse",
        "seed_policy": {"requested_sample_count": 6},
    }
    proposal = {
        "contract": "qualification_proposal/1",
        "status": "draft",
        "proposal_id": "proposal",
        "variable": "steps",
        "values": [20, 24],
        "images_per_value": 6,
        "identity": identity,
    }
    snapshot["evidence_proposal"] = freeze_proposal_context(proposal, snapshot, "test")
    experiment = LearningExperiment(
        name="Steps",
        experiment_id="exp",
        values=[20, 24],
        variable_under_test="Steps",
        images_per_value=6,
        execution_snapshot_json=freeze_snapshot(snapshot),
    )
    variants, ratings = [], {}
    for value in (20, 24):
        variant = LearningVariant(
            experiment_id="exp",
            variant_id=f"v{value}",
            job_id=f"j{value}",
            param_value=value,
            status="completed",
            executed_config={"txt2img": {"model": "model.safetensors", "steps": value}},
        )
        samples = []
        for i in range(6):
            path = tmp_path / f"{value}-{i}.png"
            path.write_bytes(b"synthetic")
            variant.image_refs.append(str(path))
            samples.append(
                {"path": str(path), "seed": 42 + i, "sample_index": i, "job_id": variant.job_id}
            )
            ratings[str(path)] = {"overall_rating": 3 if value == 20 else 4}
        variant.execution_metadata = {
            "controlled_evidence_valid": True,
            "actual_all_seeds": list(range(42, 48)),
            "runtime_launch_profile": "same-launch",
            "qualification_tested_value_verified": True,
            "qualification_setting_evidence": [
                {
                    "field": "steps",
                    "tested": True,
                    "status": "matched",
                    "selected": value,
                    "compiled_njr": value,
                    "dispatched_request": value,
                    "backend_reported": value,
                }
            ],
            "qualification_samples": {
                "contract": "learning_samples/1",
                "experiment_id": "exp",
                "variant_id": variant.variant_id,
                "job_id": variant.job_id,
                "snapshot_sha256": snapshot_digest(experiment.execution_snapshot_json),
                "runtime_before": {
                    "pid": 100,
                    "started": 1000,
                    "ready_epoch": 1,
                    "endpoint": "http://test",
                    "backend": "forge_webui",
                },
                "runtime_after": {
                    "pid": 100,
                    "started": 1000,
                    "ready_epoch": 1,
                    "endpoint": "http://test",
                    "backend": "forge_webui",
                },
                "samples": samples,
            },
        }
        variants.append(variant)
    return experiment, variants, ratings


def test_six_pairs_use_observed_identity_and_pass_only_followup_screen(study):
    e, plan, ratings = study
    result = project_qualification(e, plan, ratings)
    assert len(result.pairs) == result.rated_pairs == 6
    assert result.outcome == "Follow-up supported"
    assert result.next_action == "Investigate Further"
    assert result.comparisons[0].wins == 6
    assert result.comparisons[0].mean_difference == 1


def test_shuffling_images_and_proof_rows_preserves_exact_pair_identities(study):
    e, plan, ratings = study
    before = project_qualification(e, plan, ratings)
    plan[1].image_refs.reverse()
    plan[0].execution_metadata["qualification_samples"]["samples"].reverse()
    assert project_qualification(e, plan, ratings).pairs == before.pairs


def test_historical_vectors_are_readable_but_not_positional_pair_proof(study):
    e, plan, ratings = study
    for variant in plan:
        variant.execution_metadata.pop("qualification_samples")
    result = project_qualification(e, plan, ratings)
    assert not result.pairs
    assert len(result.samples) == 12
    assert "Cannot verify matched pairs" in result.reason
    assert result.next_action == "Inspect Execution Evidence"


@pytest.mark.parametrize(
    "fault", ["seed", "job", "duplicate", "settings", "launch", "missing", "snapshot", "failed"]
)
def test_invalid_proof_is_excluded_and_never_supports_inference(study, fault):
    e, plan, ratings = study
    variant = plan[1]
    proof = variant.execution_metadata["qualification_samples"]
    if fault == "seed":
        proof["samples"][0]["seed"] = 999
    elif fault == "job":
        proof["job_id"] = "other"
    elif fault == "duplicate":
        proof["samples"][0] = copy.deepcopy(proof["samples"][1])
    elif fault == "settings":
        variant.execution_metadata["qualification_setting_evidence"][0]["backend_reported"] = 25
    elif fault == "launch":
        variant.execution_metadata["runtime_launch_profile"] = "restarted"
    elif fault == "missing":
        from pathlib import Path

        Path(variant.image_refs[0]).unlink()
    elif fault == "snapshot":
        proof["snapshot_sha256"] = "wrong"
    else:
        variant.status = "failed"
    result = project_qualification(e, plan, ratings)
    assert result.outcome == "Execution evidence invalid"
    assert result.next_action == "Inspect Execution Evidence"
    assert result.exclusions


@pytest.mark.parametrize(
    "deltas,expected",
    [
        ([1] * 6, True),
        ([1] * 5 + [0], True),
        ([1, 1, 1, 1, 1, -4], False),
        ([2, 2, 2, 2, -1, -1], False),
        ([0] * 6, False),
    ],
)
def test_screen_reports_both_thresholds_ties_are_not_wins(study, deltas, expected):
    e, plan, ratings = study
    for ref, delta in zip(plan[1].image_refs, deltas, strict=True):
        base = 5 if delta < -2 else 3
        index = plan[1].image_refs.index(ref)
        ratings[plan[0].image_refs[index]]["overall_rating"] = base
        ratings[ref]["overall_rating"] = base + delta
    result = project_qualification(e, plan, ratings)
    assert (result.outcome == "Follow-up supported") is expected
    assert result.comparisons[0].ties == deltas.count(0)


def test_unsaved_invalid_ratings_count_no_evidence(study):
    e, plan, ratings = study
    ratings.pop(plan[1].image_refs[0])
    ratings[plan[1].image_refs[1]]["overall_rating"] = True
    result = project_qualification(e, plan, ratings)
    assert result.rated_pairs == 4
    assert result.outcome == "Needs ratings"
    assert result.next_action == "Finish Rating"


@pytest.mark.parametrize("arms,count", [(2, 10), (3, 5), (4, 5)])
def test_other_designs_keep_frozen_control_comparisons_descriptive(study, tmp_path, arms, count):
    from src.learning.experiment_execution import thaw_snapshot

    e, plan, ratings = study
    snapshot = thaw_snapshot(e.execution_snapshot_json)
    values = [20, 24, 28, 32][:arms]
    snapshot.update(
        variant_values=values, images_per_value=count, seed_policy={"requested_sample_count": count}
    )
    proposal = snapshot.pop("evidence_proposal")
    proposal.update(values=values, images_per_value=count)
    snapshot["evidence_proposal"] = freeze_proposal_context(proposal, snapshot, "descriptive")
    e.execution_snapshot_json = freeze_snapshot(snapshot)
    e.values, e.images_per_value = values, count
    template = copy.deepcopy(plan[0])
    plan.clear()
    for value in values:
        variant = copy.deepcopy(template)
        variant.param_value = value
        variant.variant_id, variant.job_id = f"v{value}", f"j{value}"
        variant.executed_config["txt2img"]["steps"] = value
        variant.image_refs = []
        rows = []
        for index in range(count):
            path = tmp_path / f"descriptive-{value}-{index}.png"
            path.write_bytes(b"synthetic")
            variant.image_refs.append(str(path))
            rows.append(
                {
                    "path": str(path),
                    "seed": 42 + index,
                    "sample_index": index,
                    "job_id": variant.job_id,
                }
            )
            ratings[str(path)] = {"overall_rating": 3 if value == 20 else 4}
        meta = variant.execution_metadata
        for key in ("selected", "compiled_njr", "dispatched_request", "backend_reported"):
            meta["qualification_setting_evidence"][0][key] = value
        meta["actual_all_seeds"] = list(range(42, 42 + count))
        meta["qualification_samples"].update(
            variant_id=variant.variant_id,
            job_id=variant.job_id,
            snapshot_sha256=snapshot_digest(e.execution_snapshot_json),
            samples=rows,
        )
        plan.append(variant)
    result = project_qualification(e, plan, ratings)
    assert len(result.pairs) == (arms - 1) * count
    assert result.rated_pairs == result.expected_pairs
    assert result.outcome == "Unsupported screening design"
    assert all(p.control.value == 20 for p in result.pairs)
    assert [c.value for c in result.comparisons] == values[1:]


@pytest.mark.parametrize("during", [True, False])
def test_backend_restart_with_same_profile_is_not_controlled(study, during):
    e, plan, ratings = study
    proof = plan[1].execution_metadata["qualification_samples"]
    proof["runtime_after"]["ready_epoch"] = 2
    if not during:
        proof["runtime_before"]["ready_epoch"] = 2
    result = project_qualification(e, plan, ratings)
    assert result.outcome == "Execution evidence invalid"
    assert result.next_action == "Inspect Execution Evidence"


def test_screen_inspector_reuses_verified_projection_and_stays_json_serializable(study):
    import json

    from src.learning.setting_evidence import inspect_experiment

    e, plan, ratings = study
    before = inspect_experiment(e, plan, ratings)
    assert before["mean_improvement"] == 1
    json.dumps(before)
    plan[1].execution_metadata.pop("qualification_samples")
    assert inspect_experiment(e, plan, ratings)["mean_improvement"] is None
