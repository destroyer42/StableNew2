"""Deterministic source preparation declared by a workflow catalog entry.

The preparation happens before queue admission.  The immutable NJR therefore
references a StableNew-owned prepared image and retains enough provenance to
replay the same geometry without asking a backend to reinterpret the source.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

_COVER_CENTER_CROP = "cover_resize_center_crop"


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


def prepare_declared_workflow_source(
    *,
    source_path: str | Path,
    output_root: str | Path,
    policy: Mapping[str, Any],
) -> PreparedWorkflowSource:
    """Prepare a catalog-declared source using the bounded cover/crop policy."""

    if str(policy.get("resize_policy") or "") != _COVER_CENTER_CROP:
        raise ValueError("Workflow source preparation declares an unsupported resize policy.")
    portrait_target = _dimensions(policy.get("portrait_target"), "portrait_target")
    landscape_target = _dimensions(policy.get("landscape_target"), "landscape_target")
    square_orientation = str(policy.get("square_orientation") or "portrait").strip().lower()
    if square_orientation not in {"portrait", "landscape"}:
        raise ValueError("Workflow source preparation square_orientation must be portrait or landscape.")

    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Video workflow source image does not exist: {source}")
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Failed to open video workflow source image: {exc}") from exc
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Video workflow source image dimensions must be positive.")

    orientation = "landscape" if width > height else "portrait"
    if width == height:
        orientation = square_orientation
    target = landscape_target if orientation == "landscape" else portrait_target
    prepared = ImageOps.fit(
        image,
        (target["width"], target["height"]),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    content_digest = hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    prepared_root = Path(output_root) / "prepared_video_sources"
    prepared_root.mkdir(parents=True, exist_ok=True)
    prepared_path = prepared_root / (
        f"{content_digest}_{target['width']}x{target['height']}_{_COVER_CENTER_CROP}.png"
    )
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
        orientation_rule=(
            "landscape when source width is greater than height; otherwise portrait"
            if square_orientation == "portrait"
            else "landscape when source width is greater than or equal to height; otherwise portrait"
        ),
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


__all__ = ["PreparedWorkflowSource", "prepare_declared_workflow_source"]
