"""Reading the operator's source image once, safely and reproducibly (PR-IMG-CNET-230).

The file is read a single time through the same bounded reader and validator the library uses, so the byte, side, pixel,
format and decompression limits are one envelope. The EXIF-oriented RGB pixels are what every modality sees, and both the
file hash and the oriented-pixel hash are recorded before inference. Blocking work: call from a worker, never from Tk.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.conditioning.openpose import SUPPORTED_EXTENSIONS
from src.conditioning.openpose_library import (
    CODE_DIMENSIONS,
    CODE_MALFORMED,
    MAX_FILE_BYTES,
    MAX_SIDE,
    MIN_SIDE,
    OpenPoseInputError,
    read_bounded_file,
    validate_image_bytes,
)
from src.conditioning.reference_map.contracts import (
    CODE_SOURCE_CHANGED,
    SOURCE_CODE_PREFIX,
    ReferenceMapError,
    SourceFacts,
)

CODE_NOT_A_FILE = "not_a_file"
CODE_EXTENSION = "extension"
_HASH_CHUNK = 1024 * 1024
_ORIENTED_DOMAIN = b"stablenew.oriented-rgb8.v1"


@dataclass(frozen=True, slots=True)
class LoadedSource:
    facts: SourceFacts
    #: Oriented RGB pixels, shape ``(height, width, 3)``, ``uint8``, C-contiguous.
    rgb: np.ndarray


def _refuse(code: str, message: str) -> ReferenceMapError:
    return ReferenceMapError(SOURCE_CODE_PREFIX + code, message)


def oriented_digest(rgb: np.ndarray) -> str:
    """SHA-256 of the oriented pixels, domain-separated and bound to the dimensions."""

    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    digest = hashlib.sha256()
    digest.update(_ORIENTED_DOMAIN)
    digest.update(width.to_bytes(4, "little"))
    digest.update(height.to_bytes(4, "little"))
    digest.update(np.ascontiguousarray(rgb).tobytes())
    return digest.hexdigest()


def _resolve(path: Path) -> Path:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise _refuse(CODE_EXTENSION, "The source image must be a PNG, JPEG or WEBP file.")
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise _refuse("missing", "The source image was not found.") from exc
    if not resolved.is_file():
        raise _refuse(CODE_NOT_A_FILE, "The selected source is not an image file.")
    return resolved


def _decode_oriented(data: bytes) -> tuple[np.ndarray, bool]:
    from PIL import Image, ImageOps

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                orientation = image.getexif().get(0x0112, 1)
                oriented = ImageOps.exif_transpose(image)
                if oriented.mode in {"RGBA", "LA", "PA"} or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                    canvas.alpha_composite(rgba)
                    rgb_image = canvas.convert("RGB")
                else:
                    rgb_image = oriented.convert("RGB")
                rgb = np.ascontiguousarray(np.asarray(rgb_image, dtype=np.uint8))
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ) as exc:
        raise _refuse(CODE_MALFORMED, "The source image is not a readable image.") from exc
    return rgb, orientation not in (None, 0, 1)


def load_source(path: Path | str) -> LoadedSource:
    """Read, validate and orient one source image. Raises ``ReferenceMapError`` with a ``source_*`` code."""

    resolved = _resolve(Path(path))
    try:
        data = read_bounded_file(resolved)
        _, _, image_format = validate_image_bytes(data)
    except OpenPoseInputError as exc:
        raise _refuse(exc.code, str(exc)) from exc
    rgb, transposed = _decode_oriented(data)
    height, width = int(rgb.shape[0]), int(rgb.shape[1])
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise _refuse(
            CODE_DIMENSIONS, "The oriented source image is outside the supported size range."
        )
    facts = SourceFacts(
        file_sha256=hashlib.sha256(data).hexdigest(),
        file_size=len(data),
        image_format=image_format,
        width=width,
        height=height,
        oriented_sha256=oriented_digest(rgb),
        exif_transposed=transposed,
    )
    return LoadedSource(facts, rgb)


def reverify_source(path: Path | str, expected_sha256: str) -> None:
    """Refuse publication when the source file no longer has the bytes the map was prepared from.

    This is a streamed hash of the file as it is now, not a second source of pixels.
    """

    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        digest = hashlib.sha256()
        total = 0
        with resolved.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ReferenceMapError(
            CODE_SOURCE_CHANGED, "The source image is no longer readable; create the map again."
        ) from exc
    if total > MAX_FILE_BYTES or digest.hexdigest() != expected_sha256:
        raise ReferenceMapError(
            CODE_SOURCE_CHANGED,
            "The source image changed after the preview was made; create the map again before saving.",
        )


__all__ = [
    "CODE_EXTENSION",
    "CODE_NOT_A_FILE",
    "LoadedSource",
    "load_source",
    "oriented_digest",
    "reverify_source",
]
