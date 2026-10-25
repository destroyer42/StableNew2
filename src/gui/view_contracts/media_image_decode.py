"""Bounded image inspection on workers, reusing the thumbnail utilities and preserving source identity."""

import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from src.utils.image_utils import generate_thumbnail

MAX_SOURCE_PIXELS = 16_000_000  # refuse before allocating a source bitmap (~64 MB RGBA)
PREVIEW_EDGE = 1536  # at most ~9 MB RGBA retained; rendered viewports capped separately
VIEWPORT_EDGE = 2048  # at most 16 MB of PhotoImage input, regardless of zoom/pan


@dataclass
class InspectionImage:
    image: Image.Image
    source_size: tuple[int, int]

    @property
    def native(self) -> bool:
        return bool(self.image.size == self.source_size)


def decode_inspection_image(path: str, cancel: threading.Event) -> InspectionImage:
    if cancel.is_set():
        raise ValueError("Image load canceled")
    if not Path(path).is_file():
        raise ValueError("Media file is missing")
    try:
        with Image.open(path) as source:
            size = source.size
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise ValueError(
                    "Image exceeds the 16 megapixel inspection budget; use Open original where available"
                )
            if cancel.is_set():
                raise ValueError("Image load canceled")
            image = generate_thumbnail(source, (PREVIEW_EDGE, PREVIEW_EDGE))
            image = image.convert("RGBA")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Image is corrupt or unsupported") from exc
    if cancel.is_set():
        image.close()
        raise ValueError("Image load canceled")
    return InspectionImage(image, size)


def render_viewport(
    image: Image.Image, viewport: tuple[int, int], zoom: float | None, origin: tuple[float, float]
) -> tuple[Image.Image, tuple[int, int], tuple[int, int]]:
    """Resize/crop on the worker. Virtual scroll size may be large; the allocated bitmap never is."""
    width, height = (min(VIEWPORT_EDGE, max(1, edge)) for edge in viewport)
    scale = min(width / image.width, height / image.height, 1.0) if zoom is None else zoom
    virtual = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    x = max(0, min(round(origin[0] * virtual[0]), max(0, virtual[0] - width)))
    y = max(0, min(round(origin[1] * virtual[1]), max(0, virtual[1] - height)))
    right, bottom = min(virtual[0], x + width), min(virtual[1], y + height)
    crop = image.crop((x / scale, y / scale, right / scale, bottom / scale))
    rendered = crop.resize((max(1, right - x), max(1, bottom - y)), Image.Resampling.LANCZOS)
    return (
        rendered,
        virtual,
        (x + max(0, (width - virtual[0]) // 2), y + max(0, (height - virtual[1]) // 2)),
    )
