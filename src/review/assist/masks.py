"""Deterministic mask normalization and validation; pure image logic, no model, file or Tk (PR-IMG-REVIEW-320).

Polarity is the existing frozen-edit contract (``freeze_inputs``/``verified_inputs``): an 8-bit grayscale PNG in which
white (255) is CHANGE and black (0) is PRESERVE. A model logit strictly above ``LOGIT_THRESHOLD`` becomes white; the
low-resolution binary mask is resized to the source with nearest-neighbour sampling, so no gray value is ever created, and
nothing is inverted. A mask that is empty, selects nearly everything, has the wrong size, a non-binary value, an alpha channel or
non-finite source logits is refused with a stable code and no job is created.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from src.review.assist.contracts import (
    CODE_OUTPUT,
    LOGIT_THRESHOLD,
    MASK_EDIT,
    MASK_PRESERVE,
    MAX_LOGIT_SIDE,
    MAX_MASK_BYTES,
    MAX_MASK_COVERAGE,
    AssistError,
    SourceIdentity,
)


@dataclass(frozen=True, slots=True)
class MaskFacts:
    sha256: str
    selected_pixels: int
    coverage: float


def _refuse(message: str) -> AssistError:
    return AssistError(CODE_OUTPUT, message)


def _binary_array(data: bytes, identity: SourceIdentity) -> np.ndarray:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise _refuse("The suggested mask is empty or unreadable.")
    if len(data) > MAX_MASK_BYTES:
        raise _refuse("The suggested mask is larger than the allowed size.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.mode != "L":
                raise _refuse("The suggested mask must be an 8-bit grayscale PNG.")
            if image.size != identity.size:
                raise _refuse("The suggested mask does not match the image size.")
            image.load()
            array = np.asarray(image, dtype=np.uint8)
    except AssistError:
        raise
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError) as exc:
        raise _refuse("The suggested mask is corrupt.") from exc
    return array


def validate_mask_png(data: bytes, identity: SourceIdentity) -> MaskFacts:
    """Re-validate a mask against the exact source identity. Raises ``AssistError(invalid_output)``."""

    array = _binary_array(data, identity)
    if not np.isin(array, (MASK_PRESERVE, MASK_EDIT)).all():
        raise _refuse("The suggested mask is not strictly black and white.")
    selected = int(np.count_nonzero(array == MASK_EDIT))
    if selected == 0:
        raise _refuse("The model did not find an object at that point. Try another point or a box.")
    coverage = selected / float(array.size)
    if coverage > MAX_MASK_COVERAGE:
        raise _refuse(
            "The suggested mask covers almost the whole image. Refine the points or draw a box."
        )
    return MaskFacts(hashlib.sha256(data).hexdigest(), selected, coverage)


def logits_to_mask_png(
    logits: object, identity: SourceIdentity, *, threshold: float = LOGIT_THRESHOLD
) -> tuple[bytes, MaskFacts]:
    """Binary 8-bit PNG mask of exactly the source size from 2-D model logits."""

    try:
        array = np.asarray(logits, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise _refuse("The model returned an unusable mask.") from exc
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
        raise _refuse("The model returned a mask with an unexpected shape.")
    if array.shape[0] > MAX_LOGIT_SIDE or array.shape[1] > MAX_LOGIT_SIDE:
        raise _refuse("The model returned a mask larger than the allowed size.")
    if not np.isfinite(array).all():
        raise _refuse("The model returned invalid numbers (NaN or infinity).")
    binary = np.where(array > threshold, MASK_EDIT, MASK_PRESERVE).astype(np.uint8)
    resized = Image.fromarray(binary).resize(identity.size, Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG", optimize=False, compress_level=6)
    data = buffer.getvalue()
    return data, validate_mask_png(data, identity)


def mask_image(data: bytes, identity: SourceIdentity) -> Image.Image:
    """The validated mask as a private ``L`` image (a copy; the bytes stay untouched)."""

    validate_mask_png(data, identity)
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.copy()


__all__ = ["MaskFacts", "logits_to_mask_png", "mask_image", "validate_mask_png"]
