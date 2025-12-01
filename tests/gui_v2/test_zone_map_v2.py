from __future__ import annotations

from src.gui.zone_map_v2 import ZONE_MAP, get_pipeline_stage_order


def test_zone_map_defines_pipeline_center_stages() -> None:
    assert "pipeline_tab" in ZONE_MAP
    center = ZONE_MAP["pipeline_tab"].get("center") or {}
    assert "stages_order" in center
    stage_order = get_pipeline_stage_order()
    assert isinstance(stage_order, list)
    assert stage_order == list(center["stages_order"])
