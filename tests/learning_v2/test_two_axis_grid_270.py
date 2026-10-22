"""PR-LEARN-GRID-270: two-axis planning, frozen compilation, admission, recovery and rating isolation."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.gui.controllers.learning_controller import LearningController
from src.gui.learning_state import LearningExperiment, LearningState
from src.image_backends.forge_klein_lora import KleinLoraDecision, KleinLoraStatus
from src.learning.execution_controller import LearningExecutionController
from src.learning.experiment_conclusion import build_experiment_conclusion
from src.learning.experiment_execution import thaw_snapshot
from src.learning.learning_record import LearningRecordWriter
from src.learning.recommendation_engine import RecommendationEngine
from src.learning.two_axis_grid import (
    RECORD_KIND,
    STUDY_TYPE,
    parse_axis,
    plan_cells,
    rating_classification,
    variant_label,
)
from src.queue.job_model import JobStatus
from src.queue.job_repository import JobRepository
from tests.learning_v2.test_learning_recovery_260 import RepositoryService, result_for, transition
from tests.learning_v2.test_model_comparison_140 import KLEIN, baseline, policy


def grid_experiment(
    *,
    x=("CFG Scale", (5, 7, 9)),
    y=("Steps", (20, 30, 40)),
    images=2,
    lora=None,
    prompt="portrait, detailed",
):
    return LearningExperiment(
        name="grid",
        experiment_id="grid1",
        stage="txt2img",
        prompt_text=prompt,
        images_per_value=images,
        metadata={
            "study_type": STUDY_TYPE,
            "prompt_source": "custom",
            "grid": {
                "x": {"variable": x[0], "values": list(x[1])},
                "y": {"variable": y[0], "values": list(y[1])},
                "lora_name": lora,
            },
        },
    )


def grid_controller(exp, config=None, *, build=True):
    controller = LearningController(learning_state=LearningState())
    controller._get_baseline_config = lambda: copy.deepcopy(config or baseline())
    controller._learning_policy_resolver = policy
    controller._learning_lora_resolver = lambda name: KleinLoraDecision(
        name, KleinLoraStatus.COMPATIBLE, "fixture"
    )
    controller.known_loras = lambda: ["detail-xl", "style-xl"]
    if build:
        controller.build_plan(exp)
    return controller


def wired(exp, repository, *, config=None):
    controller = grid_controller(exp, config)
    service = RepositoryService(repository)
    controller.pipeline_controller = SimpleNamespace(_job_service=service)
    controller.execution_controller = LearningExecutionController(
        controller.learning_state, service
    )
    controller.execution_controller.set_completion_callback(
        controller._apply_variant_completion_evidence
    )
    controller.execution_controller.set_presentation_callback(
        controller._on_variant_completion_published
    )
    controller.execution_controller.set_failure_callback(controller._on_variant_job_failed)
    return controller, service


@pytest.fixture
def repository(tmp_path):
    repo = JobRepository(tmp_path / "jobs.sqlite3")
    yield repo
    repo.close()


def compiled(controller):
    return [
        controller._build_variant_njr(v, controller.learning_state.current_experiment)
        for v in controller.learning_state.plan
    ]


# ---- A. design and plan ---------------------------------------------------------------------------------------


def test_cfg_by_steps_expands_to_ordered_stable_coordinates():
    x, y = (
        parse_axis({"variable": "CFG Scale", "values": [5, 7, 9]}),
        parse_axis({"variable": "Steps", "values": [20, 30, 40]}),
    )
    cells = plan_cells("grid1", x, y, 2)
    assert len(cells) == 9
    assert [(c.row, c.col) for c in cells] == [(r, c) for r in range(3) for c in range(3)]
    assert [(c.y_value, c.x_value) for c in cells[:4]] == [
        (20, 5.0),
        (20, 7.0),
        (20, 9.0),
        (30, 5.0),
    ]
    assert len({c.cell_id for c in cells}) == 9
    assert [c.cell_id for c in cells] == [c.cell_id for c in plan_cells("grid1", x, y, 2)]
    assert cells[0].cell_id != plan_cells("other", x, y, 2)[0].cell_id


def test_axis_reversal_keeps_each_coordinate_meaning():
    forward = grid_controller(grid_experiment())
    reverse = grid_controller(
        grid_experiment(x=("Steps", (20, 30, 40)), y=("CFG Scale", (5, 7, 9)))
    )
    by_pair = {}
    for record in compiled(forward):
        by_pair[(record.cfg_scale, record.steps)] = record
    for variant, record in zip(reverse.learning_state.plan, compiled(reverse), strict=True):
        assert variant.param_value["x_variable"] == "Steps"
        mirror = by_pair[(record.cfg_scale, record.steps)]
        assert mirror.config["txt2img"]["cfg_scale"] == record.config["txt2img"]["cfg_scale"]
    first = reverse.learning_state.plan[1].param_value
    assert (first["x_value"], first["y_value"]) == (30, 5.0)


@pytest.mark.parametrize(
    "spec",
    [
        {"variable": "CFG Scale", "values": [7, 7.0]},
        {"variable": "CFG Scale", "values": [7]},
        {"variable": "CFG Scale", "values": [3, 4, 5, 6, 7]},
        {"variable": "Steps", "values": [20, 30.5]},
        {"variable": "Steps", "values": [True, 30]},
        {"variable": "Steps", "values": [0, 30]},
        {"variable": "CFG Scale", "values": [7, 7.123]},
        {"variable": "CFG Scale", "values": [7, float("nan")]},
        {"variable": "LoRA Strength", "values": [0, 0.5]},
        {"variable": "Sampler", "values": ["a", "b"]},
        {"variable": "CFG Scale", "start": 5, "end": 10, "step": 0.5},
        {"variable": "CFG Scale", "start": 5, "end": 9, "step": 0},
    ],
)
def test_invalid_axes_are_refused_not_truncated_or_repaired(spec):
    with pytest.raises(ValueError):
        parse_axis(spec)


def test_range_axis_uses_exact_decimal_values():
    axis = parse_axis({"variable": "CFG Scale", "start": 6.1, "end": 6.4, "step": 0.1})
    assert axis.values == (6.1, 6.2, 6.3, 6.4)
    assert parse_axis({"variable": "Steps", "start": 20, "end": 40, "step": 10}).values == (
        20,
        30,
        40,
    )


def test_same_variable_on_both_axes_and_oversized_samples_are_refused():
    cfg = parse_axis({"variable": "CFG Scale", "values": [5, 7]})
    with pytest.raises(ValueError, match="distinct"):
        plan_cells("e", cfg, cfg, 1)
    steps = parse_axis({"variable": "Steps", "values": [20, 30]})
    with pytest.raises(ValueError, match="images per cell"):
        plan_cells("e", cfg, steps, 4)


def test_preview_builds_snapshot_and_makes_zero_queue_calls():
    exp = grid_experiment()
    controller = grid_controller(exp, build=False)
    service = Mock()
    controller.pipeline_controller = SimpleNamespace(_job_service=service)
    controller.build_plan(exp)
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    assert snapshot["study_type"] == STUDY_TYPE
    assert (
        snapshot["two_axis_grid"]["total_cells"] == 9
        and snapshot["two_axis_grid"]["total_images"] == 18
    )
    assert [v.param_value["cell_id"] for v in controller.learning_state.plan] == [
        c["cell_id"] for c in snapshot["two_axis_grid"]["cells"]
    ]
    assert all(
        c["effective"]["steps"] and c["effective"]["cfg_scale"]
        for c in snapshot["two_axis_grid"]["cells"]
    )
    assert (
        service.method_calls == []
        and controller.learning_state.current_experiment.variable_under_test == "CFG Scale x Steps"
    )
    assert not any(v.job_id for v in controller.learning_state.plan)


def test_fixed_model_controls_and_unverified_models_are_refused():
    config = baseline()
    config["txt2img"]["model"] = KLEIN
    with pytest.raises(ValueError):
        grid_controller(grid_experiment(), config)
    config["txt2img"]["model"] = "unknown.safetensors"
    with pytest.raises(ValueError):
        grid_controller(grid_experiment(), config)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["pipeline"].update(upscale_enabled=True),
        lambda c: c["txt2img"].update(enable_hr=True),
        lambda c: c.update(controlnet={"enabled": True}),
    ],
)
def test_unsupported_structure_is_refused_not_silently_disabled(mutate):
    config = baseline()
    mutate(config)
    with pytest.raises(ValueError):
        grid_controller(grid_experiment(), config)


def test_lora_axis_requires_a_known_compatible_lora(monkeypatch):
    exp = grid_experiment(x=("LoRA Strength", (0.4, 0.8)), lora="not-installed")
    with pytest.raises(ValueError, match="LoRA"):
        grid_controller(exp)
    exp = grid_experiment(x=("LoRA Strength", (0.4, 0.8)), lora=None)
    with pytest.raises(ValueError, match="LoRA"):
        grid_controller(exp)
    monkeypatch.setattr(
        "src.learning.model_policy_service.assess_lora_selection",
        lambda *a, **k: SimpleNamespace(blocked=True, blocking="incompatible", exact=True),
    )
    with pytest.raises(ValueError, match="LoRA"):
        grid_controller(grid_experiment(x=("LoRA Strength", (0.4, 0.8)), lora="detail-xl"))


# ---- B. compilation and seeds ---------------------------------------------------------------------------------


def test_both_axes_reach_every_effective_njr_with_one_common_seed_vector():
    controller = grid_controller(grid_experiment())
    records = compiled(controller)
    snapshot = thaw_snapshot(controller.learning_state.current_experiment.execution_snapshot_json)
    seeds = {(r.config["txt2img"]["seed"], r.config["txt2img"]["subseed"]) for r in records}
    assert seeds == {
        (
            snapshot["seed_policy"]["requested_base_seed"],
            snapshot["seed_policy"]["requested_subseed"],
        )
    }
    for variant, record in zip(controller.learning_state.plan, records, strict=True):
        value = variant.param_value
        expected = {value["x_variable"]: value["x_value"], value["y_variable"]: value["y_value"]}
        assert record.cfg_scale == expected["CFG Scale"] == record.config["txt2img"]["cfg_scale"]
        assert record.steps == expected["Steps"] == record.config["txt2img"]["steps"]
        assert record.stages[0].steps == expected["Steps"]
        assert record.images_per_prompt == 2
        assert record.learning_context.variant_value == value
        assert record.positive_prompt == record.config["prompt"] == "portrait, detailed"
        assert record.positive_prompt.count("portrait") == 1
        assert variant.executed_config["txt2img"]["steps"] == expected["Steps"]


@pytest.mark.parametrize(
    "x,y",
    [
        (("CFG Scale", (5, 9)), ("LoRA Strength", (0.4, 0.8))),
        (("Steps", (20, 40)), ("LoRA Strength", (0.4, 0.8))),
    ],
)
def test_lora_strength_axis_executes_one_token_at_the_requested_weight(x, y):
    controller = grid_controller(
        grid_experiment(x=x, y=y, lora="detail-xl", prompt="portrait <lora:style-xl:0.5>")
    )
    for variant, record in zip(controller.learning_state.plan, compiled(controller), strict=True):
        weight = variant.param_value["y_value"]
        assert record.positive_prompt.count("<lora:detail-xl:") == 1
        assert f"<lora:detail-xl:{weight}>" in record.positive_prompt
        assert "<lora:style-xl:0.5>" in record.positive_prompt
        assert record.config["lora_override"] == {"name": "detail-xl", "weight": weight}
        assert {t.name: t.weight for t in record.provenance.lora_tags}["detail-xl"] == weight


def test_policy_that_drops_an_axis_value_refuses_the_whole_grid(monkeypatch):
    from src.image_backends import model_policy

    real = model_policy.apply_model_compile_policy

    def clamp(config):
        real(config)
        config["txt2img"]["steps"] = 25

    monkeypatch.setattr(model_policy, "apply_model_compile_policy", clamp)
    with pytest.raises(ValueError, match="overwritten"):
        grid_controller(grid_experiment())


def test_pack_source_changes_after_preview_cannot_change_run(tmp_path, monkeypatch):
    path = tmp_path / "pack.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_data": {
                    "name": "p",
                    "slots": [{"index": 0, "text": "frozen text", "negative": "bad"}],
                },
                "preset_data": {},
            }
        ),
        encoding="utf-8",
    )
    exp = grid_experiment()
    exp.metadata.update(
        prompt_source="pack",
        selected_prompt_pack_path=str(path),
        selected_prompt_pack_name="p",
        selected_prompt_index=0,
    )
    controller = grid_controller(exp)
    path.write_text("changed", encoding="utf-8")
    monkeypatch.setattr(
        "src.learning.experiment_freeze.load_prompt_pack_document",
        lambda *a, **k: pytest.fail("Run reopened the pack"),
    )
    controller._get_baseline_config = lambda: pytest.fail("Run read live cards")
    assert all("frozen text" in r.positive_prompt for r in compiled(controller))


def test_tampered_or_foreign_cell_is_refused_at_run():
    controller = grid_controller(grid_experiment())
    exp = controller.learning_state.current_experiment
    variant = controller.learning_state.plan[0]
    snapshot = thaw_snapshot(exp.execution_snapshot_json)
    snapshot["two_axis_grid"]["cells"][0]["effective"]["steps"] = 99
    exp.execution_snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="rebuild preview|Rebuild"):
        controller._build_variant_njr(variant, exp)
    foreign = grid_controller(grid_experiment())
    other = foreign.learning_state.plan[0]
    other.param_value = dict(other.param_value, y_value=25)
    with pytest.raises(ValueError, match="outside the frozen"):
        foreign._build_variant_njr(other, foreign.learning_state.current_experiment)


# ---- C. queue and recovery ------------------------------------------------------------------------------------


def test_run_compiles_everything_then_submits_once_and_binds_job_ids_to_cells(repository):
    controller, service = wired(grid_experiment(), repository)
    controller.run_plan()
    controller.run_plan()  # a double click admits nothing more
    assert len(service.calls) == 1 and len(service.calls[0]) == 9
    for variant, record in zip(controller.learning_state.plan, service.calls[0], strict=True):
        assert variant.job_id == record.job_id and variant.status == "queued"
        assert record.learning_context.variant_value == variant.param_value
        assert repository.get_job_model(variant.job_id) is not None


def test_one_incompatible_cell_at_run_admits_nothing(repository, monkeypatch):
    controller, service = wired(grid_experiment(), repository)
    from src.learning import two_axis_grid

    real = two_axis_grid.materialize_njr
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 5:
            raise ValueError("fifth cell incompatible")
        return real(*a, **k)

    monkeypatch.setattr(two_axis_grid, "materialize_njr", flaky)
    with pytest.raises(ValueError, match="fifth"):
        controller.run_plan()
    assert service.calls == [] and not any(v.job_id for v in controller.learning_state.plan)


def test_refused_admission_keeps_the_whole_draft(repository):
    controller, service = wired(grid_experiment(), repository)
    service.mode = "raise_before"
    with pytest.raises(Exception, match="refused|admitted"):
        controller.run_plan()
    assert all(v.status == "pending" and not v.job_id for v in controller.learning_state.plan)


def test_restart_reconstructs_each_cell_by_exact_identity_and_missing_cells_keep_position(
    tmp_path, repository
):
    controller, service = wired(grid_experiment(), repository)
    controller.run_plan()
    state = controller.learning_state
    state.selected_variant = state.plan[4]
    payload = json.loads(json.dumps(controller.export_resume_state()))
    ids = [v.job_id for v in state.plan]
    transition(repository, ids[0], JobStatus.COMPLETED, result_for(tmp_path))
    transition(repository, ids[3], JobStatus.FAILED, error="backend interrupted")
    fresh_service = RepositoryService(repository)
    restored = LearningController(
        LearningState(), pipeline_controller=SimpleNamespace(_job_service=fresh_service)
    )
    assert restored.restore_resume_state(copy.deepcopy(payload))
    plan = restored.learning_state.plan
    assert [v.job_id for v in plan] == ids
    assert [v.param_value["cell_id"] for v in plan] == [
        v.param_value["cell_id"] for v in state.plan
    ]
    assert plan[0].status == "completed" and len(plan[0].image_refs) == 2
    assert plan[3].status == "failed" and not plan[3].image_refs
    assert plan[4].status == "queued" and restored.learning_state.selected_variant is plan[4]
    assert fresh_service.calls == []
    restored.restore_resume_state(copy.deepcopy(payload))
    assert len(restored.learning_state.plan[0].image_refs) == 2


def test_duplicate_completion_does_not_duplicate_artifacts(tmp_path, repository):
    controller, service = wired(grid_experiment(), repository)
    controller.run_plan()
    first = controller.learning_state.plan[0]
    job = transition(repository, first.job_id, JobStatus.COMPLETED, result_for(tmp_path))
    service.finish(job)
    service.finish(job)
    assert (
        first.status == "completed" and len(first.image_refs) == 2 and first.completed_images == 2
    )


# ---- D. ratings and recommendations ---------------------------------------------------------------------------


def complete_all(controller, service, repository, tmp_path):
    controller.run_plan()
    for index, variant in enumerate(controller.learning_state.plan):
        sub = tmp_path / f"cell{index}"
        sub.mkdir()
        service.finish(transition(repository, variant.job_id, JobStatus.COMPLETED, result_for(sub)))


def test_grid_ratings_carry_cell_identity_and_cannot_feed_recommendations(tmp_path, repository):
    controller, service = wired(grid_experiment(), repository)
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    controller._learning_record_writer = writer
    complete_all(controller, service, repository, tmp_path)
    for variant in controller.learning_state.plan:
        assert (
            variant.status == "completed"
            and variant.execution_metadata["controlled_evidence_valid"] is True
        )
        for image in variant.image_refs:
            controller.record_rating(image, 5, "great")
    rows = [
        json.loads(line)["metadata"]
        for line in (tmp_path / "records.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 18 and {row["record_kind"] for row in rows} == {RECORD_KIND}
    sample = rows[0]
    assert sample["study_type"] == STUDY_TYPE and sample["causal_one_variable"] is False
    assert (
        sample["variant_value"]["x_variable"] == "CFG Scale"
        and sample["variant_value"]["y_variable"] == "Steps"
    )
    assert sample["grid_cell"]["cell_id"] == sample["variant_value"]["cell_id"]
    assert sample["grid_cell"]["sample_index"] in (0, 1) and sample["job_id"]
    assert sample["frozen_experiment"]["controlled_evidence_valid"] is True
    recommendations = RecommendationEngine(tmp_path / "records.jsonl").recommend(
        "portrait, detailed", "txt2img"
    )
    assert not getattr(recommendations, "recommendations", None)
    conclusion = controller.get_experiment_conclusion()
    assert conclusion["best_value"] is None and conclusion["causal_one_variable"] is False
    assert conclusion["sufficient_evidence"] is False and "winner" not in conclusion[
        "message"
    ].lower().replace("no winner", "")
    from src.learning.learning_analytics import LearningAnalytics

    assert LearningAnalytics(writer).get_experiment_summary("grid1") is None


def test_missing_seed_readback_makes_a_cell_uncontrolled(tmp_path, repository):
    controller, service = wired(grid_experiment(), repository)
    controller.run_plan()
    variant = controller.learning_state.plan[2]
    service.finish(
        transition(
            repository, variant.job_id, JobStatus.COMPLETED, result_for(tmp_path, seeds=False)
        )
    )
    assert (
        variant.status == "uncontrolled"
        and variant.execution_metadata["controlled_evidence_valid"] is False
    )


def test_lora_cell_execution_evidence_and_ordinary_classification_unchanged(tmp_path, repository):
    controller, service = wired(
        grid_experiment(x=("CFG Scale", (5, 9)), y=("LoRA Strength", (0.4, 0.8)), lora="detail-xl"),
        repository,
    )
    controller.run_plan()
    variant = controller.learning_state.plan[0]
    weight = variant.param_value["y_value"]
    result = result_for(tmp_path)
    result["variants"][0]["final_prompt"] = f"portrait <lora:detail-xl:{weight}>"
    service.finish(transition(repository, variant.job_id, JobStatus.COMPLETED, result))
    assert variant.execution_metadata["variable_validation_reason"] == "valid"
    wrong = controller.learning_state.plan[1]
    bad = result_for(tmp_path)
    bad["variants"][0]["final_prompt"] = "portrait <lora:detail-xl:0.1>"
    service.finish(transition(repository, wrong.job_id, JobStatus.COMPLETED, bad))
    assert wrong.status == "uncontrolled"
    from src.learning.model_comparison import rating_classification as ordinary_classification

    assert ordinary_classification({"study_type": "controlled_variable"}, 7.0, {}) == {
        "record_kind": "learning_experiment_rating"
    }
    with pytest.raises(ValueError):
        rating_classification({"study_type": "controlled_variable"}, 7.0, {})
    ordinary = build_experiment_conclusion([], {}, {}, study_type="controlled_variable")
    assert ordinary["causal_one_variable"] is True


def test_variant_label_is_readable_and_filename_safe():
    cell = {
        "cell_id": "abc",
        "x_variable": "CFG Scale",
        "x_value": 7.0,
        "y_variable": "Steps",
        "y_value": 30,
    }
    assert variant_label(cell) == "CFG Scale 7.0 | Steps 30"
    from src.learning.experiment_naming import build_learning_filename_prefix

    prefix = build_learning_filename_prefix(
        stage="txt2img", variable="CFG Scale x Steps", value=cell, variant_index=3
    )
    assert not set(prefix) & set("<>:\"/\\|?*{}' ")


# ---- save, reopen and resume -----------------------------------------------------------------------------------


def test_reopen_from_the_real_store_keeps_cells_ratings_drafts_and_selection_without_rebuilding(
    tmp_path, repository, monkeypatch
):
    from src.learning import two_axis_grid
    from src.learning.experiment_store import LearningExperimentStore

    controller, service = wired(grid_experiment(), repository)
    writer = LearningRecordWriter(tmp_path / "records.jsonl")
    controller._learning_record_writer = writer
    complete_all(controller, service, repository, tmp_path)
    state = controller.learning_state
    image = state.plan[4].image_refs[0]
    controller.record_rating(image, 4, "keeper")
    controller.save_review_draft(state.plan[5].image_refs[0], {"overall_rating": 3})
    state.selected_variant = state.plan[4]
    store = LearningExperimentStore(tmp_path / "experiments")
    handle = store.save_session(
        display_name="grid", payload=json.loads(json.dumps(controller.export_resume_state()))
    )
    rows_before = (tmp_path / "records.jsonl").read_text().splitlines()
    ids = [v.job_id for v in state.plan]

    monkeypatch.setattr(
        two_axis_grid, "build_grid_snapshot", lambda *a, **k: pytest.fail("reopen rebuilt the grid")
    )
    monkeypatch.setattr(
        two_axis_grid, "materialize_njr", lambda *a, **k: pytest.fail("reopen recompiled a cell")
    )
    fresh_service = RepositoryService(repository)
    reopened = LearningController(
        LearningState(),
        pipeline_controller=SimpleNamespace(_job_service=fresh_service),
        learning_record_writer=writer,
    )
    assert reopened.restore_resume_state(store.load_session(handle.experiment_id))
    reopened.restore_resume_state(store.load_session(handle.experiment_id))  # idempotent
    plan = reopened.learning_state.plan
    assert [v.job_id for v in plan] == ids and all(v.status == "completed" for v in plan)
    assert [len(v.image_refs) for v in plan] == [2] * 9
    assert reopened.learning_state.selected_variant is plan[4]
    assert reopened.get_rating_for_image(image) == 4 and reopened.get_review_draft(
        plan[5].image_refs[0]
    )
    assert (tmp_path / "records.jsonl").read_text().splitlines() == rows_before
    assert fresh_service.calls == []
    model = reopened.get_grid_results_model()
    assert [(c.row, c.col) for c in model.cells] == [(r, c) for r in range(3) for c in range(3)]
    assert model.cells[4].images[0].rating == 4 and model.exportable


def test_baseline_edited_after_preview_is_refused_at_run():
    controller = grid_controller(grid_experiment())
    exp = controller.learning_state.current_experiment
    for edit in (
        lambda b: b["pipeline"].update(upscale_enabled=True),
        lambda b: b["txt2img"].update(sampler_name="Euler"),
    ):
        snapshot = thaw_snapshot(exp.execution_snapshot_json)
        edit(snapshot["baseline_config"])
        tampered = LearningExperiment(
            name=exp.name,
            experiment_id=exp.experiment_id,
            execution_snapshot_json=json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
        )
        with pytest.raises(ValueError, match="plain txt2img|txt2img-only|integrity|rebuild"):
            controller._build_variant_njr(controller.learning_state.plan[0], tampered)
