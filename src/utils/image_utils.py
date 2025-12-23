"""Image utility functions for thumbnail generation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)


def generate_thumbnail(
    image: "Image.Image",
    max_size: tuple[int, int] = (150, 150),
    *,
    preserve_aspect: bool = True,
    background: str | None = None,
) -> "Image.Image":
    """Generate a thumbnail from a PIL Image.

    Args:
        image: Source PIL Image
        max_size: Maximum (width, height) for thumbnail
        preserve_aspect: If True, maintain aspect ratio
        background: Optional background color for letterboxing

    Returns:
        Thumbnail as PIL Image
    """
    from PIL import Image as PILImage

    if preserve_aspect:
        # Use LANCZOS for high-quality downscaling
        thumb = image.copy()
        thumb.thumbnail(max_size, PILImage.Resampling.LANCZOS)

        if background:
            # Create background and paste thumbnail centered
            bg = PILImage.new("RGBA", max_size, background)
            x = (max_size[0] - thumb.width) // 2
            y = (max_size[1] - thumb.height) // 2

            # Handle transparency
            if thumb.mode == "RGBA":
                bg.paste(thumb, (x, y), thumb)
            else:
                bg.paste(thumb, (x, y))
            return bg

        return thumb
    else:
        return image.resize(max_size, PILImage.Resampling.LANCZOS)


def load_image_thumbnail(
    path: Path | str,
    max_size: tuple[int, int] = (150, 150),
    *,
    background: str | None = "#2a2a2a",
) -> "Image.Image | None":
    """Load an image file and return a thumbnail.

    Args:
        path: Path to image file
        max_size: Maximum thumbnail dimensions
        background: Background color for letterboxing

    Returns:
        Thumbnail PIL Image, or None on error
    """
    from PIL import Image as PILImage

    try:
        path = Path(path)
        if not path.exists():
            logger.debug(f"Thumbnail source not found: {path}")
            return None

        with PILImage.open(path) as img:
            # Convert to RGB if needed
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            return generate_thumbnail(img, max_size, background=background)

    except Exception as exc:
        logger.debug(f"Failed to load thumbnail from {path}: {exc}")
        return None
