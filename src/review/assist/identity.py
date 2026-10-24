"""Reading the operator's source image once and binding every request to its exact bytes (PR-IMG-REVIEW-320).

The file goes through the same bounded reader and validator the mask editor freezes (``read_source``): byte, side, pixel,
format, single-frame and decompression limits are one envelope. The decoded pixels are what the mask editor displays
(Pillow ``convert("RGB")``, EXIF rotation recorded but not applied), so a mask proposed here has exactly the size the
frozen edit contract requires. Blocking work: call from a worker, never from Tk.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.conditioning.openpose import SUPPORTED_EXTENSIONS
from src.conditioning.openpose_library import MAX_FILE_BYTES
from src.pipeline.image_edit_inputs import read_source
from src.review.assist.contracts import (
    CODE_SOURCE,
    CODE_SOURCE_CHANGED,
    AssistError,
    SourceIdentity,
)

_HASH_CHUNK = 1024 * 1024
_EXIF_ORIENTATION = 0x0112


@dataclass(frozen=True, slots=True)
class LoadedSource:
    identity: SourceIdentity
    #: Stored pixels as the mask editor shows them, shape ``(height, width, 3)``, ``uint8``, C-contiguous.
    rgb: np.ndarray


def _resolve(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise AssistError(CODE_SOURCE, "The source image must be a PNG, JPEG or WEBP file.")
    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError as exc:
        raise AssistError(CODE_SOURCE, "The source image was not found.") from exc
    if not resolved.is_file():
        raise AssistError(CODE_SOURCE, "The selected source is not an image file.")
    return resolved


def load_source(path: Path | str) -> LoadedSource:
    """Read, validate and decode one image. Raises ``AssistError(source_invalid)`` with a path-free message."""

    from PIL import Image

    resolved = _resolve(path)
    try:
        source = read_source(resolved)
        with Image.open(io.BytesIO(source.data)) as image:
            orientation = int(image.getexif().get(_EXIF_ORIENTATION, 1) or 1)
            rgb = np.ascontiguousarray(np.asarray(image.convert("RGB"), dtype=np.uint8))
    except (ValueError, OSError) as exc:
        raise AssistError(CODE_SOURCE, "The source image is not a readable still image.") from exc
    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    if (width, height) != (source.width, source.height):
        raise AssistError(CODE_SOURCE, "The decoded image does not match its header.")
    identity = SourceIdentity(
        file_sha256=source.sha256,
        file_size=source.size,
        width=width,
        height=height,
        exif_orientation=orientation,
        image_format=source.image_format,
    )
    return LoadedSource(identity, rgb)


def current_file_sha256(path: Path | str) -> str:
    """Streamed SHA-256 of the file as it is now (never a second source of pixels)."""

    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        digest = hashlib.sha256()
        total = 0
        with resolved.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    raise AssistError(
                        CODE_SOURCE_CHANGED, "The source image changed; analyze it again."
                    )
                digest.update(chunk)
    except OSError as exc:
        raise AssistError(
            CODE_SOURCE_CHANGED, "The source image is no longer readable; analyze it again."
        ) from exc
    return digest.hexdigest()


def reverify_source(path: Path | str, identity: SourceIdentity) -> None:
    """Refuse when the file no longer has the bytes this request was made from."""

    if current_file_sha256(path) != identity.file_sha256:
        raise AssistError(
            CODE_SOURCE_CHANGED,
            "The source image changed after it was analyzed; analyze it again before using a suggestion.",
        )


__all__ = ["LoadedSource", "current_file_sha256", "load_source", "reverify_source"]
