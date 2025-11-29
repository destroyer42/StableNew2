"""Tests for the learning adapter stub."""

from __future__ import annotations

from src.learning.learning_adapter import (
    build_learning_plan_from_config,
    prepare_learning_run,
)


def test_build_learning_plan_from_config_matches_options():
    base_config = {"txt2img": {"model": "base"}}
    plan = build_learning_plan_from_config(
        base_config,
        stage="txt2img",
        target_variable="steps",
        sweep_values=[10, 20],
        images_per_step=3,
        metadata={"note": "demo"},
    )

    assert plan.stage == "txt2img"
    assert plan.target_variable == "steps"
    assert plan.sweep_values == [10, 20]
    assert plan.images_per_step == 3
    assert plan.metadata == {"note": "demo"}


def test_prepare_learning_run_returns_plan_and_steps_without_mutating_base():
    base_config = {"txt2img": {"model": "demo"}}
    options = {
        "stage": "txt2img",
        "target_variable": "cfg_scale",
        "sweep_values": [5.0, 7.0],
        "images_per_step": 1,
    }

    plan, steps = prepare_learning_run(base_config, options)

    assert len(steps) == 2
    assert steps[0].config_snapshot["txt2img"]["cfg_scale"] == 5.0
    assert base_config["txt2img"].get("cfg_scale") is None
    assert plan.target_variable == "cfg_scale"
