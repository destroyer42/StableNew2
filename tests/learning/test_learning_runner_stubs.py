"""Tests for LearningRunner stub behavior."""

from __future__ import annotations

from src.learning.learning_plan import LearningPlan
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
