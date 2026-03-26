"""Toolkit-agnostic layout contracts for Pipeline tab behavior."""

from __future__ import annotations

from collections.abc import Sequence


LABEL_COLUMN_MIN_WIDTH = 88
PRIMARY_CONTROL_MIN_WIDTH = 180
SECONDARY_CONTROL_MIN_WIDTH = 110
STAGE_CARD_HORIZONTAL_PADDING = 24


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
    columns = set(int(index) for index in label_columns)
    columns.update(int(index) for index in primary_columns)
    columns.update(int(index) for index in secondary_columns)
    specs: list[dict[str, int]] = []
    for index in sorted(columns):
        if index in label_columns:
            specs.append({"index": index, "weight": 0, "minsize": int(label_min_width)})
        elif index in primary_columns:
            specs.append({"index": index, "weight": int(primary_weight), "minsize": int(primary_min_width)})
        else:
            specs.append(
                {"index": index, "weight": int(secondary_weight), "minsize": int(secondary_min_width)}
            )
    return tuple(specs)


def get_two_pair_form_column_specs(
    *,
    primary_weight: int = 1,
    secondary_weight: int = 1,
) -> tuple[dict[str, int], ...]:
    return build_form_column_specs(
        label_columns=(0, 2),
        primary_columns=(1,),
        secondary_columns=(3,),
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


def get_form_min_width(column_specs: Sequence[dict[str, int]], *, padding: int = 0) -> int:
    return sum(max(0, int(spec.get("minsize", 0))) for spec in column_specs) + max(0, int(padding))


def get_stage_card_min_width(*, padding: int = STAGE_CARD_HORIZONTAL_PADDING) -> int:
    return get_form_min_width(get_two_pair_form_column_specs(), padding=padding)


def normalize_window_geometry(current_geometry: str, min_width: int) -> str | None:
    """Return updated geometry string if width is below minimum, else None."""
    text = str(current_geometry or "")
    if "x" not in text:
        return None
    width_str, rest = text.split("x", 1)
    try:
        width = int(width_str)
        required = max(0, int(min_width))
    except Exception:
        return None
    if width >= required:
        return None
    parts = rest.split("+")
    height = parts[0]
    if not height:
        return None
    if len(parts) >= 3 and parts[1] and parts[2]:
        return f"{required}x{height}+{parts[1]}+{parts[2]}"
    return f"{required}x{height}"


def get_visible_stage_order(stage_order: list[str], enabled_stages: list[str]) -> tuple[str, ...]:
    ordered = [str(name) for name in (stage_order or [])]
    enabled = {str(name) for name in (enabled_stages or [])}
    return tuple(name for name in ordered if name in enabled)


__all__ = [
    "LABEL_COLUMN_MIN_WIDTH",
    "PRIMARY_CONTROL_MIN_WIDTH",
    "SECONDARY_CONTROL_MIN_WIDTH",
    "STAGE_CARD_HORIZONTAL_PADDING",
    "build_form_column_specs",
    "get_single_pair_form_column_specs",
    "get_two_pair_form_column_specs",
    "get_three_pair_form_column_specs",
    "get_form_min_width",
    "get_stage_card_min_width",
    "normalize_window_geometry",
    "get_visible_stage_order",
]
