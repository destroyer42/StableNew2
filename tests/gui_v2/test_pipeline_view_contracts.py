from __future__ import annotations

from src.gui.view_contracts.pipeline_layout_contract import (
    get_visible_stage_order,
    normalize_window_geometry,
)


def test_normalize_window_geometry_only_when_below_minimum() -> None:
    assert normalize_window_geometry("1500x900+100+50", 1400) is None
    assert normalize_window_geometry("1200x900+100+50", 1400) == "1400x900+100+50"
    assert normalize_window_geometry("1200x900", 1400) == "1400x900"


def test_get_visible_stage_order_preserves_source_order() -> None:
    order = get_visible_stage_order(
        ["txt2img", "img2img", "ADetailer", "upscale"],
        ["upscale", "txt2img"],
    )
    assert order == ("txt2img", "upscale")
