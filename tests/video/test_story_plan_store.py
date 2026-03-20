from __future__ import annotations

from pathlib import Path

from src.video.story_plan_models import ScenePlan, ShotPlan, StoryPlan
from src.video.story_plan_store import StoryPlanStore


def _make_plan(plan_id: str, display_name: str) -> StoryPlan:
    return StoryPlan(
        plan_id=plan_id,
        display_name=display_name,
        created_at="2026-03-20T00:00:00+00:00",
        updated_at="2026-03-20T01:00:00+00:00",
        scenes=[
            ScenePlan(
                scene_id="scene-001",
                display_name="Scene",
                shots=[
                    ShotPlan(
                        shot_id="shot-001",
                        display_name="Shot",
                        prompt="prompt",
                        workflow_id="ltx_multiframe_anchor_v1",
                    )
                ],
            )
        ],
    )


def test_save_and_load_plan_round_trip(tmp_path: Path) -> None:
    store = StoryPlanStore(tmp_path)
    plan = _make_plan("story-001", "Opening")

    path = store.save_plan(plan)
    loaded = store.load_plan("story-001")

    assert path.exists()
    assert loaded is not None
    assert loaded.to_dict() == plan.to_dict()


def test_list_plan_summaries_sorted(tmp_path: Path) -> None:
    store = StoryPlanStore(tmp_path)
    store.save_plan(_make_plan("story-b", "Zulu"))
    store.save_plan(_make_plan("story-a", "Alpha"))

    summaries = store.list_plan_summaries()

    assert [summary.plan_id for summary in summaries] == ["story-a", "story-b"]


def test_load_missing_plan_returns_none(tmp_path: Path) -> None:
    store = StoryPlanStore(tmp_path)

    assert store.load_plan("missing") is None