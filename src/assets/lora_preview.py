"""Bounded, read-only local adapter preview access. Worker-only; no Tk objects."""

from __future__ import annotations

import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps

MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_PIXELS = 16_000_000
THUMBNAIL_SIZE = (128, 128)


def local_preview_path(adapter: Path, root: Path) -> Path | None:
    for suffix in (".preview.png", ".preview.jpg", ".preview.webp", ".png", ".jpg", ".webp"):
        candidate = adapter.with_suffix(suffix)
        if candidate.resolve().is_relative_to(root.resolve()) and candidate.is_file():
            return candidate
    return None


def read_thumbnail(path: Path | None, root: Path) -> Image.Image | None:
    """Decode only one requested preview, with byte/pixel limits and containment rechecked."""
    if path is None:
        return None
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_PREVIEW_BYTES + 1)
        if len(raw) > MAX_PREVIEW_BYTES:
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # Restrict content detection before decoding: EPS and other plugins can invoke
            # external programs or create temporary files even under a raster filename.
            with Image.open(io.BytesIO(raw), formats=("PNG", "JPEG", "WEBP")) as image:
                if image.width * image.height > MAX_PREVIEW_PIXELS:
                    return None
                image.thumbnail(THUMBNAIL_SIZE)
                return ImageOps.exif_transpose(image).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None
