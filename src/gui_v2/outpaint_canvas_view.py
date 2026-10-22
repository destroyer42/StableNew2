"""Toolkit-neutral view of an outpaint canvas: where the original sits as the margins change. No Tk, files or backend."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from src.gui_v2.mask_editor_state import MaskViewport
from src.pipeline.outpaint_canvas import Extents

_BACKGROUND = (35, 35, 35)
_NEW_AREA = (58, 70, 112)
_BOUNDARY = (255, 214, 64)
_EDGE = (150, 150, 150)
Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class CanvasView:
    scale: float
    canvas: Rect
    original: Rect


def canvas_view(
    original_size: tuple[int, int], extents: Extents, view: tuple[int, int], margin: int = 12
) -> CanvasView:
    """Fit the *expanded* canvas into the view with the existing viewport transform; the original is anchored at (L, T)."""
    expanded = (
        original_size[0] + extents.left + extents.right,
        original_size[1] + extents.top + extents.bottom,
    )
    inner = (max(1, view[0] - 2 * margin), max(1, view[1] - 2 * margin))
    viewport = MaskViewport()
    viewport.fit(expanded, inner)
    left, top = viewport.x + margin, viewport.y + margin
    scale = viewport.scale
    return CanvasView(
        scale,
        (left, top, left + expanded[0] * scale, top + expanded[1] * scale),
        (
            left + extents.left * scale,
            top + extents.top * scale,
            left + (extents.left + original_size[0]) * scale,
            top + (extents.top + original_size[1]) * scale,
        ),
    )


def render_canvas_view(
    proxy: Image.Image,
    original_size: tuple[int, int],
    extents: Extents,
    size: tuple[int, int],
    *,
    show_mask: bool = False,
) -> Image.Image:
    """Draw the proposed canvas from a small proxy of the original; cheap enough for the Tk thread."""
    view = canvas_view(original_size, extents, size)
    image = Image.new("RGB", size, _BACKGROUND)
    draw = ImageDraw.Draw(image)
    canvas = tuple(round(value) for value in view.canvas)
    original = tuple(round(value) for value in view.original)
    draw.rectangle(canvas, fill=(255, 255, 255) if show_mask else _NEW_AREA)
    width, height = max(1, original[2] - original[0]), max(1, original[3] - original[1])
    if show_mask:
        draw.rectangle(original, fill=(0, 0, 0))
    else:
        image.paste(proxy.resize((width, height), Image.Resampling.BILINEAR), original[:2])
    draw.rectangle(canvas, outline=_EDGE)
    draw.rectangle(original, outline=_BOUNDARY)
    return image
