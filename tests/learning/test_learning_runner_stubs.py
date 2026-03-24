"""Tests for LearningRunner stub behavior."""

from __future__ import annotations

from src.learning.learning_plan import LearningPlan, build_prompt_optimizer_preset_plan
from src.learning.learning_runner import LearningRunner


def _sample_plan():
    return LearningPlan(
        mode="single_variable_sweep",
        stage="txt2img",
        target_variable="cfg_scale",
        sweep_values=[5.0, 7.5, 10.0],
        images_per_step=2,
    )


def test_prepare_learning_batches_returns_steps():
    runner = LearningRunner({"txt2img": {"model": "base"}})
    plan = _sample_plan()

    steps = runner.prepare_learning_batches(plan)

    assert len(steps) == len(plan.sweep_values)
    assert steps[0].config_snapshot["txt2img"]["cfg_scale"] == 5.0
    assert steps[-1].config_snapshot["txt2img"]["cfg_scale"] == 10.0


def test_run_learning_batches_returns_placeholder_result():
    runner = LearningRunner({"txt2img": {"model": "base"}})
    plan = _sample_plan()
    steps = runner.prepare_learning_batches(plan)

    result = runner.run_learning_batches(steps)

    assert result.plan is plan
    assert len(result.artifacts) == len(steps)
    assert result.summary["status"] == "learning_stub"

    summary = runner.summarize_results(result)
    assert summary["total_steps"] == len(steps)
    assert summary["unique_values"] == sorted(plan.sweep_values)


def test_prepare_learning_batches_supports_prompt_optimizer_preset_comparison():
    runner = LearningRunner({"txt2img": {"model": "base"}})
    plan = build_prompt_optimizer_preset_plan(
        stage="txt2img",
        preset_ids=["baseline_safe_v1", "subject_anchor_v1"],
    )

    steps = runner.prepare_learning_batches(plan)

    assert [step.value for step in steps] == ["baseline_safe_v1", "subject_anchor_v1"]
    assert steps[0].config_snapshot["prompt_optimizer"]["enabled"] is True
    assert steps[0].config_snapshot["metadata"]["prompt_optimizer_learning_enabled"] is True
    assert steps[1].config_snapshot["metadata"]["prompt_optimizer_learning_preset"] == "subject_anchor_v1"


def test_run_learning_batches_summarizes_compared_presets():
    runner = LearningRunner({"txt2img": {"model": "base"}})
    plan = build_prompt_optimizer_preset_plan(
        stage="txt2img",
        preset_ids=["baseline_safe_v1", "score_classifier_v1"],
    )
    steps = runner.prepare_learning_batches(plan)

    result = runner.run_learning_batches(steps)

    assert result.summary["compared_presets"] == ["baseline_safe_v1", "score_classifier_v1"]
    summary = runner.summarize_results(result)
    assert summary["compared_presets"] == ["baseline_safe_v1", "score_classifier_v1"]
