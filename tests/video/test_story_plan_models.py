from __future__ import annotations

from src.video.story_plan_models import Actor, AnchorPlan, ScenePlan, ShotPlan, StoryPlan, merge_actor_lists


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
                actors=[
                    Actor(
                        name="Ada",
                        character_name="ada",
                        trigger_phrase="ada person",
                        lora_name="ada",
                        weight=0.7,
                    )
                ],
                shots=[
                    ShotPlan(
                        shot_id="shot-001",
                        display_name="Intro Pan",
                        prompt="hero on rooftop",
                        actors=[
                            Actor(
                                name="Ada",
                                character_name="ada",
                                trigger_phrase="ada heroic close-up",
                                weight=0.9,
                            ),
                            Actor(
                                name="Bran",
                                character_name="bran",
                                trigger_phrase="bran ranger",
                                lora_name="bran",
                            ),
                        ],
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
    assert restored.scenes[0].actors[0].trigger_phrase == "ada person"
    assert restored.scenes[0].shots[0].actors[0].trigger_phrase == "ada heroic close-up"
    assert restored.continuity_link is not None
    assert restored.continuity_link["pack_id"] == "cont-001"


def test_story_plan_summary_counts() -> None:
    summary = _make_plan().summary()

    assert summary.scene_count == 1
    assert summary.shot_count == 1
    assert summary.anchor_count == 1


def test_merge_actor_lists_shot_overrides_scene_without_reordering() -> None:
    merged = merge_actor_lists(
        [
            Actor(
                name="Ada",
                character_name="ada",
                trigger_phrase="ada person",
                lora_name="ada",
                weight=0.7,
            )
        ],
        [
            Actor(
                name="Ada",
                character_name="ada",
                trigger_phrase="ada heroic close-up",
                weight=0.9,
            ),
            Actor(
                name="Bran",
                character_name="bran",
                trigger_phrase="bran ranger",
                lora_name="bran",
            ),
        ],
    )

    assert [actor.character_name for actor in merged] == ["ada", "bran"]
    assert merged[0].trigger_phrase == "ada heroic close-up"
    assert merged[0].lora_name == "ada"
    assert merged[0].weight == 0.9