"""Toolkit-neutral outpainting canvas preparation and original-pixel preservation.

Pure Pillow and bytes: no files, Tk, queue or backend. ``prepare_outpaint_canvas`` derives the expanded source, the
generation mask and a versioned record from one original image and four nonnegative extensions. ``verify_derivation``
re-derives all three from the original and compares *pixels*, so a forged record or a substituted snapshot cannot pass.
``preserve_original`` is the finalization step: it pastes the canonical decoded original back into the backend result so
the protected region is pixel-identical whatever the backend returned. Rules:

* expanded size = (W + left + right, H + top + bottom); the original sits at (left, top), unscaled and uncropped;
* the empty area is filled by replicating the nearest boundary pixel (``edge_replicate.v1``), corners included;
* the mask is binary: black over the original, white over every new pixel. Feathering is the backend's ``mask_blur`` and
  never changes the protected original, which is restored exactly after generation;
* both expanded sides must be multiples of 8 (the backend latent grid); geometry is refused, never silently adjusted.
  ``aligned_extents`` is the one documented rule an operator can inspect and apply: grow right/bottom to the next multiple.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

OUTPAINT_SCHEMA = "stablenew.image_edit.outpaint.v1"
OPERATION = "outpaint"
PADDING_POLICY = "edge_replicate.v1"
MASK_POLICY = "new_region_white_original_black.v1"
COLOR_NORMALIZATION = "exif_transpose_rgb_flatten_white.v1"
RESULT_NORMALIZATION = "rgb_convert.v1"
PRESERVATION_POLICY = "original_pixels_pasted.v1"
ALIGNMENT = 8
MIN_SIDE = 64
MAX_SIDE = 4096
_SIDES = ("left", "right", "top", "bottom")
_MODES = frozenset({"1", "L", "LA", "P", "PA", "RGB", "RGBA"})


@dataclass(frozen=True, slots=True)
class Extents:
    left: int = 0
    right: int = 0
    top: int = 0
    bottom: int = 0

    def validate(self) -> None:
        for side in _SIDES:
            value = getattr(self, side)
            if type(value) is not int:
                raise ValueError(f"The {side} extension must be a whole number of pixels")
            if value < 0:
                raise ValueError(f"The {side} extension cannot be negative")
        if not any(getattr(self, side) for side in _SIDES):
            raise ValueError("Extend at least one side of the canvas")

    def as_dict(self) -> dict[str, int]:
        return {side: getattr(self, side) for side in _SIDES}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Extents:
        raw = record.get("extents")
        if not isinstance(raw, Mapping) or set(raw) != set(_SIDES):
            raise ValueError("The outpaint record has no valid extents")
        extents = cls(**{side: raw[side] for side in _SIDES})
        extents.validate()
        return extents


@dataclass(frozen=True, slots=True)
class Pressure:
    status: str
    effective_load: float
    megapixels: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanvasGeometry:
    original_size: tuple[int, int]
    expanded_size: tuple[int, int]
    original_origin: tuple[int, int]
    pressure: Pressure | None = None

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        left, top = self.original_origin
        return left, top, left + self.original_size[0], top + self.original_size[1]


@dataclass(frozen=True, slots=True)
class OutpaintCanvas:
    expanded_png: bytes
    mask_png: bytes
    geometry: CanvasGeometry
    record: dict[str, Any] = field(default_factory=dict)


def assess_pressure(width: int, height: int, steps: int | None = None) -> Pressure:
    """The executor's stage-pressure bands for a plain img2img stage, without live GPU state.

    Mirrors ``Pipeline._assess_stage_pressure`` (``high_pressure`` from 7.0, ``unsafe`` from 10.0 effective load); a
    parity test keeps them identical.
    """

    megapixels = max(int(width), 1) * max(int(height), 1) / 1_000_000.0
    load = megapixels * (1.0 + max(int(steps or 0) - 20, 0) / 80.0)
    status, reasons = "normal", []
    if load >= 7.0:
        status = "high_pressure"
        reasons.append("stage geometry is large for SDXL-class processing")
    if load >= 10.0:
        status = "unsafe"
        reasons.append("stage geometry is in a known timeout/OOM risk band")
    return Pressure(status, round(load, 3), round(megapixels, 3), tuple(reasons))


def aligned_extents(original_size: tuple[int, int], extents: Extents) -> Extents:
    """The documented alignment rule: grow the right and bottom extensions to the next multiple of 8."""

    width = original_size[0] + extents.left + extents.right
    height = original_size[1] + extents.top + extents.bottom
    return Extents(
        extents.left,
        extents.right + (-width) % ALIGNMENT,
        extents.top,
        extents.bottom + (-height) % ALIGNMENT,
    )


def plan_geometry(
    original_size: tuple[int, int], extents: Extents, *, steps: int | None = None
) -> CanvasGeometry:
    extents.validate()
    width, height = original_size
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise ValueError(
            f"The original is {width} × {height}; supported sizes are {MIN_SIDE}–{MAX_SIDE} pixels per side"
        )
    expanded = (width + extents.left + extents.right, height + extents.top + extents.bottom)
    if max(expanded) > MAX_SIDE:
        raise ValueError(
            f"The expanded canvas {expanded[0]} × {expanded[1]} exceeds the supported {MAX_SIDE}-pixel limit per side"
        )
    for label, value in (("width", expanded[0]), ("height", expanded[1])):
        if value % ALIGNMENT:
            raise ValueError(
                f"The expanded {label} {value} is not a multiple of {ALIGNMENT} (the backend latent grid); "
                f"adjust the extensions or use Align to {ALIGNMENT}"
            )
    pressure = None
    if steps is not None:
        pressure = assess_pressure(*expanded, steps)
        if pressure.status == "unsafe":
            raise ValueError(
                f"The expanded canvas {expanded[0]} × {expanded[1]} is too large: resource pressure is unsafe "
                f"({pressure.megapixels} MP, effective load {pressure.effective_load})"
            )
    return CanvasGeometry((width, height), expanded, (extents.left, extents.top), pressure)


def normalize_original(data: bytes) -> Image.Image:
    """The canonical decoded original: EXIF orientation applied, alpha flattened over white, RGB."""

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Outpainting supports one still image, not an animation")
                image.load()
                if image.mode not in _MODES:
                    raise ValueError(
                        f"The image color mode {image.mode} is not supported for outpainting"
                    )
                oriented = ImageOps.exif_transpose(image)
                transparent = oriented.mode in {"RGBA", "LA", "PA"} or (
                    oriented.mode == "P" and "transparency" in oriented.info
                )
                if transparent:
                    flat = Image.new("RGBA", oriented.size, (255, 255, 255, 255))
                    flat.alpha_composite(oriented.convert("RGBA"))
                    return flat.convert("RGB")
                return oriented.convert("RGB")
    except ValueError:
        raise
    except (
        OSError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("The original image cannot be decoded") from exc


def _png(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=6)
    return stream.getvalue()


def _expand(original: Image.Image, extents: Extents, geometry: CanvasGeometry) -> Image.Image:
    width, height = original.size
    left, top = extents.left, extents.top
    expanded = Image.new("RGB", geometry.expanded_size)
    expanded.paste(original, (left, top))
    if left:
        expanded.paste(
            original.crop((0, 0, 1, height)).resize((left, height), Image.Resampling.NEAREST),
            (0, top),
        )
    if extents.right:
        expanded.paste(
            original.crop((width - 1, 0, width, height)).resize(
                (extents.right, height), Image.Resampling.NEAREST
            ),
            (left + width, top),
        )
    full = expanded.width
    if top:  # full-width rows, so the corners replicate the nearest corner pixel
        expanded.paste(
            expanded.crop((0, top, full, top + 1)).resize((full, top), Image.Resampling.NEAREST),
            (0, 0),
        )
    if extents.bottom:
        expanded.paste(
            expanded.crop((0, top + height - 1, full, top + height)).resize(
                (full, extents.bottom), Image.Resampling.NEAREST
            ),
            (0, top + height),
        )
    return expanded


def _record(original_bytes: bytes, extents: Extents, geometry: CanvasGeometry) -> dict[str, Any]:
    left, top, right, bottom = geometry.bbox
    return {
        "schema": OUTPAINT_SCHEMA,
        "operation": OPERATION,
        "extents": extents.as_dict(),
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "original_size": {"width": geometry.original_size[0], "height": geometry.original_size[1]},
        "expanded_size": {"width": geometry.expanded_size[0], "height": geometry.expanded_size[1]},
        "original_bbox": {"left": left, "top": top, "right": right, "bottom": bottom},
        "alignment": ALIGNMENT,
        "padding_policy": PADDING_POLICY,
        "mask_policy": MASK_POLICY,
        "color_normalization": COLOR_NORMALIZATION,
        "preservation": {"policy": PRESERVATION_POLICY, "applied_at": "artifact_finalization"},
    }


def prepare_outpaint_canvas(
    original_bytes: bytes, extents: Extents, *, steps: int | None = None
) -> OutpaintCanvas:
    original = normalize_original(original_bytes)
    geometry = plan_geometry(original.size, extents, steps=steps)
    mask = Image.new("L", geometry.expanded_size, 255)
    mask.paste(0, geometry.bbox)
    return OutpaintCanvas(
        _png(_expand(original, extents, geometry)),
        _png(mask),
        geometry,
        _record(original_bytes, extents, geometry),
    )


def plain_record(value: Any) -> Any:
    """Detach a frozen NJR mapping (or any JSON-like value) into plain dicts and lists for comparison."""

    if isinstance(value, Mapping):
        return {key: plain_record(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_record(item) for item in value]
    return value


def _pixels(data: bytes) -> tuple[str, tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.mode, image.size, image.tobytes()


def verify_derivation(
    record: Mapping[str, Any], original_bytes: bytes, expanded_bytes: bytes, mask_bytes: bytes
) -> None:
    """Re-derive the canvas from the original and refuse any record or snapshot that does not match, pixel for pixel."""

    record = plain_record(record)
    derived = prepare_outpaint_canvas(original_bytes, Extents.from_record(record))
    if record != derived.record:
        raise ValueError(
            "The outpaint record does not match the geometry derived from its original and extents"
        )
    if _pixels(expanded_bytes) != _pixels(derived.expanded_png):
        raise ValueError(
            "The frozen expanded image does not match the original and extents; preview again"
        )
    if _pixels(mask_bytes) != _pixels(derived.mask_png):
        raise ValueError(
            "The frozen outpaint mask does not match the original and extents; preview again"
        )


def preserve_original(
    result: bytes | str, original_bytes: bytes, record: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    """Finalize one backend result: validate it, restore the protected original, return PNG bytes and evidence."""

    record = plain_record(record)
    if isinstance(result, str):
        text = result.split(",", 1)[1] if "," in result else result
        try:
            result = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("The backend result is not valid base64 image data") from exc
    if hashlib.sha256(original_bytes).hexdigest() != record.get("original_sha256"):
        raise ValueError("The original image identity does not match the frozen outpaint record")
    original = normalize_original(original_bytes)
    geometry = plan_geometry(original.size, Extents.from_record(record))
    left, top, right, bottom = geometry.bbox
    if record.get("original_bbox") != {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    } or record.get("expanded_size") != {
        "width": geometry.expanded_size[0],
        "height": geometry.expanded_size[1],
    }:
        raise ValueError("The outpaint record is inconsistent with its extents")
    try:
        with Image.open(io.BytesIO(result)) as decoded:
            if getattr(decoded, "n_frames", 1) != 1:
                raise ValueError("The backend result is an animation, not a single still image")
            decoded.load()
            if decoded.mode not in _MODES:
                raise ValueError(f"The backend result color mode {decoded.mode} is not supported")
            generated = decoded.convert("RGB")
    except ValueError:
        raise
    except (OSError, SyntaxError) as exc:
        raise ValueError("The backend result cannot be decoded as an image") from exc
    if generated.size != geometry.expanded_size:
        raise ValueError(
            f"The backend result size {generated.size[0]} × {generated.size[1]} differs from the approved "
            f"expanded size {geometry.expanded_size[0]} × {geometry.expanded_size[1]}"
        )
    generated.paste(original, (left, top))
    if generated.crop(geometry.bbox).tobytes() != original.tobytes():
        raise ValueError("The protected original region could not be restored exactly")
    evidence = {
        "schema": OUTPAINT_SCHEMA,
        "operation": OPERATION,
        "preservation_applied": True,
        "policy": PRESERVATION_POLICY,
        "result_normalization": RESULT_NORMALIZATION,
        "original_sha256": record["original_sha256"],
        "protected_region_sha256": hashlib.sha256(original.tobytes()).hexdigest(),
        "original_bbox": dict(record["original_bbox"]),
        "extents": dict(record["extents"]),
        "original_size": dict(record["original_size"]),
        "result_size": {"width": generated.width, "height": generated.height},
    }
    return _png(generated), evidence
