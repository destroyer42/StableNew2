"""Localized-only ADetailer refinement (PR-IMG-ADETAILER-LOCAL-240B): execution mode, mask evidence and preservation.

The legacy ADetailer stage sends a whole-image img2img request and lets the pinned ADetailer-Neo run as an always-on
script behind it, so the whole image is re-sampled before any face or hand is touched and nothing says which pixels the
extension was entitled to change. ``localized_only`` replaces that for newly compiled jobs: the StableNew companion
extension in the managed Forge runtime runs the pinned extension's own detection, mask filtering, mask preprocessing and
masked inpainting with no outer generation, and returns the masks it used. This module is the StableNew side of that
contract and is pure and offline:

* the execution mode a frozen stage configuration asks for (an absent key is a job compiled before this mode existed
  and keeps ``legacy_whole_image``; nothing migrates it);
* what ``localized_only`` refuses before any dispatch;
* validation of the returned mask evidence against the image StableNew sent; and
* the composite that is published: backend pixels inside the authorized region, original pixels everywhere else, with
  the equality outside that region proven on the result rather than assumed from Forge's inpainting overlay.

The authorized region is each effective mask (any non-zero pixel) grown by the pass's *blend margin*: Forge blurs an
inpainting mask with a Gaussian kernel of half-width ``int(2.5 * mask_blur + 0.5)`` pixels before it composites, so that
is how far a correction may legitimately reach beyond the mask. The margin is a square (Chebyshev) growth, which
contains that kernel exactly.

Every failure raises ``LocalizedRefinementError``; the caller publishes nothing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageFilter

SCHEMA = "stablenew.adetailer-localized.v1"
EXECUTION_MODE_KEY = "adetailer_execution_mode"
LOCALIZED_ONLY = "localized_only"
LEGACY_WHOLE_IMAGE = "legacy_whole_image"
EXECUTION_MODES: tuple[str, ...] = (LOCALIZED_ONLY, LEGACY_WHOLE_IMAGE)

#: The companion extension's route in the managed Forge runtime, and the generation stage key StableNew dispatches it as.
ENDPOINT = "/stablenew/v1/adetailer/localized"
STAGE_KEY = "adetailer_localized"
COMPANION_EXTENSION = "stablenew-adetailer-local"

#: Upper bound on effective masks in one response (two passes; the hand pass keeps at most a handful per person).
MAX_MASKS = 64
_INVERTING_MERGE_MODE = "Merge and Invert"


class LocalizedRefinementError(ValueError):
    """Localized-only refinement was refused, or its evidence could not be verified. Nothing may be published."""


def execution_mode(config: Mapping[str, Any] | None) -> str:
    """The execution mode of one frozen ADetailer stage configuration.

    An absent (or ``None``) key is a configuration compiled before the mode existed: it keeps the whole-image behavior
    it was recorded with. Any other unknown value is refused rather than guessed.
    """

    value = (config or {}).get(EXECUTION_MODE_KEY)
    if value is None:
        return LEGACY_WHOLE_IMAGE
    if value in EXECUTION_MODES:
        return str(value)
    raise LocalizedRefinementError(
        f"unknown {EXECUTION_MODE_KEY} {value!r}; expected one of {list(EXECUTION_MODES)}"
    )


def stamp_fresh_execution_mode(section: Mapping[str, Any]) -> dict[str, Any]:
    """A newly compiled ADetailer section: ``localized_only`` unless the section already states a mode."""

    stamped = dict(section)
    if stamped.get(EXECUTION_MODE_KEY) is None:
        stamped[EXECUTION_MODE_KEY] = LOCALIZED_ONLY
    return stamped


def localized_refusals(passes: Sequence[tuple[str, Mapping[str, Any]]]) -> tuple[str, ...]:
    """Reasons ``localized_only`` refuses these requested passes before any dispatch."""

    return tuple(
        f"{label} pass uses mask mode {_INVERTING_MERGE_MODE!r}, which targets everything except the detected "
        "regions; localized-only refinement never edits the background"
        for label, args in passes
        if args.get("ad_mask_merge_invert") == _INVERTING_MERGE_MODE
    )


def stage_refusals(section: Mapping[str, Any]) -> tuple[str, ...]:
    """``localized_refusals`` for a stored ADetailer stage section (its own key names), for the compile boundary."""

    passes: list[tuple[str, Mapping[str, Any]]] = []
    if section.get("enable_face_pass", True):
        mode = section.get("ad_mask_merge_invert", section.get("mask_merge_mode"))
        passes.append(("face", {"ad_mask_merge_invert": mode}))
    if section.get("enable_hands_pass", section.get("ad_hands_enabled", False)):
        passes.append(
            ("hands", {"ad_mask_merge_invert": section.get("ad_hands_mask_merge_invert")})
        )
    return localized_refusals(passes)


def blend_margin(mask_blur: Any) -> int:
    """Pixels a correction may reach beyond its mask: the half-width of Forge's mask-blur kernel."""

    try:
        blur = float(mask_blur)
    except (TypeError, ValueError) as exc:
        raise LocalizedRefinementError(f"mask blur {mask_blur!r} is not a number") from exc
    if blur < 0:
        raise LocalizedRefinementError(f"mask blur {mask_blur!r} is negative")
    return int(2.5 * blur + 0.5)


def pixel_sha256(image: Image.Image) -> str:
    """Identity of an image's RGB pixels and size, independent of file encoding and metadata."""

    rgb = image.convert("RGB")
    digest = hashlib.sha256(f"RGB:{rgb.width}x{rgb.height}:".encode("ascii"))
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def encode_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _decode_image(value: Any, what: str) -> Image.Image:
    if not isinstance(value, str) or not value:
        raise LocalizedRefinementError(f"{what} is missing")
    try:
        raw = base64.b64decode(value.split(",", 1)[-1], validate=True)
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (binascii.Error, ValueError, OSError) as exc:
        raise LocalizedRefinementError(f"{what} is not a decodable image: {exc}") from exc
    return image


def build_request(
    *,
    original: Image.Image,
    passes: Sequence[tuple[str, Mapping[str, Any]]],
    generation: Mapping[str, Any],
) -> dict[str, Any]:
    """The companion request for one image. ``generation`` carries the stage's own prompt, sampler and pinning fields."""

    rgb = original.convert("RGB")
    return {
        **dict(generation),
        "schema": SCHEMA,
        "image": encode_png(rgb),
        "source": {"width": rgb.width, "height": rgb.height, "sha256": pixel_sha256(rgb)},
        "width": rgb.width,
        "height": rgb.height,
        "passes": [{"label": label, "args": dict(args)} for label, args in passes],
    }


def _nonzero(mask: Image.Image) -> Image.Image:
    return mask.point(lambda value: 255 if value else 0)


def _count(mask: Image.Image) -> int:
    return int(mask.histogram()[255])


def _grow(mask: Image.Image, margin: int) -> Image.Image:
    # ``margin`` passes of a 3x3 maximum are one (2 * margin + 1) square dilation, without a large rank filter.
    for _ in range(margin):
        mask = mask.filter(ImageFilter.MaxFilter(3))
    return mask


def _difference(first: Image.Image, second: Image.Image) -> Image.Image:
    """255 where any RGB channel differs, else 0 (a luminance conversion would round a one-level change away)."""

    red, green, blue = ImageChops.difference(first, second).split()
    return _nonzero(ImageChops.lighter(ImageChops.lighter(red, green), blue))


@dataclass(frozen=True, slots=True)
class LocalizedOutcome:
    """A verified result. ``image`` is ``None`` when the original passes through unchanged (nothing was sampled)."""

    image: Image.Image | None
    authorized: Image.Image
    record: dict[str, Any]


def verify_and_composite(
    *,
    original: Image.Image,
    response: Any,
    passes: Sequence[tuple[str, Mapping[str, Any]]],
) -> LocalizedOutcome:
    """Validate the companion's mask evidence against ``original`` and build the image that may be published."""

    if not isinstance(response, Mapping):
        raise LocalizedRefinementError("the backend returned no localized-refinement evidence")
    if response.get("schema") != SCHEMA:
        raise LocalizedRefinementError(
            f"evidence schema {response.get('schema')!r} is not {SCHEMA!r}"
        )
    companion_version = response.get("companion_version")
    if not isinstance(companion_version, str) or not companion_version:
        raise LocalizedRefinementError("evidence does not identify the companion extension version")

    source = original.convert("RGB")
    reported = response.get("source")
    if not isinstance(reported, Mapping):
        raise LocalizedRefinementError("evidence does not identify the image the backend processed")
    if (reported.get("width"), reported.get("height")) != source.size:
        raise LocalizedRefinementError(
            f"the backend processed a {reported.get('width')}x{reported.get('height')} image, "
            f"not the {source.width}x{source.height} source"
        )
    source_sha = pixel_sha256(source)
    if reported.get("sha256") != source_sha:
        raise LocalizedRefinementError(
            "the backend processed different pixels than the source image"
        )

    reported_passes = response.get("passes")
    if not isinstance(reported_passes, list) or len(reported_passes) != len(passes):
        raise LocalizedRefinementError("evidence does not cover exactly the requested passes")
    sampled = response.get("sampled")
    if not isinstance(sampled, bool):
        raise LocalizedRefinementError("evidence does not state whether refinement sampling ran")

    authorized = Image.new("L", source.size, 0)
    pass_records: list[dict[str, Any]] = []
    total_masks = 0
    for (label, args), entry in zip(passes, reported_passes, strict=True):
        if not isinstance(entry, Mapping) or entry.get("label") != label:
            raise LocalizedRefinementError(
                f"evidence for the {label} pass is missing or out of order"
            )
        if entry.get("model") != args.get("ad_model"):
            raise LocalizedRefinementError(
                f"the {label} pass ran detector {entry.get('model')!r}, not {args.get('ad_model')!r}"
            )
        masks = entry.get("masks")
        if not isinstance(masks, list) or entry.get("mask_count") != len(masks):
            raise LocalizedRefinementError(f"the {label} pass mask count does not match its masks")
        sampled_masks = entry.get("sampled_masks")
        if sampled_masks is not None and (
            type(sampled_masks) is not int
            or not 0 <= sampled_masks <= len(masks)
            or (sampled_masks > 0 and not sampled)
        ):
            raise LocalizedRefinementError(f"the {label} pass sampled-mask count is invalid")
        total_masks += len(masks)
        if total_masks > MAX_MASKS:
            raise LocalizedRefinementError(f"more than {MAX_MASKS} effective masks were returned")
        margin = blend_margin(args.get("ad_mask_blur", 0))
        regions: list[dict[str, Any]] = []
        for index, encoded in enumerate(masks):
            what = f"{label} mask {index + 1}"
            mask = _decode_image(encoded, what)
            if mask.mode not in ("L", "1"):
                raise LocalizedRefinementError(f"{what} is {mask.mode}, not a single-channel mask")
            if mask.size != source.size:
                raise LocalizedRefinementError(
                    f"{what} is {mask.width}x{mask.height}, not the source {source.width}x{source.height}"
                )
            region = _nonzero(mask.convert("L"))
            pixels = _count(region)
            if pixels == 0:
                raise LocalizedRefinementError(f"{what} is empty")
            authorized = ImageChops.lighter(authorized, _grow(region, margin))
            regions.append({"pixels": pixels, "bbox": list(region.getbbox() or ())})
        pass_records.append(
            {
                "label": label,
                "detector": args.get("ad_model"),
                "effective_mask_count": len(masks),
                "sampled_masks": sampled_masks,
                "mask_blur": args.get("ad_mask_blur", 0),
                "blend_margin_px": margin,
                "masks": regions,
            }
        )

    if sampled and all(entry["sampled_masks"] == 0 for entry in pass_records):
        raise LocalizedRefinementError("evidence reports sampling but no pass sampled a mask")

    authorized_pixels = _count(authorized)
    total_pixels = source.width * source.height
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "execution_mode": LOCALIZED_ONLY,
        "backend": {
            "companion_extension": COMPANION_EXTENSION,
            "companion_version": companion_version,
            "adetailer_version": response.get("adetailer_version"),
        },
        "source": {"width": source.width, "height": source.height, "pixel_sha256": source_sha},
        "passes": pass_records,
        "effective_mask_count": total_masks,
        "authorized_region": {
            "definition": "non-zero mask pixels grown by each pass's blend margin (square)",
            "pixels": authorized_pixels,
            "fraction": authorized_pixels / total_pixels,
        },
        "refinement_sampled": sampled,
        "zero_mask_passthrough": total_masks == 0,
    }

    if not sampled:
        if response.get("image") is not None:
            raise LocalizedRefinementError(
                "the backend returned an image although it reports no sampling"
            )
        record["pixel_change"] = {"changed_pixels": 0, "output_identical_to_source": True}
        record["preservation"] = {
            "verified": True,
            "method": "passthrough: no refinement sampling ran, the source image is the result",
            "backend_changed_pixels_outside_authorized": 0,
        }
        return LocalizedOutcome(image=None, authorized=authorized, record=record)

    if total_masks == 0:
        raise LocalizedRefinementError(
            "the backend reports refinement sampling without any effective mask"
        )
    generated = _decode_image(response.get("image"), "the refined image").convert("RGB")
    if generated.size != source.size:
        raise LocalizedRefinementError(
            f"the refined image is {generated.width}x{generated.height}, "
            f"not the source {source.width}x{source.height}"
        )
    backend_change = _difference(generated, source)
    outside = ImageChops.invert(authorized)
    final = Image.composite(generated, source, authorized)
    final_change = _difference(final, source)
    leaked = _count(ImageChops.multiply(final_change, outside))
    if leaked:
        raise LocalizedRefinementError(
            f"{leaked} pixel(s) outside the authorized region differ from the source after compositing"
        )
    record["pixel_change"] = {
        "changed_pixels": _count(final_change),
        "output_identical_to_source": _count(final_change) == 0,
    }
    record["preservation"] = {
        "verified": True,
        "method": "composited against the source; every pixel outside the authorized region compared exactly",
        "backend_changed_pixels_outside_authorized": _count(
            ImageChops.multiply(backend_change, outside)
        ),
    }
    record["output_pixel_sha256"] = pixel_sha256(final)
    return LocalizedOutcome(image=final, authorized=authorized, record=record)


def verify_published(
    *, original: Image.Image, published: Image.Image, outcome: LocalizedOutcome
) -> None:
    """Prove the file that was written still equals the source outside the authorized region (and is the composite)."""

    if outcome.image is None:
        raise LocalizedRefinementError("a passthrough result has no published refinement to verify")
    final = published.convert("RGB")
    if (
        final.size != outcome.image.size
        or pixel_sha256(final) != outcome.record["output_pixel_sha256"]
    ):
        raise LocalizedRefinementError("the written image is not the verified composite")
    leaked = _count(
        ImageChops.multiply(
            _difference(final, original.convert("RGB")), ImageChops.invert(outcome.authorized)
        )
    )
    if leaked:
        raise LocalizedRefinementError(
            f"{leaked} pixel(s) outside the authorized region differ in the written image"
        )


__all__ = [
    "COMPANION_EXTENSION",
    "ENDPOINT",
    "EXECUTION_MODES",
    "EXECUTION_MODE_KEY",
    "LEGACY_WHOLE_IMAGE",
    "LOCALIZED_ONLY",
    "MAX_MASKS",
    "SCHEMA",
    "STAGE_KEY",
    "LocalizedOutcome",
    "LocalizedRefinementError",
    "blend_margin",
    "build_request",
    "encode_png",
    "execution_mode",
    "localized_refusals",
    "pixel_sha256",
    "stage_refusals",
    "stamp_fresh_execution_mode",
    "verify_and_composite",
    "verify_published",
]
