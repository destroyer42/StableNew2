"""How much work a design would create, before any Preview is built.

The counts use the same rules the Preview later applies (the controller's inclusive stepped range, the selected
items, the selected models) but only count; nothing is compiled, resolved against the backend or queued. A design
that cannot be counted yet (an invalid or incomplete form) reports ``None`` rather than guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_RANGE_LIMIT = 1000


@dataclass(frozen=True)
class DesignEstimate:
    variants: int | None
    images_per_variant: int
    note: str = ""

    @property
    def total_images(self) -> int | None:
        return None if self.variants is None else self.variants * self.images_per_variant

    def text(self) -> str:
        if self.variants is None:
            return (
                self.note
                or "Estimated work: complete the design to see the number of variants and images."
            )
        noun = "variant" if self.variants == 1 else "variants"
        per = "image" if self.images_per_variant == 1 else "images"
        return (
            f"Estimated work: {self.variants} {noun} x {self.images_per_variant} {per} "
            f"= {self.total_images} images (nothing is queued until you Run)."
        )


def range_values(start: float, end: float, step: float) -> list[float] | None:
    """The inclusive stepped range, or ``None`` when it is not a valid range.

    Each value is computed from its index rather than by repeated addition, so ``0.2..0.6`` by ``0.2`` yields
    ``0.2, 0.4, 0.6`` instead of losing the end value to accumulated float error.
    """
    if step <= 0 or start > end:
        return None
    count = int((end - start) / step + 1e-9) + 1
    if count > _RANGE_LIMIT:
        return None
    return [round(start + index * step, 2) for index in range(count)]


def count_range_values(start: float, end: float, step: float) -> int | None:
    """Number of values in the inclusive stepped range, or ``None`` when it is not a valid range."""
    values = range_values(start, end, step)
    return None if values is None else len(values)


def estimate_design(
    *,
    study_type: str,
    value_type: str,
    images_per_value: int,
    start: float = 0.0,
    end: float = 0.0,
    step: float = 0.0,
    selected_items: Sequence[str] = (),
    lora_comparison: bool = False,
    selected_loras: Sequence[str] = (),
    strength_start: float = 0.0,
    strength_end: float = 0.0,
    strength_step: float = 0.0,
    selected_models: Sequence[str] = (),
    grid_cells: int | None = None,
) -> DesignEstimate:
    images = max(1, int(images_per_value or 1))
    if study_type == "two_axis_grid":
        return DesignEstimate(
            grid_cells, images, "Estimated work: finish both axes to see the number of cells."
        )
    if study_type == "model_comparison":
        count = len(selected_models)
        if count < 2:
            return DesignEstimate(
                None, images, "Estimated work: select at least two models to compare."
            )
        return DesignEstimate(count, images)
    if value_type in {"discrete", "resource"}:
        count = len(selected_items)
        return DesignEstimate(
            count or None, images, "Estimated work: select at least one item to test."
        )
    if value_type == "composite":
        if lora_comparison:
            count = len(selected_loras)
            return DesignEstimate(
                count or None, images, "Estimated work: select at least one LoRA to compare."
            )
        return DesignEstimate(
            count_range_values(strength_start, strength_end, strength_step),
            images,
            "Estimated work: enter a valid strength range (start below end, positive step).",
        )
    if value_type == "numeric":
        return DesignEstimate(
            count_range_values(start, end, step),
            images,
            "Estimated work: enter a valid range (start below end, positive step).",
        )
    return DesignEstimate(None, images, "Estimated work: choose the setting to test.")


__all__ = ["DesignEstimate", "count_range_values", "estimate_design"]
