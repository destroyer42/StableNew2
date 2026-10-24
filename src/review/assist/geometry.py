"""Pointer-to-pixel mapping, prompt validation and overlay composition; no Tk, files or models (PR-IMG-REVIEW-320).

The viewport is the mask editor's own ``MaskViewport`` (canvas = image * scale + offset), so letterboxing from Fit, zoom and
pan all map back to original image pixels through one tested transform. A pointer outside the image is refused, never clamped.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PIL import Image, ImageDraw

from src.gui_v2.mask_editor_state import MaskViewport
from src.review.assist.contracts import (
    CODE_PROMPT,
    MAX_BOXES,
    MAX_POINTS,
    AssistError,
    BoxPrompt,
    PointPrompt,
)

MIN_BOX_SIDE = 4
_PROPOSAL_COLOUR = (0, 190, 255)
_POSITIVE_COLOUR = (40, 220, 80)
_NEGATIVE_COLOUR = (255, 60, 60)
_BOX_COLOUR = (255, 220, 0)


def canvas_to_image(
    viewport: MaskViewport, x: float, y: float, size: tuple[int, int]
) -> tuple[int, int] | None:
    """Original pixel under a canvas position, or ``None`` when the pointer is not over the image."""

    if not (math.isfinite(x) and math.isfinite(y)) or viewport.scale <= 0:
        return None
    ix, iy = viewport.image_point(x, y)
    if not (0 <= ix < size[0] and 0 <= iy < size[1]):
        return None
    return int(math.floor(ix)), int(math.floor(iy))


def image_to_canvas(viewport: MaskViewport, x: float, y: float) -> tuple[float, float]:
    """Canvas position of the centre of original pixel ``(x, y)``."""

    return (x + 0.5) * viewport.scale + viewport.x, (y + 0.5) * viewport.scale + viewport.y


def point_at(
    viewport: MaskViewport, x: float, y: float, size: tuple[int, int], *, positive: bool
) -> PointPrompt:
    pixel = canvas_to_image(viewport, x, y, size)
    if pixel is None:
        raise AssistError(CODE_PROMPT, "Click on the image. Points outside the image are ignored.")
    return PointPrompt(pixel[0], pixel[1], positive)


def box_from_drag(
    viewport: MaskViewport,
    start: tuple[float, float],
    end: tuple[float, float],
    size: tuple[int, int],
) -> BoxPrompt:
    """A box from a drag. It must start on the image; the far corner is held to the image edge."""

    first = canvas_to_image(viewport, start[0], start[1], size)
    if first is None:
        raise AssistError(
            CODE_PROMPT, "Start the box on the image. Boxes starting outside are ignored."
        )
    if not (math.isfinite(end[0]) and math.isfinite(end[1])):
        raise AssistError(CODE_PROMPT, "The box end is not a valid position.")
    ex, ey = viewport.image_point(end[0], end[1])
    second = (
        min(max(int(math.floor(ex)), 0), size[0] - 1),
        min(max(int(math.floor(ey)), 0), size[1] - 1),
    )
    box = BoxPrompt(
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[0], second[0]),
        max(first[1], second[1]),
    )
    if box.x2 - box.x1 < MIN_BOX_SIDE or box.y2 - box.y1 < MIN_BOX_SIDE:
        raise AssistError(
            CODE_PROMPT, f"The box is too small; drag at least {MIN_BOX_SIDE} pixels each way."
        )
    return box


def validate_prompts(
    points: Sequence[PointPrompt], boxes: Sequence[BoxPrompt], size: tuple[int, int]
) -> None:
    """Refuse an unusable prompt set before any model is touched."""

    if len(points) > MAX_POINTS or len(boxes) > MAX_BOXES:
        raise AssistError(CODE_PROMPT, f"Use at most {MAX_POINTS} points and {MAX_BOXES} box.")
    if not any(point.positive for point in points) and not boxes:
        raise AssistError(
            CODE_PROMPT, "Click a foreground point on the object, or draw a box around it."
        )
    width, height = size
    for point in points:
        if (
            type(point.x) is not int
            or type(point.y) is not int
            or not (0 <= point.x < width and 0 <= point.y < height)
        ):
            raise AssistError(CODE_PROMPT, "A point is outside the image.")
    for box in boxes:
        coordinates = (box.x1, box.y1, box.x2, box.y2)
        if any(type(value) is not int for value in coordinates):
            raise AssistError(CODE_PROMPT, "A box coordinate is not a whole pixel.")
        if not (0 <= box.x1 < box.x2 < width and 0 <= box.y1 < box.y2 < height):
            raise AssistError(CODE_PROMPT, "A box is outside the image or empty.")


def compose_overlay(
    image: Image.Image,
    mask: Image.Image | None,
    viewport: MaskViewport,
    view_size: tuple[int, int],
    *,
    points: Sequence[PointPrompt] = (),
    boxes: Sequence[BoxPrompt] = (),
) -> Image.Image:
    """The visible canvas: the source with the proposed mask tinted over it and the prompts drawn. Inputs are never mutated."""

    transform = (
        1 / viewport.scale,
        0,
        -viewport.x / viewport.scale,
        0,
        1 / viewport.scale,
        -viewport.y / viewport.scale,
    )
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    view = rgb.transform(
        view_size,
        Image.Transform.AFFINE,
        transform,
        resample=Image.Resampling.BILINEAR,
        fillcolor=(35, 35, 35),
    )
    if mask is not None:
        shown = mask.transform(
            view_size, Image.Transform.AFFINE, transform, resample=Image.Resampling.NEAREST
        )
        alpha = shown.point(lambda value: value * 120 // 255)
        view = Image.composite(Image.new("RGB", view_size, _PROPOSAL_COLOUR), view, alpha)
    draw = ImageDraw.Draw(view)
    for box in boxes:
        left, top = image_to_canvas(viewport, box.x1, box.y1)
        right, bottom = image_to_canvas(viewport, box.x2, box.y2)
        draw.rectangle((left, top, right, bottom), outline=_BOX_COLOUR, width=2)
    for point in points:
        cx, cy = image_to_canvas(viewport, point.x, point.y)
        colour = _POSITIVE_COLOUR if point.positive else _NEGATIVE_COLOUR
        draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), outline=colour, width=3)
        draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=colour)
    return view


__all__ = [
    "MIN_BOX_SIDE",
    "box_from_drag",
    "canvas_to_image",
    "compose_overlay",
    "image_to_canvas",
    "point_at",
    "validate_prompts",
]
