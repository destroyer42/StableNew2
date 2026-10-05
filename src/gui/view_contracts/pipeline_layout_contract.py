"""Toolkit-agnostic layout contracts for Pipeline tab behavior."""

from __future__ import annotations

from collections.abc import Callable, Sequence

LABEL_COLUMN_MIN_WIDTH = 88
PRIMARY_CONTROL_MIN_WIDTH = 180
SECONDARY_CONTROL_MIN_WIDTH = 110
STAGE_CARD_HORIZONTAL_PADDING = 24
WORKSPACE_LEFT_COLUMN_MIN_WIDTH = 260
WORKSPACE_CENTER_COLUMN_MIN_WIDTH = 420
WORKSPACE_RIGHT_COLUMN_MIN_WIDTH = 320

# PR-GUI-100: the Pipeline chooses between its normal three-column presentation and a reversible compact presentation
# from whether the *rendered* layout fits (no actionable control wider than its scroll viewport), measured in the
# current Tk/font/scaling environment. No fixed pixel breakpoint: fonts, display scaling and the Tk build all change how
# much width the forms need.
#
# A width below this is a not-yet-laid-out widget (Tk reports 1 px), not a narrow window.
PIPELINE_MIN_REALIZED_WIDTH = 400
# Compact form column minimums are scaled by the largest of these that makes the layout fit (least compaction first).
COMPACT_MINSIZE_SCALES = (0.8, 0.7, 0.6, 0.5, 0.4)
# Grid columns below this declared minimum are not scaled.
COMPACT_FORM_MINSIZE_FLOOR = 60
# Descriptive labels wrap at no more than this while compact (their normal 400-880 px wraps exceed a narrow column),
# and Base Generation's unwrapped hint labels wrap at the hint length so the seed rows fit.
COMPACT_LABEL_WRAPLENGTH_CAP = 240
COMPACT_HINT_WRAPLENGTH = 90
# Hysteresis: after the normal presentation fails to fit at width W it is probed again only once the width has grown by
# this much, so resizing cannot oscillate between presentations.
PIPELINE_PROBE_STEP = 24
# Pixels a control may overhang its viewport and still count as fitting (borders/rounding).
LAYOUT_FIT_TOLERANCE = 1


def pipeline_layout_fits(
    extents: Sequence[tuple[int, int]], *, tolerance: int = LAYOUT_FIT_TOLERANCE
) -> bool:
    """True when every (required_width, available_width) pair fits: nothing needs more than its viewport offers."""
    return all(int(required) <= int(available) + int(tolerance) for required, available in extents)


def select_compact_scale(
    fits_at: Callable[[float], bool], scales: Sequence[float] = COMPACT_MINSIZE_SCALES
) -> tuple[float, bool]:
    """Least-compact scale for which ``fits_at(scale)`` holds, as (scale, fits); the smallest scale if none fits."""
    for scale in scales:
        if fits_at(scale):
            return scale, True
    return scales[-1], False


def should_probe_normal_layout(
    width: int, unfit_width: int | None, *, step: int = PIPELINE_PROBE_STEP
) -> bool:
    """Whether the compact Pipeline should try the normal presentation again at ``width``.

    ``unfit_width`` is the widest width at which the normal presentation was measured not to fit (None: never tried).
    """
    return unfit_width is None or int(width) >= int(unfit_width) + int(step)


def should_refit_compact(width: int, search_width: int, *, step: int = PIPELINE_PROBE_STEP) -> bool:
    """Whether a compact layout that still fits should look for a less compact scale (the window has grown)."""
    return int(width) >= int(search_width) + int(step)


def get_compact_minsize(minsize: int, scale: float) -> int:
    """Compact form column minimum for a normal minimum (columns below the floor are not scaled)."""
    minsize = int(minsize)
    if minsize < COMPACT_FORM_MINSIZE_FLOOR:
        return minsize
    return max(1, int(minsize * float(scale)))


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
    "COMPACT_MINSIZE_SCALES",
    "LAYOUT_FIT_TOLERANCE",
    "PIPELINE_PROBE_STEP",
    "COMPACT_LABEL_WRAPLENGTH_CAP",
    "COMPACT_HINT_WRAPLENGTH",
    "PIPELINE_MIN_REALIZED_WIDTH",
    "get_compact_minsize",
    "pipeline_layout_fits",
    "select_compact_scale",
    "should_probe_normal_layout",
    "should_refit_compact",
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
