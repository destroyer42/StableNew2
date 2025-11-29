"""Tests for learning plan factory helpers."""

from __future__ import annotations

import pytest

from src.learning.learning_plan import (
    LearningPlan,
    build_learning_plan_from_dict,
)


def test_build_learning_plan_from_dict_basic():
    payload = {
        "mode": "single_variable_sweep",
        "stage": "txt2img",
        "target_variable": "cfg_scale",
        "sweep_values": [5.0, 7.0],
        "images_per_step": 2,
        "metadata": {"notes": "demo"},
    }
    plan = build_learning_plan_from_dict(payload)

    assert isinstance(plan, LearningPlan)
    assert plan.mode == "single_variable_sweep"
    assert plan.stage == "txt2img"
    assert plan.target_variable == "cfg_scale"
    assert plan.sweep_values == [5.0, 7.0]
    assert plan.images_per_step == 2
    assert plan.metadata == {"notes": "demo"}


def test_build_learning_plan_from_dict_normalizes_values():
    payload = {
        "mode": "single_variable_sweep",
        "stage": "img2img",
        "target_variable": "steps",
        "sweep_values": 50,
    }
    plan = build_learning_plan_from_dict(payload)

    assert plan.sweep_values == [50]
    assert plan.images_per_step == 1


def test_build_learning_plan_from_dict_missing_fields():
    payload = {"mode": "single_variable_sweep"}
    with pytest.raises(ValueError):
        build_learning_plan_from_dict(payload)
