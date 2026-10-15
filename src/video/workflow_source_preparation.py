"""Deterministic source preparation declared by a workflow catalog entry.

The preparation happens before queue admission.  The immutable NJR therefore
references a StableNew-owned prepared image and retains enough provenance to
replay the same geometry without asking a backend to reinterpret the source.

``transform_declared_workflow_source`` is the one side-effect-free transformation (EXIF transpose,
RGB conversion, declared target selection, LANCZOS cover resize with a centred crop).  Both the
queue-time ``prepare_declared_workflow_source`` and the operator-facing
``preview_declared_workflow_source`` call it, so a preview can never disagree with the PNG that
admission later publishes, and the reported crop rectangle is the one the resize actually used.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

_COVER_CENTER_CROP = "cover_resize_center_crop"
_EXIF_ORIENTATION_TAG = 0x0112

# Input-pixel budget of the operator-facing readiness *preview* only.  Decoding, transposing and
# converting a source holds several full-size buffers at once, so an automatic preview declines an
# image whose header reports more pixels than this and never decodes it.  Queue-time preparation
# has no such budget: an oversized image is still prepared and generated normally.
PREVIEW_MAX_SOURCE_PIXELS = 64_000_000


class SourceTooLargeForPreview(ValueError):
    """The preview declined a source above its pixel budget; preparation is unaffected."""


@dataclass(frozen=True, slots=True)
class PreparedWorkflowSource:
    original_source_path: str
    prepared_image_path: str
    source_dimensions: dict[str, int]
    target_dimensions: dict[str, int]
    prepared_dimensions: dict[str, int]
    orientation: str
    policy: str
    orientation_rule: str

    def to_stage_config(self) -> dict[str, Any]:
        return {
            "original_source_path": self.original_source_path,
            "prepared_image_path": self.prepared_image_path,
            "source_dimensions": dict(self.source_dimensions),
            "target_dimensions": dict(self.target_dimensions),
            "prepared_dimensions": dict(self.prepared_dimensions),
            "orientation": self.orientation,
            "policy": self.policy,
            "orientation_rule": self.orientation_rule,
        }


@dataclass(frozen=True, slots=True)
class WorkflowSourceGeometry:
    """What the declared preparation does to one source, as plain numbers.

    ``crop_box`` is ``(left, top, right, bottom)`` in EXIF-transposed source pixels: the exact
    region the resize consumed.  ``stored_dimensions`` is the pixel grid as stored in the file;
    it differs from ``source_dimensions`` only when an EXIF orientation tag rotated the image.
    """

    stored_dimensions: dict[str, int]
    source_dimensions: dict[str, int]
    exif_orientation: int
    target_dimensions: dict[str, int]
    prepared_dimensions: dict[str, int]
    source_orientation: str  # landscape | portrait | square, from the pixels alone
    orientation: str  # the policy's orientation decision (a square follows the policy)
    orientation_rule: str
    policy: str
    crop_box: tuple[float, float, float, float]

    @property
    def crop_dimensions(self) -> tuple[float, float]:
        left, top, right, bottom = self.crop_box
        return right - left, bottom - top

    @property
    def retained_fraction(self) -> float:
        crop_width, crop_height = self.crop_dimensions
        total = self.source_dimensions["width"] * self.source_dimensions["height"]
        return min(1.0, (crop_width * crop_height) / total) if total else 0.0

    @property
    def discarded_fraction(self) -> float:
        return max(0.0, 1.0 - self.retained_fraction)

    @property
    def exif_transposed(self) -> bool:
        return self.exif_orientation not in (0, 1)


@dataclass(frozen=True, slots=True)
class TransformedWorkflowSource:
    """The prepared pixels (RGB) and the geometry that produced them; nothing is written."""

    image: Image.Image
    geometry: WorkflowSourceGeometry

    def to_png_bytes(self) -> bytes:
        """The prepared image encoded exactly as a published prepared PNG is (no metadata)."""

        buffer = io.BytesIO()
        self.image.save(buffer, format="PNG")
        return buffer.getvalue()


def cover_crop_box(
    source_size: tuple[int, int], target_size: tuple[int, int]
) -> tuple[float, float, float, float]:
    """Centred crop rectangle of a cover resize: ``ImageOps.fit(..., centering=(0.5, 0.5))``.

    The arithmetic is the one Pillow's ``ImageOps.fit`` applies (no bleed, centred), kept as the
    single definition so the pixels and the reported geometry cannot diverge; tests pin it to
    ``ImageOps.fit`` itself.  Pure: dimensions in, rectangle out."""

    source_width, source_height = float(source_size[0]), float(source_size[1])
    source_ratio = source_width / source_height
    target_ratio = target_size[0] / target_size[1]
    if source_ratio == target_ratio:
        crop_width, crop_height = source_width, source_height
    elif source_ratio >= target_ratio:
        crop_width, crop_height = target_ratio * source_height, source_height
    else:
        crop_width, crop_height = source_width, source_width / target_ratio
    left = (source_width - crop_width) * 0.5
    top = (source_height - crop_height) * 0.5
    return left, top, left + crop_width, top + crop_height


def _source_orientation(width: int, height: int) -> str:
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def transform_declared_workflow_source(
    *,
    source_path: str | Path,
    policy: Mapping[str, Any],
    max_source_pixels: int | None = None,
) -> TransformedWorkflowSource:
    """Apply the catalog-declared preparation to ``source_path`` in memory.

    Reads the source file and nothing else: no output root, no hashing, no temporary file, no
    write of any kind.  Raises ``ValueError`` with the operator-facing reason on a bad source or
    policy, exactly as ``prepare_declared_workflow_source`` always did.  ``max_source_pixels`` is
    a header-first budget for the preview only; ``None`` (what preparation passes) is unbounded,
    exactly as before."""

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Video workflow source image does not exist: {source}")
    try:
        with Image.open(source) as opened:
            stored_width, stored_height = opened.size  # header only: nothing is decoded yet
            if max_source_pixels is not None and stored_width * stored_height > max_source_pixels:
                megapixels = stored_width * stored_height / 1e6
                raise SourceTooLargeForPreview(
                    f"The source image is {stored_width}x{stored_height} ({megapixels:.0f} "
                    f"megapixels), above the {max_source_pixels / 1e6:.0f}-megapixel limit for "
                    "the readiness preview, so no preview is shown. Queueing is unaffected: the "
                    "image is prepared normally."
                )
            exif_orientation = int(opened.getexif().get(_EXIF_ORIENTATION_TAG, 1) or 1)
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except SourceTooLargeForPreview:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to open video workflow source image: {exc}") from exc
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Video workflow source image dimensions must be positive.")

    orientation, target, orientation_rule = resolve_declared_target(policy, width, height)
    crop_box = cover_crop_box((width, height), (target["width"], target["height"]))
    prepared = image.resize(
        (target["width"], target["height"]),
        Image.Resampling.LANCZOS,
        box=crop_box,
    )
    geometry = WorkflowSourceGeometry(
        stored_dimensions={"width": int(stored_width), "height": int(stored_height)},
        source_dimensions={"width": int(width), "height": int(height)},
        exif_orientation=exif_orientation,
        target_dimensions=dict(target),
        prepared_dimensions={"width": int(prepared.width), "height": int(prepared.height)},
        source_orientation=_source_orientation(width, height),
        orientation=orientation,
        orientation_rule=orientation_rule,
        policy=_COVER_CENTER_CROP,
        crop_box=crop_box,
    )
    return TransformedWorkflowSource(image=prepared, geometry=geometry)


def preview_declared_workflow_source(
    *,
    source_path: str | Path,
    policy: Mapping[str, Any],
    max_source_pixels: int | None = None,
) -> TransformedWorkflowSource:
    """The exact prepared image and geometry admission would publish, without publishing.

    Same transformation as ``prepare_declared_workflow_source``; creates no file and leaves the
    source untouched, so it is safe to call repeatedly from a worker while an operator browses.
    A source whose header reports more than ``max_source_pixels`` (default
    ``PREVIEW_MAX_SOURCE_PIXELS``) raises ``SourceTooLargeForPreview`` before any pixel is
    decoded; that is a preview-only limit and never applies to preparation."""

    budget = PREVIEW_MAX_SOURCE_PIXELS if max_source_pixels is None else max_source_pixels
    return transform_declared_workflow_source(
        source_path=source_path, policy=policy, max_source_pixels=budget
    )


def prepare_declared_workflow_source(
    *,
    source_path: str | Path,
    output_root: str | Path,
    policy: Mapping[str, Any],
) -> PreparedWorkflowSource:
    """Prepare a catalog-declared source using the bounded cover/crop policy."""

    source = Path(source_path).expanduser().resolve()
    transformed = transform_declared_workflow_source(source_path=source, policy=policy)
    prepared = transformed.image
    geometry = transformed.geometry
    width, height = geometry.source_dimensions["width"], geometry.source_dimensions["height"]
    orientation, target = geometry.orientation, geometry.target_dimensions
    orientation_rule = geometry.orientation_rule

    content_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    prepared_path = prepared_source_destination(output_root, content_digest, target)
    prepared_root = prepared_path.parent
    prepared_root.mkdir(parents=True, exist_ok=True)
    if not prepared_path.exists():
        # Each caller owns its temp, including callers in other processes. Keep it
        # beside the destination so replacement publishes a complete PNG atomically.
        with tempfile.NamedTemporaryFile(
            delete=False, dir=prepared_root, prefix=f"{prepared_path.stem}_", suffix=".tmp.png"
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        try:
            prepared.save(temporary_path, format="PNG")
            try:
                temporary_path.replace(prepared_path)
            except PermissionError:
                # Windows may deny replacement while another caller reads the
                # winner. Reuse only a byte-identical, fully published PNG.
                try:
                    same_content = prepared_path.read_bytes() == temporary_path.read_bytes()
                except OSError:
                    same_content = False
                if not same_content:
                    raise
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass  # Best effort; never mask the original preparation/publication failure.

    return PreparedWorkflowSource(
        original_source_path=str(source),
        prepared_image_path=str(prepared_path.resolve()),
        source_dimensions={"width": int(width), "height": int(height)},
        target_dimensions=dict(target),
        prepared_dimensions={"width": int(prepared.width), "height": int(prepared.height)},
        orientation=orientation,
        policy=_COVER_CENTER_CROP,
        orientation_rule=orientation_rule,
    )


def resolve_declared_target(
    policy: Mapping[str, Any], width: int, height: int
) -> tuple[str, dict[str, int], str]:
    """Orientation, target dimensions and orientation rule the policy assigns to a source size.

    Pure and read-only: the same decision ``prepare_declared_workflow_source`` applies, available
    without decoding or writing anything so a preview can report it truthfully."""

    if str(policy.get("resize_policy") or "") != _COVER_CENTER_CROP:
        raise ValueError("Workflow source preparation declares an unsupported resize policy.")
    portrait_target = _dimensions(policy.get("portrait_target"), "portrait_target")
    landscape_target = _dimensions(policy.get("landscape_target"), "landscape_target")
    square_orientation = str(policy.get("square_orientation") or "portrait").strip().lower()
    if square_orientation not in {"portrait", "landscape"}:
        raise ValueError("Workflow source preparation square_orientation must be portrait or landscape.")
    orientation = "landscape" if width > height else "portrait"
    if width == height:
        orientation = square_orientation
    target = landscape_target if orientation == "landscape" else portrait_target
    rule = (
        "landscape when source width is greater than height; otherwise portrait"
        if square_orientation == "portrait"
        else "landscape when source width is greater than or equal to height; otherwise portrait"
    )
    return orientation, dict(target), rule


def prepared_source_destination(
    output_root: str | Path, source_sha256: str, target: Mapping[str, int]
) -> Path:
    """Content-addressed path of the prepared PNG for a source hash and target size."""

    return (
        Path(output_root)
        / "prepared_video_sources"
        / f"{str(source_sha256)[:20]}_{target['width']}x{target['height']}_{_COVER_CENTER_CROP}.png"
    )


def _dimensions(value: Any, field_name: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Workflow source preparation requires {field_name} dimensions.")
    try:
        width = int(value["width"])
        height = int(value["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Workflow source preparation requires valid {field_name} dimensions.") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"Workflow source preparation {field_name} dimensions must be positive.")
    return {"width": width, "height": height}


__all__ = [
    "PREVIEW_MAX_SOURCE_PIXELS",
    "PreparedWorkflowSource",
    "SourceTooLargeForPreview",
    "TransformedWorkflowSource",
    "WorkflowSourceGeometry",
    "cover_crop_box",
    "prepare_declared_workflow_source",
    "prepared_source_destination",
    "preview_declared_workflow_source",
    "resolve_declared_target",
    "transform_declared_workflow_source",
]
