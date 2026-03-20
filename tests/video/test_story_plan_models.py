from __future__ import annotations

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
                        workflow_id="ltx_multiframe_anchor_v1",
                        total_segments=2,
                        segment_length_frames=24,
                        overlap_frames=2,
                        carry_forward_policy="last_frame",
                        anchors=[
                            AnchorPlan(
                                anchor_id="anchor-001",
                                display_name="Hero Start",
                                source_image_path="C:/anchors/hero.png",
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_story_plan_round_trip() -> None:
    plan = _make_plan()

    restored = StoryPlan.from_dict(plan.to_dict())

    assert restored.plan_id == "story-001"
    assert restored.scenes[0].scene_id == "scene-001"
    assert restored.scenes[0].shots[0].anchors[0].anchor_id == "anchor-001"
    assert restored.continuity_link is not None
    assert restored.continuity_link["pack_id"] == "cont-001"


def test_story_plan_summary_counts() -> None:
    summary = _make_plan().summary()

    assert summary.scene_count == 1
    assert summary.shot_count == 1
    assert summary.anchor_count == 1