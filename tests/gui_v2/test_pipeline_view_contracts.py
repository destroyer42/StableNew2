from __future__ import annotations

import pytest

from src.gui.base_generation_panel_v2 import BaseGenerationPanelV2
from src.gui.view_contracts.pipeline_layout_contract import (
    LABEL_COLUMN_MIN_WIDTH,
    PRIMARY_CONTROL_MIN_WIDTH,
    SECONDARY_CONTROL_MIN_WIDTH,
    WORKSPACE_CENTER_COLUMN_MIN_WIDTH,
    WORKSPACE_LEFT_COLUMN_MIN_WIDTH,
    WORKSPACE_RIGHT_COLUMN_MIN_WIDTH,
    get_compact_minsize,
    get_form_min_width,
    get_stage_card_min_width,
    get_three_pair_form_column_specs,
    get_three_pane_workspace_column_specs,
    get_two_pair_form_column_specs,
    get_two_pane_workspace_column_specs,
    get_visible_stage_order,
    is_compact_pipeline_width,
)


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


def test_base_generation_uses_responsive_two_pair_layout() -> None:
    assert tuple(spec["index"] for spec in BaseGenerationPanelV2.FORM_COLUMN_SPECS) == (0, 1, 2, 3)
    assert BaseGenerationPanelV2.FORM_COLUMN_SPECS[1]["minsize"] == 160
    assert get_form_min_width(BaseGenerationPanelV2.FORM_COLUMN_SPECS) < 664


def test_workspace_column_specs_define_shared_surface_minimums() -> None:
    assert get_two_pane_workspace_column_specs() == (
        {"index": 0, "weight": 2, "minsize": WORKSPACE_LEFT_COLUMN_MIN_WIDTH},
        {"index": 1, "weight": 3, "minsize": WORKSPACE_CENTER_COLUMN_MIN_WIDTH},
    )
    assert get_three_pane_workspace_column_specs() == (
        {"index": 0, "weight": 2, "minsize": WORKSPACE_LEFT_COLUMN_MIN_WIDTH},
        {"index": 1, "weight": 3, "minsize": WORKSPACE_CENTER_COLUMN_MIN_WIDTH},
        {"index": 2, "weight": 3, "minsize": WORKSPACE_RIGHT_COLUMN_MIN_WIDTH},
    )


@pytest.mark.parametrize(
    ("width", "compact"),
    [(0, False), (1, False), (399, False), (1280, True), (1342, True), (1879, True), (1880, False), (2560, False)],
)
def test_compact_pipeline_breakpoint_ignores_unrealized_widths(width: int, compact: bool) -> None:
    assert is_compact_pipeline_width(width) is compact


def test_compact_minsize_scales_form_columns_and_leaves_small_ones() -> None:
    assert get_compact_minsize(160) < 160
    assert get_compact_minsize(88) < 88
    assert get_compact_minsize(24) == 24
