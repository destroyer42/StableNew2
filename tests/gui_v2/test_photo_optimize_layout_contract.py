"""Pure Photo Optimize fit rules (PR-GUI-420). No display required."""

from __future__ import annotations

import pytest

from src.gui.view_contracts import photo_optimize_layout_contract as contract
from src.gui.view_contracts.photo_optimize_layout_contract import (
    BODY_SPLIT,
    BODY_STACKED,
    BODY_WIDE,
    body_column_minsizes,
    body_column_weights,
    body_placements,
    choose_body_mode,
    flow_rows,
    region_minimums,
    selection_summary,
)

MINIMUMS = region_minimums(7)


def _wide_need(minimums=MINIMUMS) -> int:
    return minimums.assets + minimums.preview + minimums.editor + 2 * contract.REGION_GUTTER


def _split_need(minimums=MINIMUMS) -> int:
    return max(minimums.assets, minimums.preview) + minimums.editor + contract.REGION_GUTTER


def test_minimums_follow_font_width_not_a_screen_size() -> None:
    narrow, wide = region_minimums(6), region_minimums(10)
    assert wide.editor > narrow.editor and wide.assets > narrow.assets
    assert wide.preview == narrow.preview  # thumbnails are pixel based, fonts do not change them


def test_mode_is_the_widest_arrangement_whose_regions_fit() -> None:
    assert choose_body_mode(_wide_need(), MINIMUMS) == BODY_WIDE
    assert choose_body_mode(_wide_need() - 1, MINIMUMS) == BODY_SPLIT
    assert choose_body_mode(_split_need(), MINIMUMS) == BODY_SPLIT
    assert choose_body_mode(_split_need() - 1, MINIMUMS) == BODY_STACKED


def test_larger_font_needs_more_width_for_the_same_arrangement() -> None:
    width = _wide_need(region_minimums(7))
    assert choose_body_mode(width, region_minimums(7)) == BODY_WIDE
    assert choose_body_mode(width, region_minimums(11)) != BODY_WIDE


def test_unmeasured_parent_keeps_wide_instead_of_flashing_stacked() -> None:
    assert choose_body_mode(0, MINIMUMS) == BODY_WIDE
    assert choose_body_mode(1, MINIMUMS) == BODY_WIDE


@pytest.mark.parametrize("mode", [BODY_WIDE, BODY_SPLIT, BODY_STACKED])
def test_every_region_has_exactly_one_non_overlapping_cell(mode: str) -> None:
    placements = body_placements(mode)
    assert set(placements) == {"assets", "preview", "editor"}
    cells: set[tuple[int, int]] = set()
    for placement in placements.values():
        for row in range(placement.row, placement.row + placement.rowspan):
            for column in range(placement.column, placement.column + placement.columnspan):
                assert (row, column) not in cells
                cells.add((row, column))
    columns = {p.column for p in placements.values()}
    assert len(body_column_weights(mode)) == len(columns)
    assert len(body_column_minsizes(mode, MINIMUMS)) == len(columns)


def test_split_editor_spans_a_spare_row_so_left_rows_stay_natural() -> None:
    placements = body_placements(BODY_SPLIT)
    left_rows = {placements["assets"].row, placements["preview"].row}
    assert placements["editor"].row == 0
    assert placements["editor"].rowspan > max(left_rows) + 1


def test_stacked_order_is_assets_preview_editor() -> None:
    placements = body_placements(BODY_STACKED)
    assert [placements[n].row for n in ("assets", "preview", "editor")] == [0, 1, 2]


def test_flow_rows_wraps_without_dropping_or_reordering() -> None:
    widths = [100, 120, 80, 200]
    assert flow_rows(widths, 1000, gap=6) == [[0, 1, 2, 3]]
    assert flow_rows(widths, 250, gap=6) == [[0, 1], [2], [3]]
    assert flow_rows(widths, 290, gap=6) == [[0, 1], [2, 3]]
    flat = [i for row in flow_rows(widths, 90, gap=6) for i in row]
    assert flat == [0, 1, 2, 3]


def test_flow_rows_item_wider_than_row_gets_its_own_row() -> None:
    assert flow_rows([50, 400, 50], 200, gap=0) == [[0], [1], [2]]


def test_flow_rows_unmeasured_parent_is_one_row_and_empty_is_empty() -> None:
    assert flow_rows([10, 10], 1) == [[0, 1]]
    assert flow_rows([], 500) == []


def test_flow_rows_counts_gap_between_items() -> None:
    assert flow_rows([100, 100], 206, gap=6) == [[0, 1]]
    assert flow_rows([100, 100], 206, gap=10) == [[0], [1]]


def test_selection_summary_distinguishes_single_from_batch() -> None:
    text = selection_summary(visible=12, selected=3, active_name="a.png")
    assert "Single Photo: a.png" in text and "Batch: 3 selected" in text and "12 visible" in text
    assert "Single Photo: none" in selection_summary(visible=2, selected=0, active_name=None)
    assert selection_summary(visible=0, selected=0, active_name=None) == "No assets loaded"
    archived = selection_summary(visible=2, selected=1, active_name="a.png", archived=1)
    assert "2 visible (+1 archived)" in archived
