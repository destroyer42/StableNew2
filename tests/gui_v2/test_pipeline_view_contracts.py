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
    pipeline_layout_fits,
    select_compact_scale,
    should_probe_normal_layout,
    should_refit_compact,
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
    ("extents", "fits"),
    [
        ([], True),
        ([(300, 400), (500, 500)], True),
        ([(401, 400)], True),  # within the 1 px tolerance
        ([(402, 400)], False),
        ([(300, 400), (700, 560)], False),  # one overflowing surface is enough
    ],
)
def test_pipeline_layout_fit_is_decided_from_required_versus_available_width(extents, fits) -> None:
    assert pipeline_layout_fits(extents) is fits


def test_select_compact_scale_prefers_the_least_compact_scale_that_fits() -> None:
    tried: list[float] = []

    def fits_at(scale: float) -> bool:
        tried.append(scale)
        return scale <= 0.65

    scale, fits = select_compact_scale(fits_at, (0.8, 0.7, 0.6, 0.5))
    assert (scale, fits) == (0.6, True)
    assert tried == [0.8, 0.7, 0.6]  # stops at the first fit, most generous scale first
    assert select_compact_scale(lambda _scale: True, (0.8, 0.5)) == (0.8, True)
    assert select_compact_scale(lambda _scale: False, (0.8, 0.5)) == (0.5, False)  # best effort: the smallest


@pytest.mark.parametrize(
    ("width", "unfit_width", "probe"),
    [(1300, None, True), (1303, 1280, False), (1304, 1280, True), (900, 1280, False)],
)
def test_normal_layout_is_probed_again_only_after_the_window_has_grown(width, unfit_width, probe) -> None:
    assert should_probe_normal_layout(width, unfit_width, step=24) is probe


def test_compact_layout_refits_only_after_growth_and_compact_minsize_leaves_small_columns() -> None:
    assert should_refit_compact(1330, 1300, step=24) is True
    assert should_refit_compact(1310, 1300, step=24) is False
    assert get_compact_minsize(160, 0.6) == 96
    assert get_compact_minsize(88, 0.5) == 44
    assert get_compact_minsize(24, 0.5) == 24
