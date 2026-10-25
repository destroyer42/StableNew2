"""Legacy golden tests: experiments frozen before PR-LEARN-STAGE-650 restore and compile exactly as they did.

``fixtures/pre_650_ordinary_snapshots.json`` was produced by running the unchanged pre-650 code (merge base
40946733): each scenario holds the stored ``execution_snapshot_json`` and what that code compiled for every variant.
The expected values must not be edited to match new authoring behavior.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.gui.learning_state import LearningExperiment, LearningState, LearningVariant
from src.learning import baseline_authoring as authoring
from src.learning.experiment_execution import thaw_snapshot
from tests.learning_v2.test_learning_independent_baseline_650 import Bench

FIXTURE = Path(__file__).parent / "fixtures" / "pre_650_ordinary_snapshots.json"
SCENARIOS = json.loads(FIXTURE.read_text(encoding="utf-8"))["scenarios"]
PLACEHOLDER = "{SOURCE_IMAGE}"


def essentials(record, image: str) -> dict:
    context = record.provenance.learning_context
    return {
        "positive_prompt": record.positive_prompt,
        "negative_prompt": record.negative_prompt,
        "seed": record.seed,
        "images_per_prompt": record.images_per_prompt,
        "steps": record.steps,
        "cfg_scale": record.cfg_scale,
        "sampler_name": record.sampler_name,
        "scheduler": record.scheduler,
        "width": record.width,
        "height": record.height,
        "stages": [
            {
                "stage_type": s.stage_type,
                "enabled": s.enabled,
                "steps": s.steps,
                "cfg_scale": s.cfg_scale,
                "denoising_strength": s.denoising_strength,
                "sampler_name": s.sampler_name,
                "scheduler": s.scheduler,
                "model": s.model,
            }
            for s in record.stages
        ],
        "input_image_paths": [PLACEHOLDER if p else p for p in record.input_image_paths],
        "variant_value": context.variant_value,
        "variable": context.variable_name if hasattr(context, "variable_name") else None,
        "config": json.loads(json.dumps(record.config, default=str)),
    }


def restored(bench: Bench, scenario: dict) -> tuple[LearningExperiment, str]:
    image = bench.image()
    snapshot_json = scenario["snapshot_json"].replace(PLACEHOLDER, json.dumps(image)[1:-1])
    snapshot = thaw_snapshot(snapshot_json)
    stored = LearningExperiment(
        name=scenario["name"],
        experiment_id=scenario["experiment_id"],
        stage=scenario["stage"],
        variable_under_test=scenario["variable"],
        prompt_text=scenario["prompt_text"],
        images_per_value=snapshot["images_per_value"],
        values=list(scenario["values"]),
        input_image_path=snapshot["input_image_path"],
        baseline_config=copy.deepcopy(snapshot["baseline_config"]),
        execution_snapshot_json=snapshot_json,
        metadata=dict(snapshot["prompt_source"]),
    )
    return LearningExperiment.from_dict(stored.to_dict()), image


def open_legacy(bench: Bench, scenario: dict):
    experiment, image = restored(bench, scenario)
    bench.state.current_experiment = experiment
    bench.state.plan = [
        LearningVariant(
            experiment_id=experiment.experiment_id,
            variant_id=item["variant_id"],
            param_value=item["param_value"],
            planned_images=item["planned_images"],
        )
        for item in scenario["variants"]
    ]
    return experiment, image


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["stage"])
def test_legacy_snapshot_is_read_as_legacy_and_never_upgraded(tmp_path, scenario):
    bench = Bench(tmp_path)
    experiment, _ = open_legacy(bench, scenario)
    before = experiment.execution_snapshot_json
    assert not authoring.has_authoring(thaw_snapshot(before))
    assert experiment.baseline_authoring == {}
    bench.controller._get_baseline_config = lambda: pytest.fail(
        "A legacy experiment read the live Pipeline"
    )  # type: ignore[method-assign]
    for variant in bench.state.plan:
        bench.controller._build_variant_njr(variant, experiment)
    assert experiment.execution_snapshot_json == before  # read-only: no rewrite, no migration
    assert experiment.baseline_authoring == {}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["stage"])
def test_legacy_snapshot_compiles_to_exactly_what_the_original_code_compiled(tmp_path, scenario):
    bench = Bench(tmp_path)
    experiment, image = open_legacy(bench, scenario)
    bench.pipeline["txt2img"].update(
        steps=2, model="other.safetensors"
    )  # today's Pipeline must not matter
    for variant, item in zip(bench.state.plan, scenario["variants"], strict=True):
        record = bench.controller._build_variant_njr(variant, experiment)
        assert essentials(record, image) == item["expected"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["stage"])
def test_legacy_experiment_with_admitted_jobs_restores_with_exact_identities(tmp_path, scenario):
    bench = Bench(tmp_path)
    experiment, _ = open_legacy(bench, scenario)
    for index, variant in enumerate(bench.state.plan):
        variant.job_id = f"job-{scenario['stage']}-{index}"
        variant.status = "queued"
    payload = json.loads(json.dumps(bench.state.to_dict()))

    other = Bench(tmp_path / "restored")
    other.tmp_path.mkdir()
    assert other.controller.restore_resume_state(payload)
    restored_plan = other.state.plan
    assert [variant.job_id for variant in restored_plan] == [
        f"job-{scenario['stage']}-{i}" for i in range(len(restored_plan))
    ]
    assert other.state.current_experiment.experiment_id == scenario["experiment_id"]
    assert (
        other.state.current_experiment.execution_snapshot_json == experiment.execution_snapshot_json
    )
    other.controller.run_plan()  # every variant already has a job: nothing is resubmitted
    other.service.submit_njrs.assert_not_called()


def test_an_unbuilt_legacy_draft_is_not_given_a_fabricated_baseline(tmp_path):
    """S37: no frozen baseline and nothing authored -> the gaps are visible and nothing is executable."""
    bench = Bench(tmp_path)
    bench.pipeline = {}  # the Pipeline offers nothing to copy
    incomplete = LearningExperiment(
        name="old draft",
        experiment_id="old",
        stage="txt2img",
        variable_under_test="CFG Scale",
        prompt_text="x",
        values=[4.0, 6.0],
    )
    state = LearningState()
    state.current_experiment = incomplete
    state.plan = [LearningVariant(experiment_id="old", variant_id="old:0", param_value=4.0)]
    assert bench.controller.restore_resume_state(json.loads(json.dumps(state.to_dict())))
    assert bench.controller.authoring_baseline() == {}
    assert bench.controller.pipeline_settings_available() is False
    problems = bench.controller.baseline_blockers("txt2img")
    assert problems and "empty" in problems[0]
    with pytest.raises(ValueError, match="no frozen baseline"):
        bench.controller._build_variant_njr(bench.state.plan[0], bench.state.current_experiment)
    bench.service.submit_njrs.assert_not_called()
