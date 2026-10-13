"""Classify pinned Forge generated images before any artifact write (PR-IMG-CNET-211)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import struct
import warnings
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, NoReturn

from src.conditioning.openpose import ConditioningError

MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_RESULT_PIXELS = 64 * 1024 * 1024
_HASH_CHUNK_PIXELS = 65536


@lru_cache(maxsize=1)
def _forge_alpha_tables() -> tuple[bytes, ...]:
    """64 KiB table reproducing Forge's float32 multiply/add and uint8 truncation, without NumPy.

    Pillow's alpha_composite rounds rather than truncates. Even integer floor differs at float32 boundaries, so round
    each arithmetic operation to IEEE binary32, as pinned HWC3 does. Every channel/alpha byte pair is regression-tested.
    """

    binary32 = struct.Struct("<f")

    def f32(value: float) -> float:
        return binary32.unpack(binary32.pack(value))[0]

    tables = []
    for alpha_byte in range(256):
        alpha = f32(alpha_byte / 255.0)
        white = f32(255.0 * f32(1.0 - alpha))
        tables.append(
            bytes(
                int(min(255.0, max(0.0, f32(f32(channel * alpha) + white))))
                for channel in range(256)
            )
        )
    return tuple(tables)


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
            digest = hashlib.sha256()
            # Hash bounded row-major chunks; do not allocate full RGBA/float arrays. Wide images use row segments.
            rows = max(1, _HASH_CHUNK_PIXELS // image.width)
            for top in range(0, image.height, rows):
                for left in range(0, image.width, _HASH_CHUNK_PIXELS):
                    block = image.crop(
                        (
                            left,
                            top,
                            min(image.width, left + _HASH_CHUNK_PIXELS),
                            min(image.height, top + rows),
                        )
                    )
                    if "A" not in block.getbands() and "transparency" not in block.info:
                        digest.update(block.convert("RGB").tobytes())
                        continue
                    rgba = block.convert("RGBA").tobytes()
                    rgb = bytearray(len(rgba) // 4 * 3)
                    tables = _forge_alpha_tables()
                    for offset in range(0, len(rgba), 4):
                        table = tables[rgba[offset + 3]]
                        target = offset // 4 * 3
                        rgb[target] = table[rgba[offset]]
                        rgb[target + 1] = table[rgba[offset + 1]]
                        rgb[target + 2] = table[rgba[offset + 2]]
                    digest.update(rgb)
    return size, digest.hexdigest()


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
