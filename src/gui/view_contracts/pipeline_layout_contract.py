"""Toolkit-agnostic layout contracts for Pipeline tab behavior."""

from __future__ import annotations

from collections.abc import Sequence

LABEL_COLUMN_MIN_WIDTH = 88
PRIMARY_CONTROL_MIN_WIDTH = 180
SECONDARY_CONTROL_MIN_WIDTH = 110
STAGE_CARD_HORIZONTAL_PADDING = 24
WORKSPACE_LEFT_COLUMN_MIN_WIDTH = 260
WORKSPACE_CENTER_COLUMN_MIN_WIDTH = 420
WORKSPACE_RIGHT_COLUMN_MIN_WIDTH = 320

# PR-GUI-100: below this Pipeline width the three columns no longer fit at the normal form column minimums. Measured at
# 100% display scaling: the left Base Generation form needs ~552 px of viewport, reached at a ~1870 px wide tab, so the
# normal three-column presentation is kept from 1880 px up (a 1920 px display's usable width is 1896).
PIPELINE_COMPACT_BREAKPOINT_WIDTH = 1880
PIPELINE_MIN_REALIZED_WIDTH = 400
# Compact presentation lowers the grid-column minimums of the left/stage forms to this fraction (measured to leave every
# actionable control unclipped at the 1280 px minimum window); columns below the floor are left alone.
COMPACT_FORM_MINSIZE_SCALE = 0.6
COMPACT_FORM_MINSIZE_FLOOR = 60
# Descriptive labels wrap at no more than this while compact (their normal 400-880 px wraps exceed a narrow column),
# and Base Generation's unwrapped hint labels wrap at the hint length so the seed rows fit.
COMPACT_LABEL_WRAPLENGTH_CAP = 240
COMPACT_HINT_WRAPLENGTH = 90


def is_compact_pipeline_width(width: int) -> bool:
    """True when the realized Pipeline workspace is too narrow for the normal three-column form minimums.

    A width below ``PIPELINE_MIN_REALIZED_WIDTH`` is a not-yet-laid-out widget (Tk reports 1 px), not a narrow window.
    """
    return PIPELINE_MIN_REALIZED_WIDTH <= int(width) < PIPELINE_COMPACT_BREAKPOINT_WIDTH


def get_compact_minsize(minsize: int) -> int:
    """Compact form column minimum for a normal minimum (columns below the floor are not scaled)."""
    minsize = int(minsize)
    if minsize < COMPACT_FORM_MINSIZE_FLOOR:
        return minsize
    return max(1, int(minsize * COMPACT_FORM_MINSIZE_SCALE))


def build_form_column_specs(
    *,
    label_columns: Sequence[int] = (),
    primary_columns: Sequence[int] = (),
    secondary_columns: Sequence[int] = (),
    label_min_width: int = LABEL_COLUMN_MIN_WIDTH,
    primary_min_width: int = PRIMARY_CONTROL_MIN_WIDTH,
    secondary_min_width: int = SECONDARY_CONTROL_MIN_WIDTH,
    primary_weight: int = 1,
    secondary_weight: int = 1,
) -> tuple[dict[str, int], ...]:
    """Return normalized grid column specs for shared form rows."""
    columns = {int(index) for index in label_columns}
    columns.update(int(index) for index in primary_columns)
    columns.update(int(index) for index in secondary_columns)
    specs: list[dict[str, int]] = []
    for index in sorted(columns):
        if index in label_columns:
            specs.append({"index": index, "weight": 0, "minsize": int(label_min_width)})
        elif index in primary_columns:
            specs.append(
                {"index": index, "weight": int(primary_weight), "minsize": int(primary_min_width)}
            )
        else:
            specs.append(
                {
                    "index": index,
                    "weight": int(secondary_weight),
                    "minsize": int(secondary_min_width),
                }
            )
    return tuple(specs)


def get_two_pair_form_column_specs(
    *,
    primary_weight: int = 1,
    secondary_weight: int = 1,
    label_min_width: int = LABEL_COLUMN_MIN_WIDTH,
    primary_min_width: int = PRIMARY_CONTROL_MIN_WIDTH,
    secondary_min_width: int = SECONDARY_CONTROL_MIN_WIDTH,
) -> tuple[dict[str, int], ...]:
    return build_form_column_specs(
        label_columns=(0, 2),
        primary_columns=(1,),
        secondary_columns=(3,),
        label_min_width=label_min_width,
        primary_min_width=primary_min_width,
        secondary_min_width=secondary_min_width,
        primary_weight=primary_weight,
        secondary_weight=secondary_weight,
    )


def get_single_pair_form_column_specs(
    *,
    primary_weight: int = 1,
) -> tuple[dict[str, int], ...]:
    return build_form_column_specs(
        label_columns=(0,),
        primary_columns=(1,),
        primary_weight=primary_weight,
    )


def get_three_pair_form_column_specs(
    *,
    primary_weight: int = 3,
    secondary_weight: int = 2,
) -> tuple[dict[str, int], ...]:
    return build_form_column_specs(
        label_columns=(0, 2, 4),
        primary_columns=(1,),
        secondary_columns=(3, 5),
        primary_weight=primary_weight,
        secondary_weight=secondary_weight,
    )


def get_two_pane_workspace_column_specs(
    *,
    left_weight: int = 2,
    right_weight: int = 3,
    left_min_width: int = WORKSPACE_LEFT_COLUMN_MIN_WIDTH,
    right_min_width: int = WORKSPACE_CENTER_COLUMN_MIN_WIDTH,
) -> tuple[dict[str, int], ...]:
    return (
        {"index": 0, "weight": int(left_weight), "minsize": int(left_min_width)},
        {"index": 1, "weight": int(right_weight), "minsize": int(right_min_width)},
    )


def get_three_pane_workspace_column_specs(
    *,
    left_weight: int = 2,
    center_weight: int = 3,
    right_weight: int = 3,
    left_min_width: int = WORKSPACE_LEFT_COLUMN_MIN_WIDTH,
    center_min_width: int = WORKSPACE_CENTER_COLUMN_MIN_WIDTH,
    right_min_width: int = WORKSPACE_RIGHT_COLUMN_MIN_WIDTH,
) -> tuple[dict[str, int], ...]:
    return (
        {"index": 0, "weight": int(left_weight), "minsize": int(left_min_width)},
        {"index": 1, "weight": int(center_weight), "minsize": int(center_min_width)},
        {"index": 2, "weight": int(right_weight), "minsize": int(right_min_width)},
    )


def get_form_min_width(column_specs: Sequence[dict[str, int]], *, padding: int = 0) -> int:
    return sum(max(0, int(spec.get("minsize", 0))) for spec in column_specs) + max(0, int(padding))


def get_stage_card_min_width(*, padding: int = STAGE_CARD_HORIZONTAL_PADDING) -> int:
    return get_form_min_width(get_two_pair_form_column_specs(), padding=padding)


def get_visible_stage_order(stage_order: list[str], enabled_stages: list[str]) -> tuple[str, ...]:
    ordered = [str(name) for name in (stage_order or [])]
    enabled = {str(name) for name in (enabled_stages or [])}
    return tuple(name for name in ordered if name in enabled)


__all__ = [
    "COMPACT_FORM_MINSIZE_FLOOR",
    "COMPACT_FORM_MINSIZE_SCALE",
    "COMPACT_LABEL_WRAPLENGTH_CAP",
    "COMPACT_HINT_WRAPLENGTH",
    "PIPELINE_COMPACT_BREAKPOINT_WIDTH",
    "PIPELINE_MIN_REALIZED_WIDTH",
    "get_compact_minsize",
    "is_compact_pipeline_width",
    "LABEL_COLUMN_MIN_WIDTH",
    "PRIMARY_CONTROL_MIN_WIDTH",
    "SECONDARY_CONTROL_MIN_WIDTH",
    "STAGE_CARD_HORIZONTAL_PADDING",
    "WORKSPACE_LEFT_COLUMN_MIN_WIDTH",
    "WORKSPACE_CENTER_COLUMN_MIN_WIDTH",
    "WORKSPACE_RIGHT_COLUMN_MIN_WIDTH",
    "build_form_column_specs",
    "get_single_pair_form_column_specs",
    "get_two_pane_workspace_column_specs",
    "get_three_pane_workspace_column_specs",
    "get_two_pair_form_column_specs",
    "get_three_pair_form_column_specs",
    "get_form_min_width",
    "get_stage_card_min_width",
    "get_visible_stage_order",
]
