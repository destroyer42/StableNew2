from __future__ import annotations

from src.gui.view_contracts.pipeline_layout_contract import (
    LABEL_COLUMN_MIN_WIDTH,
    PRIMARY_CONTROL_MIN_WIDTH,
    SECONDARY_CONTROL_MIN_WIDTH,
    get_form_min_width,
    get_stage_card_min_width,
    get_three_pair_form_column_specs,
    get_two_pair_form_column_specs,
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


def test_shared_form_column_specs_define_consistent_minimums() -> None:
    two_pair = get_two_pair_form_column_specs()
    three_pair = get_three_pair_form_column_specs()

    assert two_pair == (
        {"index": 0, "weight": 0, "minsize": LABEL_COLUMN_MIN_WIDTH},
        {"index": 1, "weight": 1, "minsize": PRIMARY_CONTROL_MIN_WIDTH},
        {"index": 2, "weight": 0, "minsize": LABEL_COLUMN_MIN_WIDTH},
        {"index": 3, "weight": 1, "minsize": SECONDARY_CONTROL_MIN_WIDTH},
    )
    assert three_pair[0]["minsize"] == LABEL_COLUMN_MIN_WIDTH
    assert three_pair[1]["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
    assert three_pair[3]["minsize"] == SECONDARY_CONTROL_MIN_WIDTH
    assert three_pair[5]["minsize"] == SECONDARY_CONTROL_MIN_WIDTH


def test_stage_card_min_width_rolls_up_shared_form_columns() -> None:
    expected = get_form_min_width(get_two_pair_form_column_specs(), padding=24)
    assert get_stage_card_min_width() == expected
