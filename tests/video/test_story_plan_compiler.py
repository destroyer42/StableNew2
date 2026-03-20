from __future__ import annotations

import pytest

from src.video.story_plan_compiler import StoryPlanCompiler
from src.video.story_plan_models import AnchorPlan, ScenePlan, ShotPlan, StoryPlan


def _make_plan() -> StoryPlan:
    return StoryPlan(
        plan_id="story-001",
        display_name="Opening Sequence",
        continuity_link={
            "pack_id": "cont-001",
            "pack_summary": {"pack_id": "cont-001", "display_name": "Hero Pack"},
        },
        scenes=[
            ScenePlan(
                scene_id="scene-001",
                display_name="Rooftop",
                shots=[
                    ShotPlan(
                        shot_id="shot-001",
                        display_name="Intro Pan",
                        prompt="hero on rooftop",
                        negative_prompt="blurry",
                        workflow_id="ltx_multiframe_anchor_v1",
                        total_segments=2,
                        segment_length_frames=24,
                        overlap_frames=2,
                        carry_forward_policy="last_frame",
                        anchors=[
                            AnchorPlan(
                                anchor_id="anchor-001",
                                display_name="Hero Start",
                                source_image_path="C:/anchors/hero_start.png",
                            ),
                            AnchorPlan(
                                anchor_id="anchor-002",
                                display_name="Hero Mid",
                                source_image_path="C:/anchors/hero_mid.png",
                                prompt="hero turns to camera",
                            ),
                        ],
                    )
                ],
            )
        ],
    )


def test_compile_story_plan_returns_sequence_jobs() -> None:
    compiled = StoryPlanCompiler().compile(_make_plan())

    assert len(compiled) == 1
    sequence_job = compiled[0]
    assert sequence_job.sequence_id == "story_story-001__scene_scene-001__shot_shot-001"
    assert sequence_job.workflow_id == "ltx_multiframe_anchor_v1"
    assert sequence_job.total_segments == 2
    assert sequence_job.base_source_image_path == "C:/anchors/hero_start.png"
    assert sequence_job.plan_origin is not None
    assert sequence_job.plan_origin["plan_id"] == "story-001"
    assert sequence_job.plan_origin["scene_id"] == "scene-001"
    assert sequence_job.plan_origin["shot_id"] == "shot-001"
    assert sequence_job.continuity_link is not None
    assert sequence_job.continuity_link["pack_id"] == "cont-001"


def test_compile_story_plan_builds_anchor_overrides() -> None:
    compiled = StoryPlanCompiler().compile(_make_plan())

    overrides = compiled[0].per_segment_overrides
    assert overrides[0]["anchor_id"] == "anchor-001"
    assert overrides[1]["anchor_id"] == "anchor-002"
    assert overrides[1]["prompt"] == "hero turns to camera"
    assert overrides[1]["source_image_path"] == "C:/anchors/hero_mid.png"


def test_compile_requires_workflow_id() -> None:
    plan = _make_plan()
    plan.scenes[0].shots[0].workflow_id = None

    with pytest.raises(ValueError):
        StoryPlanCompiler().compile(plan)


def test_compile_is_deterministic() -> None:
    compiler = StoryPlanCompiler()
    first = compiler.compile(_make_plan())
    second = compiler.compile(_make_plan())

    assert [job.to_dict() for job in first] == [job.to_dict() for job in second]