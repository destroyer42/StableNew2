"""Pure fit/placement rules for the Photo Optimize tab (PR-GUI-420). No Tk, no state.

The Tk mixin (``PhotoOptimizeLayoutMixin``) owns *when* these are applied and only re-grids existing widgets; this
module owns the arithmetic so it is testable without a display. Nothing here derives a layout from a screen size:
every decision is "do the requested widths of the regions fit the width the tab was actually given".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

BODY_WIDE = "wide"  # assets | previews | editor side by side
BODY_SPLIT = "split"  # assets over previews on the left, editor on the right
BODY_STACKED = "stacked"  # assets, previews, editor in one scrolling column

REGION_GUTTER = 12
HEADER_GAP = 6
HEADER_ROW_GAP = 4
# Edge of the narrowest usable original/candidate thumbnail (matches the shared preview floor).
PREVIEW_MIN_EDGE = 200
PREVIEW_MAX_EDGE = 360

# Region minimum widths, in widths of the digit "0" in the real default font (so they follow font and DPI scaling),
# plus fixed pixels for scrollbars, borders and padding that do not scale with the font.
ASSETS_MIN_CHARS = 28
ASSETS_MIN_PAD = 48
EDITOR_MIN_CHARS = 64
EDITOR_MIN_PAD = 48
PREVIEW_MIN_PAD = 48


@dataclass(frozen=True)
class RegionMinimums:
    assets: int
    preview: int
    editor: int


@dataclass(frozen=True)
class Placement:
    row: int
    column: int
    rowspan: int = 1
    columnspan: int = 1


def region_minimums(char_width: int) -> RegionMinimums:
    """Smallest usable width of each body region for a font whose digit is ``char_width`` px wide."""

    char = max(1, int(char_width))
    return RegionMinimums(
        assets=ASSETS_MIN_CHARS * char + ASSETS_MIN_PAD,
        preview=2 * PREVIEW_MIN_EDGE + REGION_GUTTER + PREVIEW_MIN_PAD,
        editor=EDITOR_MIN_CHARS * char + EDITOR_MIN_PAD,
    )


def choose_body_mode(
    available_width: int, minimums: RegionMinimums, *, gutter: int = REGION_GUTTER
) -> str:
    """Widest arrangement whose regions each keep their minimum width inside ``available_width``.

    An unmeasured parent (width <= 1) keeps the wide arrangement rather than flashing a stacked one.
    """

    if available_width <= 1:
        return BODY_WIDE
    available = int(available_width)
    if minimums.assets + minimums.preview + minimums.editor + 2 * gutter <= available:
        return BODY_WIDE
    if max(minimums.assets, minimums.preview) + minimums.editor + gutter <= available:
        return BODY_SPLIT
    return BODY_STACKED


def body_placements(mode: str) -> dict[str, Placement]:
    if mode == BODY_WIDE:
        return {"assets": Placement(0, 0), "preview": Placement(0, 1), "editor": Placement(0, 2)}
    if mode == BODY_SPLIT:
        # The editor spans a third, empty, weighted row so its extra height never inflates the left-hand rows.
        return {
            "assets": Placement(0, 0),
            "preview": Placement(1, 0),
            "editor": Placement(0, 1, rowspan=3),
        }
    return {"assets": Placement(0, 0), "preview": Placement(1, 0), "editor": Placement(2, 0)}


def body_column_weights(mode: str) -> tuple[int, ...]:
    """Grid weights for the used columns; the editor and previews get the spare width, assets stay narrow."""

    if mode == BODY_WIDE:
        return (1, 2, 2)
    if mode == BODY_SPLIT:
        return (2, 3)
    return (1,)


def body_column_minsizes(mode: str, minimums: RegionMinimums) -> tuple[int, ...]:
    """Minimum width of each used body column, so the grid never squeezes a region below its floor."""

    if mode == BODY_WIDE:
        return (minimums.assets, minimums.preview, minimums.editor)
    if mode == BODY_SPLIT:
        return (max(minimums.assets, minimums.preview), minimums.editor)
    return (0,)


def flow_rows(
    widths: Sequence[int], available_width: int, *, gap: int = HEADER_GAP
) -> list[list[int]]:
    """Greedy left-to-right wrap of items of ``widths`` into rows no wider than ``available_width``.

    Returns item indices per row, order preserved. An item wider than the row still gets a row of its own
    (it is never dropped), and an unmeasured parent (<= 1) keeps everything on one row.
    """

    if not widths:
        return []
    if available_width <= 1:
        return [list(range(len(widths)))]
    rows: list[list[int]] = [[]]
    used = 0
    for index, width in enumerate(widths):
        needed = int(width) + (gap if rows[-1] else 0)
        if rows[-1] and used + needed > available_width:
            rows.append([])
            used = 0
            needed = int(width)
        rows[-1].append(index)
        used += needed
    return rows


def selection_summary(
    *, visible: int, selected: int, active_name: str | None, archived: int = 0
) -> str:
    """One truthful line saying which photo the Single Photo editor targets and how many form the batch.

    ``visible`` counts unarchived photos (what Review All Visible acts on); archived rows shown by
    "Show Archived" are reported separately.
    """

    if visible <= 0 and archived <= 0:
        return "No assets loaded"
    active = f"Single Photo: {active_name}" if active_name else "Single Photo: none"
    extra = f" (+{archived} archived)" if archived > 0 else ""
    return f"{active}  |  Batch: {selected} selected  |  {visible} visible{extra}"


__all__ = [
    "BODY_SPLIT",
    "BODY_STACKED",
    "BODY_WIDE",
    "HEADER_GAP",
    "HEADER_ROW_GAP",
    "PREVIEW_MAX_EDGE",
    "PREVIEW_MIN_EDGE",
    "REGION_GUTTER",
    "Placement",
    "RegionMinimums",
    "body_column_minsizes",
    "body_column_weights",
    "body_placements",
    "choose_body_mode",
    "flow_rows",
    "region_minimums",
    "selection_summary",
]
