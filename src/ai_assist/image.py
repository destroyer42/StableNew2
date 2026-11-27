"""The one way a picture is prepared for a request: reduced, re-encoded and stripped of every metadata field.

Re-encoding from pixels drops PNG text chunks (which hold generation prompts), EXIF and colour profiles. Reads the file
it is given and writes nothing; call it off the GUI thread.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

from src.ai_assist.contracts import MAX_IMAGE_BYTES

#: Long edge sent to the model. At Qwen's 32 px per token this keeps an image near 256 tokens of the 4096 context.
MAX_IMAGE_EDGE = 512


def prepare_image(path: str | Path) -> bytes:
    """JPEG bytes of at most :data:`MAX_IMAGE_BYTES`. Raises ``OSError`` or ``ValueError`` for an unreadable picture."""

    with Image.open(path) as source:
        picture = ImageOps.exif_transpose(source).convert("RGB")
    picture.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    clean = Image.new("RGB", picture.size)
    clean.paste(picture)
    for quality in (85, 70, 55):
        buffer = io.BytesIO()
        clean.save(buffer, "JPEG", quality=quality)
        if buffer.tell() <= MAX_IMAGE_BYTES:
            return buffer.getvalue()
    raise ValueError("the picture could not be reduced far enough")


__all__ = ["MAX_IMAGE_EDGE", "prepare_image"]
