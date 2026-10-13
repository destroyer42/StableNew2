"""The OpenPose reference-image library: safe resolution, bounded validation, thumbnails (PR-IMG-CNET-210).

The library is ``<configured WebUI root>/models/OpenPose`` (nested folders, relative identities). These helpers are the
one place a library image becomes bytes, so the picker, the compiler and the dispatch check all enforce the same
envelope: a path can never leave the library, a file is read once (hash, decode and snapshot come from the same bytes),
and size/dimension/format limits are explicit.

They do blocking file and image work and therefore belong on a worker thread, never on Tk.
"""

from __future__ import annotations

import hashlib
import io
import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from src.conditioning.openpose import ConditioningError, normalize_asset_identity

LIBRARY_SUBDIRS = ("models", "OpenPose")
MAX_FILE_BYTES = 20 * 1024 * 1024
MIN_SIDE = 64
MAX_SIDE = 4096
MAX_PIXELS = MAX_SIDE * MAX_SIDE
_ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

#: Stable, content-free failure codes (tests and callers branch on these, never on message text).
CODE_NO_LIBRARY = "no_library"
CODE_UNSUPPORTED = "unsupported"
CODE_ESCAPE = "escape"
CODE_MISSING = "missing"
CODE_UNREADABLE = "unreadable"
CODE_OVERSIZED = "oversized"
CODE_MALFORMED = "malformed"
CODE_DIMENSIONS = "dimensions"
CODE_CHANGED = "changed"


class OpenPoseInputError(ConditioningError):
    """A conditioning image cannot be used. ``code`` is machine-readable; the message is operator-facing."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    """One image read exactly once: the bytes plus the facts derived from those same bytes."""

    data: bytes
    sha256: str
    size: int
    width: int
    height: int
    image_format: str


def library_root(webui_root: Path | str | None) -> Path | None:
    """``<webui_root>/models/OpenPose`` (not required to exist), or ``None`` without a configured WebUI root."""

    if webui_root is None or not str(webui_root).strip():
        return None
    return Path(str(webui_root)).expanduser().joinpath(*LIBRARY_SUBDIRS)


def resolve_library_file(root: Path | str | None, identity: str) -> Path:
    """The real file a library identity names; refuses anything outside the library or not a supported file.

    The identity is normalized first (relative, no traversal, supported extension), then resolved through the
    filesystem, so a symlink or junction that leaves the library root is refused rather than followed.
    """

    try:
        normalized = normalize_asset_identity(identity)
    except ValueError as exc:
        text = str(exc)
        code = CODE_UNSUPPORTED if "must be one of" in text else CODE_ESCAPE
        raise OpenPoseInputError(code, f"OpenPose image '{_shown(identity)}' is not valid: {text}") from exc
    if root is None:
        raise OpenPoseInputError(
            CODE_NO_LIBRARY,
            "The OpenPose library is unavailable: configure the Stable Diffusion WebUI root "
            "(the library lives in models/OpenPose).",
        )
    try:
        root_resolved = Path(root).resolve(strict=True)
    except OSError as exc:
        raise OpenPoseInputError(
            CODE_NO_LIBRARY,
            "The OpenPose library folder (models/OpenPose under the WebUI root) does not exist.",
        ) from exc
    try:
        resolved = root_resolved.joinpath(*normalized.split("/")).resolve(strict=True)
    except FileNotFoundError as exc:
        raise OpenPoseInputError(
            CODE_MISSING, f"OpenPose image '{normalized}' is not in the library (it was moved or deleted)."
        ) from exc
    except OSError as exc:
        raise OpenPoseInputError(CODE_UNREADABLE, f"OpenPose image '{normalized}' cannot be read.") from exc
    if not resolved.is_relative_to(root_resolved):
        raise OpenPoseInputError(
            CODE_ESCAPE, f"OpenPose image '{normalized}' resolves outside the OpenPose library and was refused."
        )
    if not resolved.is_file():
        raise OpenPoseInputError(CODE_MISSING, f"OpenPose image '{normalized}' is not a file in the library.")
    return resolved


def _shown(value: object) -> str:
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def validate_image_bytes(data: bytes) -> tuple[int, int, str]:
    """``(width, height, format)`` of a complete, in-envelope PNG/JPEG/WEBP, or ``OpenPoseInputError``.

    Dimensions are checked from the header before any pixel is decoded, then the image is fully decoded so a truncated or
    corrupt file is refused here rather than by the backend.
    """

    from PIL import Image, UnidentifiedImageError

    if not data:
        raise OpenPoseInputError(CODE_MALFORMED, "The OpenPose image is empty.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                fmt = str(image.format or "")
                width, height = image.size
                if fmt not in _ALLOWED_FORMATS:
                    raise OpenPoseInputError(
                        CODE_MALFORMED, "The OpenPose image must be a PNG, JPEG or WEBP file."
                    )
                if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE) or (
                    width * height > MAX_PIXELS
                ):
                    raise OpenPoseInputError(
                        CODE_DIMENSIONS,
                        f"The OpenPose image is {width}x{height}; each side must be {MIN_SIDE}-{MAX_SIDE} pixels.",
                    )
                image.load()
    except OpenPoseInputError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise OpenPoseInputError(CODE_MALFORMED, "The OpenPose image is not a readable image.") from exc
    except (OSError, ValueError, SyntaxError, EOFError, MemoryError) as exc:
        raise OpenPoseInputError(CODE_MALFORMED, "The OpenPose image is corrupt or truncated.") from exc
    return int(width), int(height), fmt


def read_bounded_file(path: Path) -> bytes:
    """The exact bytes of one file, refusing anything over ``MAX_FILE_BYTES`` before reading it all."""

    try:
        with path.open("rb") as stream:
            declared = os.fstat(stream.fileno()).st_size
            if declared > MAX_FILE_BYTES:
                raise OpenPoseInputError(
                    CODE_OVERSIZED, f"The OpenPose image is larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB."
                )
            data = stream.read(MAX_FILE_BYTES + 1)
    except OpenPoseInputError:
        raise
    except FileNotFoundError as exc:
        raise OpenPoseInputError(CODE_MISSING, "The OpenPose image file is missing.") from exc
    except OSError as exc:
        raise OpenPoseInputError(CODE_UNREADABLE, "The OpenPose image file cannot be read.") from exc
    if len(data) > MAX_FILE_BYTES:
        raise OpenPoseInputError(
            CODE_OVERSIZED, f"The OpenPose image is larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB."
        )
    return data


def read_library_image(root: Path | str | None, identity: str) -> tuple[Path, ValidatedImage]:
    """Resolve, read once and validate one library image (the compile-time and picker-preview entry point)."""

    resolved = resolve_library_file(root, identity)
    data = read_bounded_file(resolved)
    width, height, fmt = validate_image_bytes(data)
    return resolved, ValidatedImage(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        width=width,
        height=height,
        image_format=fmt,
    )


def thumbnail_png(data: bytes, max_side: int = 160) -> bytes:
    """A small PNG preview of validated image bytes (worker-side; the GUI only wraps these bytes in a PhotoImage)."""

    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        preview = image.convert("RGBA") if image.mode in {"P", "LA", "RGBA"} else image.convert("RGB")
    preview.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    preview.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = [
    "CODE_CHANGED",
    "CODE_DIMENSIONS",
    "CODE_ESCAPE",
    "CODE_MALFORMED",
    "CODE_MISSING",
    "CODE_NO_LIBRARY",
    "CODE_OVERSIZED",
    "CODE_UNREADABLE",
    "CODE_UNSUPPORTED",
    "LIBRARY_SUBDIRS",
    "MAX_FILE_BYTES",
    "MAX_PIXELS",
    "MAX_SIDE",
    "MIN_SIDE",
    "OpenPoseInputError",
    "ValidatedImage",
    "library_root",
    "read_bounded_file",
    "read_library_image",
    "resolve_library_file",
    "thumbnail_png",
    "validate_image_bytes",
]
