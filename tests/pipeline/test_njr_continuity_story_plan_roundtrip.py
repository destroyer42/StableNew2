"""Live continuity-link and story-plan metadata survive NJR serialization.

The story-plan authoring code (compiler, models, store, ``ContinuityStore``) was retired as dormant. These tests pin the
surfaces that remain live: ``continuity_link`` on the video workload, ``story_plan``/``plan_origin`` metadata carried by
old and new records, and ``normalize_continuity_link``.
"""

from __future__ import annotations

import json
from typing import Any

from src.pipeline.njr_core_v26 import NormalizedJobRecord
from src.video.continuity_models import normalize_continuity_link
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

STORY_PLAN = {
    "plan_id": "plan-001",
    "actors": [{"name": "Hero", "lora_name": "hero_lora", "weight": 0.8}],
    "scenes": [{"scene_id": "s1", "shots": [{"shot_id": "a"}]}],
}
PLAN_ORIGIN = {"story_plan_id": "plan-001", "scene_id": "s1", "shot_id": "a"}
LINK = {
    "pack_id": "cont-001",
    "pack_summary": {"pack_id": "cont-001", "display_name": "Hero Pack"},
}


def _round_trip(record: NormalizedJobRecord) -> NormalizedJobRecord:
    return NormalizedJobRecord.from_dict(json.loads(json.dumps(record.to_dict())))


def test_video_njr_round_trips_continuity_link_and_story_plan_metadata() -> None:
    record = make_pipeline_njr(
        stage_chain=(make_stage_config("video_workflow"),),
        continuity_link=LINK,
        extra_metadata={"story_plan": STORY_PLAN, "plan_origin": PLAN_ORIGIN},
    )

    restored = _round_trip(record)

    assert restored.continuity_link == LINK
    assert restored.extra_metadata["story_plan"] == STORY_PLAN
    assert restored.extra_metadata["plan_origin"] == PLAN_ORIGIN
    assert restored.to_dict() == record.to_dict()


def test_image_njr_with_story_plan_metadata_round_trips_without_continuity() -> None:
    record = make_pipeline_njr(extra_metadata={"story_plan": STORY_PLAN})

    restored = _round_trip(record)

    assert restored.extra_metadata["story_plan"] == STORY_PLAN
    assert restored.to_dict() == record.to_dict()


def test_legacy_record_without_continuity_key_still_loads() -> None:
    payload: dict[str, Any] = make_pipeline_njr(
        stage_chain=(make_stage_config("video_workflow"),),
        continuity_link=LINK,
        extra_metadata={"story_plan": STORY_PLAN},
    ).to_dict()
    payload["workload"].pop("continuity_link", None)

    restored = NormalizedJobRecord.from_dict(payload)

    assert restored.continuity_link is None
    assert restored.extra_metadata["story_plan"] == STORY_PLAN


def test_normalize_continuity_link_accepts_legacy_mapping_shapes() -> None:
    assert normalize_continuity_link(None) is None
    assert normalize_continuity_link("  ") is None
    assert normalize_continuity_link({}) is None
    assert normalize_continuity_link(LINK) == normalize_continuity_link(dict(LINK))

    flat = normalize_continuity_link({"id": "cont-009", "name": "Legacy"})
    assert flat is not None
    assert flat["pack_id"] == "cont-009"
