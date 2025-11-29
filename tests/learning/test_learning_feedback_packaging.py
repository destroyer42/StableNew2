"""Tests for learning feedback serialization."""

from __future__ import annotations

from src.learning.learning_feedback import (
    FeedbackBundle,
    UserFeedbackItem,
    package_feedback_for_llm,
)
from src.learning.learning_plan import LearningPlan


def test_package_feedback_for_llm_includes_plan_and_items():
    plan = LearningPlan(
        mode="single_variable_sweep",
        stage="txt2img",
        target_variable="cfg_scale",
        sweep_values=[1, 2],
    )
    bundle = FeedbackBundle(
        plan=plan,
        items=[
            UserFeedbackItem(step_index=0, score=0.2, notes="too dark", selected_best=False),
            UserFeedbackItem(step_index=1, score=0.8, notes="good", selected_best=True),
        ],
    )

    packaged = package_feedback_for_llm(bundle)

    assert packaged["plan"]["target_variable"] == "cfg_scale"
    assert packaged["metadata"]["total_items"] == 2
    assert packaged["feedback"][1]["selected_best"] is True
