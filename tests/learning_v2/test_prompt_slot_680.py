"""Controlled text variation uses the canonical Matrix/intent machinery without fan-out."""

from types import SimpleNamespace

import pytest

from src.image_backends.model_policy import resolve_model_policy
from src.learning.prompt_slot_experiment import PromptSlotDesign, freeze_candidates


def policy():
    return resolve_model_policy(
        "test.safetensors",
        family_lookup=lambda _: SimpleNamespace(
            status=SimpleNamespace(value="resolved"), family=SimpleNamespace(value="sdxl")
        ),
    )


def design(**kwargs):
    return PromptSlotDesign(
        template="A knight, [[expression]], natural lighting.",
        slot="expression",
        candidates=("calm", "angry"),
        **kwargs,
    )


def test_custom_slot_freezes_order_and_only_declared_substitution():
    frozen = freeze_candidates(design(), policy(), {}, negative="fixed negative")
    assert [item["value"] for item in frozen["candidates"]] == ["calm", "angry"]
    assert [item["authored"] for item in frozen["candidates"]] == [
        "A knight, calm, natural lighting.",
        "A knight, angry, natural lighting.",
    ]
    assert len({item["positive"] for item in frozen["candidates"]}) == 2
    assert {item["negative"] for item in frozen["candidates"]} == {"fixed negative"}


@pytest.mark.parametrize(
    "values", [("one",), ("same", "same"), ("one", " "), tuple(str(i) for i in range(9))]
)
def test_candidate_bounds(values):
    with pytest.raises(ValueError):
        freeze_candidates(PromptSlotDesign("[[x]]", "x", values), policy(), {})


@pytest.mark.parametrize(
    "text", ["[[other]]", "<lora:x:1>", "embedding:x", "[[broken]", "<hypernet:x:1>"]
)
def test_directives_cannot_be_introduced(text):
    with pytest.raises(ValueError):
        freeze_candidates(PromptSlotDesign("[[x]]", "x", ("ordinary", text)), policy(), {})


def test_golden_custom_preview_and_canonical_admission(tmp_path):
    from src.gui.learning_state import LearningExperiment, LearningVariant
    from src.learning.experiment_execution import thaw_snapshot
    from tests.learning_v2.test_learning_independent_baseline_650 import Bench

    bench = Bench(tmp_path)
    bench.pipeline["txt2img"].update(
        seed=101,
        steps=30,
        cfg_scale=6,
        sampler_name="DPM++ 2M",
        scheduler="Karras",
        width=1024,
        height=1024,
    )
    bench.preview(
        variable="Prompt Slot",
        images=3,
        study_type="prompt_slot",
        prompt_slot={
            "template": "A knight, [[expression]], natural lighting.",
            "slot": "expression",
            "candidates": [
                "calm and confident",
                "angry and battle-ready",
                "exhausted but determined",
                "quietly triumphant",
            ],
        },
    )
    experiment = bench.state.current_experiment
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    assert snapshot["study_type"] == "prompt_slot"
    assert snapshot["variant_values"] == ["A", "B", "C", "D"]
    assert not bench.service.submit_njrs.called
    bench.pipeline["txt2img"].update(model="changed", seed=9, steps=1, cfg_scale=12)
    jobs = bench.run()
    assert len(jobs) == 4 and sum(job.workload.images_per_prompt for job in jobs) == 12
    assert {job.seed for job in jobs} == {101}
    assert {job.stages[0].steps for job in jobs} == {30}
    assert len({job.positive_prompt for job in jobs}) == 4
    assert bench.service.submit_njrs.call_count == 1
    bench.controller.run_plan()
    assert bench.service.submit_njrs.call_count == 1
    restored = LearningExperiment.from_dict(experiment.to_dict())
    restored_variants = [LearningVariant.from_dict(v.to_dict()) for v in bench.state.plan]
    assert restored.execution_snapshot_json == experiment.execution_snapshot_json
    assert [v.job_id for v in restored_variants] == [v.job_id for v in bench.state.plan]


@pytest.mark.parametrize(
    "template,slot,fixed",
    [("no slot", "x", {}), ("[[a]] [[b]]", "a", {}), ("[[[a]]]", "a", {}), ("[[a]]", "b", {})],
)
def test_missing_malformed_and_unfixed_slots_refuse(template, slot, fixed):
    with pytest.raises(ValueError):
        freeze_candidates(PromptSlotDesign(template, slot, ("one", "two"), fixed), policy(), {})


def test_all_occurrences_and_aliases_share_one_value():
    frozen = freeze_candidates(
        PromptSlotDesign("[[A b]] / [[a_b]] / [[fixed]]", "a_b", ("One", "one"), {"fixed": "same"}),
        policy(),
        {},
    )
    assert [c["authored"] for c in frozen["candidates"]] == ["One / One / same", "one / one / same"]


@pytest.mark.parametrize("images", [0, 4, True])
def test_image_cap(images):
    with pytest.raises(ValueError):
        freeze_candidates(design(images_per_candidate=images), policy(), {})


def test_optimizer_and_unknown_model_refuse():
    with pytest.raises(ValueError, match="optimizer"):
        freeze_candidates(design(), policy(), {"prompt_optimizer": {"enabled": True}})
    with pytest.raises(ValueError, match="registry"):
        freeze_candidates(design(), resolve_model_policy("unknown"), {})


def test_readback_seed_and_launch_boundaries(tmp_path):
    import copy

    from src.learning.experiment_execution import thaw_snapshot
    from src.learning.experiment_reconciliation import completion_evidence
    from src.learning.prompt_slot_experiment import prompt_readback_reason
    from tests.learning_v2.test_learning_independent_baseline_650 import Bench

    bench = Bench(tmp_path)
    bench.preview(
        variable="Prompt Slot",
        images=1,
        study_type="prompt_slot",
        prompt_slot={"template": "A [[x]] knight", "slot": "x", "candidates": ["calm", "angry"]},
    )
    bench.run()
    experiment = bench.state.current_experiment
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    variant = bench.state.plan[0]
    candidate = snapshot["prompt_slot"]["candidates"][0]
    readback = {
        "final_prompt": candidate["expected_positive"],
        "final_negative_prompt": candidate["expected_negative"],
    }
    assert prompt_readback_reason(snapshot, variant, readback) == ""
    assert "unavailable" in prompt_readback_reason(snapshot, variant, {})
    assert "mismatch" in prompt_readback_reason(
        snapshot, variant, {**readback, "final_prompt": "other"}
    )
    result = {
        "metadata": {
            **readback,
            "all_seeds": [101],
            "all_subseeds": [snapshot["seed_policy"]["requested_subseed"]],
        },
        "variants": [{**readback, "runtime_admission": {"launch_profile": "one"}}],
    }
    proof = completion_evidence(experiment, variant, result)
    assert proof.execution_metadata["controlled_evidence_valid"] is True
    experiment.metadata.update(observed_seed_vector=[101], observed_launch_profile="one")
    bad_seed = copy.deepcopy(result)
    bad_seed["metadata"]["all_seeds"] = [102]
    assert (
        completion_evidence(experiment, variant, bad_seed).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )
    bad_launch = copy.deepcopy(result)
    bad_launch["variants"][0]["runtime_admission"]["launch_profile"] = "two"
    assert (
        completion_evidence(experiment, variant, bad_launch).execution_metadata[
            "controlled_evidence_valid"
        ]
        is False
    )


def native_plan(tmp_path):
    import json

    from src.pipeline.global_prompt_policy import apply_global_prompt_policy
    from tests.learning_v2.test_learning_independent_baseline_650 import Bench
    from tests.learning_v2.test_model_comparison_140 import experiment as write_pack

    write_pack(tmp_path)
    path = tmp_path / "pack.json"
    document = json.loads(path.read_text())
    document["pack_data"]["slots"][0]["text"] = "A knight, [[expression]], in [[place]]."
    document["pack_data"]["matrix"]["slots"].append(
        {"name": "expression", "values": ["original one", "original two"]}
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    original = path.read_bytes()
    bench = Bench(tmp_path)
    bench.pipeline = apply_global_prompt_policy(
        bench.pipeline,
        positive_enabled=True,
        positive_text="GLOBAL POSITIVE",
        negative_enabled=True,
        negative_text="GLOBAL NEGATIVE",
    )
    bench.pipeline["txt2img"].update(seed=101, steps=30, cfg_scale=6)
    bench.preview(
        variable="Prompt Slot",
        images=3,
        study_type="prompt_slot",
        prompt_source="pack",
        selected_prompt_pack_path=str(path),
        selected_prompt_pack_name="study",
        selected_prompt_index=0,
        selected_prompt_text="A knight [[expression]]",
        selected_negative_prompt="negative_embed bad",
        prompt_slot={
            "template": "display only",
            "slot": "expression",
            "fixed_slots": {"place": "forest"},
            "candidates": [
                "calm and confident",
                "angry and battle-ready",
                "exhausted but determined",
                "quietly triumphant",
            ],
        },
    )
    assert path.read_bytes() == original
    return bench, path, original


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_native_source_freezes_one_axis_and_never_reopens_during_run(tmp_path, change):
    from src.learning.experiment_execution import thaw_snapshot
    from src.learning.experiment_freeze import freeze_prompt_pack_source

    bench, path, original = native_plan(tmp_path)
    snapshot = thaw_snapshot(bench.state.current_experiment.execution_snapshot_json)
    assert len(snapshot["prompt_slot"]["candidates"]) == 4
    assert all("forest" in c["positive"] for c in snapshot["prompt_slot"]["candidates"])
    ordinary = freeze_prompt_pack_source(
        {
            "prompt_source": "pack",
            "selected_prompt_pack_path": str(path),
            "selected_prompt_pack_name": "study",
            "selected_prompt_index": 0,
        }
    )
    assert "original one" in ordinary["rendered_positive_prompt"]
    if change == "edit":
        path.write_text("deliberately no longer a valid PromptPack", encoding="utf-8")
    else:
        path.unlink()
    before = path.read_bytes() if path.exists() else None
    jobs = bench.run()
    assert len(jobs) == 4 and sum(job.workload.images_per_prompt for job in jobs) == 12
    assert len({job.positive_prompt for job in jobs}) == 4
    assert {job.seed for job in jobs} == {101}
    for entry in snapshot["prompt_slot"]["candidates"]:
        assert entry["negative"].count("bad") == 1
        assert entry["negative"].count("negative_embed") == 1
        assert entry["expected_negative"].count("GLOBAL NEGATIVE") == 1
        assert entry["expected_positive"].count("GLOBAL POSITIVE") == 1
    assert (path.read_bytes() if path.exists() else None) == before


def test_one_bad_variant_or_identity_swap_admits_zero(tmp_path, monkeypatch):
    bench, _path, _original = native_plan(tmp_path)
    from src.learning.learning_controller_services import prompt_slot

    original = prompt_slot._materialize

    def changed(*args):
        record = original(*args)
        if args[-1].param_value == "C":
            raise ValueError("simulated parity failure")
        return record

    monkeypatch.setattr(prompt_slot, "_materialize", changed)
    with pytest.raises(ValueError, match="parity"):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


def test_prompt_ratings_remain_local_and_cannot_be_published_or_recommended(tmp_path):
    import copy

    from src.generation_profiles.identity import ModelIdentityResolver
    from src.generation_profiles.store import GenerationProfileStore
    from src.learning.learning_record import LearningRecordWriter
    from src.learning.profile_publication import ProfilePublicationService
    from src.learning.prompt_slot_experiment import conclusion
    from src.learning.recommendation_engine import RecommendationEngine

    bench, _path, _original = native_plan(tmp_path)
    bench.run()
    experiment = bench.state.current_experiment
    bench.controller._learning_record_writer = LearningRecordWriter(tmp_path / "ratings.jsonl")
    rows, details = [], {}
    for i, variant in enumerate(bench.state.plan):
        variant.status = "completed"
        variant.image_refs = [f"sample-{i}.png"]
        variant.completed_images = 1
        variant.execution_metadata.update(
            controlled_evidence_valid=True,
            variable_validation_reason="valid",
            actual_all_seeds=[101, 102, 103],
        )
        rating = 5 if i == 1 else 3
        record, _, _ = bench.controller.build_rating_record(
            experiment, variant, variant.image_refs[0], rating, "", None
        )
        assert record.metadata["record_kind"] == "learning_experiment_rating"
        assert record.metadata["study_type"] == "prompt_slot"
        assert record.metadata["prompt_slot"]["candidate_label"] == chr(65 + i)
        assert bench.controller._learning_record_writer.append_record(record)
        rows.append(__import__("json").loads(record.to_json()))
        details[variant.image_refs[0]] = {"overall_rating": rating}
    result = conclusion(bench.state.plan, details, {})
    assert result["best_value"] == "B" and result["saved"] == 4
    assert "Highest rated in this experiment" in result["message"]
    assert not bench.controller.get_recommendations_for_current_prompt()
    recommendation = RecommendationEngine(tmp_path / "ratings.jsonl").recommend(
        "a portrait", "txt2img"
    )
    assert not recommendation.recommendations
    resolver = ModelIdentityResolver(
        policy_resolver=lambda _: policy(), sha_lookup=lambda _: "a" * 64
    )
    proposal = ProfilePublicationService(
        GenerationProfileStore(tmp_path / "profiles"), resolver
    ).evaluate(rows, "test.safetensors")
    assert not proposal.ready and not proposal.settings
    uncontrolled = copy.deepcopy(bench.state.plan)
    uncontrolled[1].execution_metadata["controlled_evidence_valid"] = False
    assert conclusion(uncontrolled, details, {})["best_value"] is None
    assert (
        conclusion(bench.state.plan, {}, {"draft:sample-1.png": {"overall_rating": 5}})["saved"]
        == 0
    )


def test_restart_reconciles_exact_sqlite_jobs_without_recompile(tmp_path, monkeypatch):
    import copy
    import json

    from src.learning.execution_controller import LearningExecutionController
    from src.learning.experiment_store import LearningExperimentStore
    from src.queue.job_model import JobStatus
    from src.queue.job_repository import JobRepository
    from tests.learning_v2.test_learning_recovery_260 import (
        RepositoryService,
        recreated,
        transition,
    )

    bench, path, _original = native_plan(tmp_path)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    try:
        service = RepositoryService(repository)
        bench.controller.pipeline_controller = SimpleNamespace(_job_service=service)
        bench.controller.execution_controller = LearningExecutionController(bench.state, service)
        bench.controller.run_plan()
        assert len(service.calls) == 1 and len(repository.list_job_models()) == 4
        bench.state.selected_variant = bench.state.plan[1]
        bench.state.review_drafts = {"retained": {"rating": 4}}
        payload = json.loads(json.dumps(bench.controller.export_resume_state()))
        store = LearningExperimentStore(tmp_path / "experiments")
        handle = store.save_session(
            display_name="Prompt Slot",
            payload=payload,
            experiment_id=bench.state.current_experiment.experiment_id,
        )
        expected = copy.deepcopy(payload)
        candidate = json.loads(bench.state.current_experiment.execution_snapshot_json)[
            "prompt_slot"
        ]["candidates"][0]
        completed = {
            "variants": [
                {
                    "output_paths": [
                        str(tmp_path / "0.png"),
                        str(tmp_path / "1.png"),
                        str(tmp_path / "2.png"),
                    ],
                    "all_seeds": [101, 102, 103],
                    "all_subseeds": [700, 701, 702],
                    "final_prompt": candidate["expected_positive"],
                    "final_negative_prompt": candidate["expected_negative"],
                    "runtime_admission": {"launch_profile": "one"},
                }
            ]
        }
        transition(repository, bench.state.plan[0].job_id, JobStatus.COMPLETED, result=completed)
        path.unlink()
        restored, fresh_service = recreated(store.load_session(handle.experiment_id), repository)
        assert [v.job_id for v in restored.learning_state.plan] == [
            v.job_id for v in bench.state.plan
        ]
        assert restored.learning_state.selected_variant.param_value == "B"
        assert restored.learning_state.review_drafts == {"retained": {"rating": 4}}
        assert (
            restored.learning_state.current_experiment.execution_snapshot_json
            == bench.state.current_experiment.execution_snapshot_json
        )
        assert (
            restored.learning_state.plan[0].execution_metadata["controlled_evidence_valid"] is True
        )
        assert not fresh_service.calls
        assert store.load_session(handle.experiment_id) == expected
    finally:
        repository.close()


@pytest.mark.parametrize("field", ["compiled_prompt_slot_plan", "stage", "variant_id"])
def test_corrupt_frozen_plan_and_identity_refuse_before_admission(tmp_path, field):
    from src.learning.experiment_execution import freeze_snapshot, thaw_snapshot

    bench, _path, _original = native_plan(tmp_path)
    experiment = bench.state.current_experiment
    snapshot = thaw_snapshot(experiment.execution_snapshot_json)
    if field == "compiled_prompt_slot_plan":
        snapshot[field][0]["positive"] = "changed"
    elif field == "stage":
        snapshot[field] = "img2img"
    else:
        bench.state.plan[0].variant_id = "different identity"
    experiment.execution_snapshot_json = freeze_snapshot(snapshot)
    with pytest.raises(ValueError):
        bench.controller.run_plan()
    assert not bench.service.submit_njrs.called


@pytest.mark.parametrize(
    "candidate", ["(armor:1.2)", "[red:blue:0.5]", "portrait BREAK landscape", "__wildcard__"]
)
def test_other_structured_directives_refuse(candidate):
    with pytest.raises(ValueError, match="directives"):
        freeze_candidates(PromptSlotDesign("A [[x]]", "x", ("ordinary", candidate)), policy(), {})


def test_natural_punctuation_capitalization_and_fixed_alias_conflicts():
    values = ("calm (almost serene), head held high; smiling!", "Calm: head held high.")
    assert (
        len(
            freeze_candidates(PromptSlotDesign("A [[x]] knight", "x", values), policy(), {})[
                "candidates"
            ]
        )
        == 2
    )
    with pytest.raises(ValueError, match="conflicting"):
        freeze_candidates(
            PromptSlotDesign("[[x]] [[a b]]", "x", ("one", "two"), {"a b": "one", "a_b": "two"}),
            policy(),
            {},
        )
    with pytest.raises(ValueError, match="embedding"):
        freeze_candidates(
            PromptSlotDesign("[[x]]", "x", ("one", "EasyNegative")),
            policy(),
            {},
            embedding_names=("EasyNegative",),
        )


def test_global_unresolved_tokens_and_collapsed_prompts_refuse(monkeypatch):
    from src.pipeline.global_prompt_policy import apply_global_prompt_policy

    baseline = apply_global_prompt_policy(
        {},
        positive_enabled=True,
        positive_text="[[unknown]]",
        negative_enabled=False,
        negative_text="",
    )
    with pytest.raises(ValueError, match="global"):
        freeze_candidates(design(), policy(), baseline)
    import src.learning.prompt_slot_experiment as slots

    original = slots.render_pack_intent
    from dataclasses import replace

    monkeypatch.setattr(
        slots,
        "render_pack_intent",
        lambda intent: replace(original(intent), positive="erased variation"),
    )
    with pytest.raises(ValueError, match="collapse"):
        freeze_candidates(design(), policy(), {})


def test_preview_details_and_candidate_captions_obey_visibility(tmp_path):
    from src.learning.preview_summary import build_preview_summary
    from src.learning.prompt_slot_experiment import candidate_caption, visibility_prompt

    bench, _path, _original = native_plan(tmp_path)
    experiment = bench.state.current_experiment
    hidden = build_preview_summary(experiment, bench.state.plan, show_model_names=False)
    visible = build_preview_summary(experiment, bench.state.plan, show_model_names=True)
    assert not hidden.prompt_details
    assert "angry and battle-ready" not in str(hidden)
    assert "angry and battle-ready" in visible.prompt_details
    assert "angry and battle-ready" not in candidate_caption(experiment, "B", visible=False)
    assert "angry and battle-ready" in candidate_caption(experiment, "B", visible=True)
    assert "angry and battle-ready" in visibility_prompt(experiment)


@pytest.mark.parametrize("missing", ["final_prompt", "final_negative_prompt"])
def test_missing_runtime_readback_keeps_results_but_is_uncontrolled(tmp_path, missing):
    from src.learning.experiment_execution import thaw_snapshot
    from src.learning.experiment_reconciliation import completion_evidence

    bench, _path, _original = native_plan(tmp_path)
    bench.run()
    experiment, variant = bench.state.current_experiment, bench.state.plan[0]
    candidate = thaw_snapshot(experiment.execution_snapshot_json)["prompt_slot"]["candidates"][0]
    result = {
        "variants": [
            {
                "final_prompt": candidate["expected_positive"],
                "final_negative_prompt": candidate["expected_negative"],
                "all_seeds": [101, 102, 103],
                "all_subseeds": [700, 701, 702],
            }
        ]
    }
    del result["variants"][0][missing]
    proof = completion_evidence(experiment, variant, result)
    assert proof.status == "uncontrolled"
    assert proof.execution_metadata["controlled_evidence_valid"] is False
    assert "readback" in proof.execution_metadata["variable_validation_reason"]


@pytest.mark.parametrize("count", range(2, 9))
def test_every_approved_candidate_count_and_maximum_image_total(count):
    frozen = freeze_candidates(
        PromptSlotDesign(
            "A [[x]]", "x", tuple(f"candidate {i}" for i in range(count)), images_per_candidate=3
        ),
        policy(),
        {},
    )
    assert len(frozen["candidates"]) == count
    assert count * frozen["images_per_candidate"] <= 24


def test_saved_ratings_survive_new_writer_and_missing_jobs_require_attention(tmp_path):
    import json

    from src.learning.learning_record import LearningRecordWriter
    from src.queue.job_repository import JobRepository
    from tests.learning_v2.test_learning_recovery_260 import recreated

    bench, _path, _original = native_plan(tmp_path)
    bench.run()
    variant = bench.state.plan[0]
    variant.image_refs = [str(tmp_path / "sample.png")]
    variant.execution_metadata.update(
        controlled_evidence_valid=True,
        variable_validation_reason="valid",
        actual_all_seeds=[101, 102, 103],
    )
    record, _, _ = bench.controller.build_rating_record(
        bench.state.current_experiment, variant, variant.image_refs[0], 4, "saved", None
    )
    path = tmp_path / "ratings.jsonl"
    assert LearningRecordWriter(path).append_record(record)
    restored_rating = LearningRecordWriter(path).get_rating_details_for_experiment(
        bench.state.current_experiment.experiment_id
    )
    assert restored_rating[variant.image_refs[0]]["overall_rating"] == 4
    payload = json.loads(json.dumps(bench.controller.export_resume_state()))
    missing = JobRepository(tmp_path / "missing.sqlite3")
    try:
        restored, service = recreated(payload, missing)
        assert all(v.status == "requires_attention" for v in restored.learning_state.plan)
        assert not service.calls
    finally:
        missing.close()


def test_candidate_identity_change_and_fixed_setting_drift_are_uncontrolled(tmp_path):
    import copy

    from src.learning.experiment_execution import thaw_snapshot
    from src.learning.prompt_slot_experiment import prompt_readback_reason

    bench, _path, _original = native_plan(tmp_path)
    bench.run()
    snapshot = thaw_snapshot(bench.state.current_experiment.execution_snapshot_json)
    variant = copy.deepcopy(bench.state.plan[0])
    candidate = snapshot["prompt_slot"]["candidates"][0]
    readback = {
        "final_prompt": candidate["expected_positive"],
        "final_negative_prompt": candidate["expected_negative"],
    }
    variant.variant_id = "different"
    assert "identity" in prompt_readback_reason(snapshot, variant, readback)
    variant = copy.deepcopy(bench.state.plan[0])
    variant.executed_config["txt2img"]["steps"] += 1
    assert "context" in prompt_readback_reason(snapshot, variant, readback)
