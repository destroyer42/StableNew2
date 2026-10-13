"""Classify pinned Forge generated images before any artifact write (PR-IMG-CNET-211)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import warnings
from collections.abc import Mapping
from typing import Any, NoReturn

from src.conditioning.openpose import ConditioningError

MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_RESULT_PIXELS = 64 * 1024 * 1024


class OpenPoseResponseError(ConditioningError):
    def __init__(self, code: str, reason: str, *, expected: int, received: int) -> None:
        self.code = code
        self.diagnostics = {
            "code": code,
            "expected_generations": expected,
            "received_images": received,
        }
        super().__init__(
            f"OpenPose output refused ({code}): {reason}; expected {expected} generation(s), received {received} "
            "image(s). No response images were saved. Inspect Forge's response metadata; do not replay automatically."
        )


def _pixels(data: bytes) -> tuple[tuple[int, int], str]:
    """A decoded pixel identity, independent of PNG metadata/encoding, using Forge HWC3 alpha semantics."""

    import numpy as np
    from PIL import Image

    if len(data) > MAX_RESULT_BYTES:
        raise ValueError("image byte limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_RESULT_PIXELS:
                raise ValueError("image pixel limit")
            image.load()
            size = image.size
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = np.asarray(image.convert("RGBA"))
                alpha = rgba[:, :, 3:4].astype(np.float32) / 255.0
                rgb = (rgba[:, :, :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)).astype(
                    np.uint8
                )
                pixels = rgb.tobytes()
            else:
                pixels = image.convert("RGB").tobytes()
    return size, hashlib.sha256(pixels).hexdigest()


def _decode(value: Any) -> bytes:
    if not isinstance(value, str) or not value or len(value) > (MAX_RESULT_BYTES * 4 // 3 + 1024):
        raise ValueError("invalid image envelope")
    encoded = value.split(",", 1)[1] if value.startswith("data:image/") and "," in value else value
    return base64.b64decode(encoded, validate=True)


def classify_openpose_response(
    response: Any, *, expected: int, input_bytes: bytes
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use Forge Processed metadata, decoded input identity and exact counts; never guess by truncation.

    Pinned Forge returns ``processed.images + processed.extra_images``. Metadata ``index_of_first_image`` identifies
    the optional leading grid, ``infotexts`` covers only grid/generations, and ``all_seeds`` covers generations. Only
    trailing images pixel-identical to the supplied map are recognized extras. Unknown extras or a map occupying a
    generation slot refuse the entire response. This cannot prove semantic image quality or detect a transformed map.
    """

    images = response.get("images") if isinstance(response, Mapping) else None
    received = len(images) if isinstance(images, list) else 0

    from PIL import Image

    def refuse(code: str, reason: str) -> NoReturn:
        raise OpenPoseResponseError(code, reason, expected=expected, received=received)

    if expected < 1 or not isinstance(images, list) or not images:
        refuse("missing_generations", "no complete generated-image list")
    info = response.get("info")
    if isinstance(info, str) and len(info) <= MAX_RESULT_BYTES:
        try:
            info = json.loads(info)
        except (ValueError, RecursionError):
            info = None
    if not isinstance(info, Mapping):
        refuse("ambiguous_metadata", "generation metadata is absent or unreadable")
    first = info.get("index_of_first_image")
    seeds = info.get("all_seeds")
    texts = info.get("infotexts")
    if type(first) is not int or first not in (0, 1):
        refuse("ambiguous_metadata", "missing or unsupported generated-image boundary")
    if (
        not isinstance(seeds, list)
        or len(seeds) != expected
        or any(type(seed) is not int for seed in seeds)
    ):
        refuse("generation_count", "seed count does not substantiate every requested generation")
    if (
        not isinstance(texts, list)
        or len(texts) != first + expected
        or any(not isinstance(text, str) or not text.strip() for text in texts)
    ):
        refuse(
            "generation_count", "infotext count does not substantiate every requested generation"
        )
    end = first + expected
    if received < end:
        refuse("missing_generations", "fewer images than the metadata claims")
    # One unit, optionally one low-res and one high-res detect map. More extras cannot be this supported contract.
    if received > end + 2:
        refuse("unexpected_images", "too many extra images for the single supported unit")
    try:
        reference = _pixels(input_bytes)
        identities = [_pixels(_decode(value)) for value in images]
    except (
        ValueError,
        OSError,
        SyntaxError,
        MemoryError,
        binascii.Error,
        Warning,
        Image.DecompressionBombError,
    ) as exc:
        refuse("invalid_image", f"an image could not be decoded safely ({type(exc).__name__})")
    if any(identity == reference for identity in identities[first:end]):
        refuse(
            "pose_in_generation_slot", "a declared generation is identical to the supplied pose map"
        )
    if any(identity != reference for identity in identities[end:]):
        refuse("unexpected_images", "trailing images cannot be identified as the supplied pose map")
    classified = dict(response)
    classified["images"] = list(images[first:end])
    classified_info = dict(info)
    classified_info["index_of_first_image"] = 0
    classified_info["infotexts"] = list(texts[first:end])
    classified["info"] = classified_info
    return classified, {
        "classification": "metadata_and_input_identity",
        "expected_generations": expected,
        "received_images": received,
        "generated_images": expected,
        "grids_discarded": first,
        "control_images_discarded": received - end,
    }
