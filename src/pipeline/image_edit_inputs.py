"""Bounded, content-addressed image-edit inputs in existing mutable state, like OpenPose snapshots."""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from src.conditioning.openpose_library import (
    MAX_FILE_BYTES,
    OpenPoseInputError,
    ValidatedImage,
    read_bounded_file,
    validate_image_bytes,
)
from src.conditioning.openpose_snapshot import snapshot_path, write_snapshot
from src.pipeline.outpaint_canvas import (
    Extents,
    plain_record,
    prepare_outpaint_canvas,
    verify_derivation,
)

KEY = "image_edit_inputs"
SCHEMA = "stablenew.image_edit.inputs.v1"
OUTPAINT_KEY = "outpaint"
EDIT_OPERATION_KEY = "edit_operation"
ORIGINAL_KEY = "original"


def default_snapshot_root() -> Path:
    from src.state.workspace_paths import workspace_paths

    return workspace_paths.state_dir(create=False) / "image_edit_inputs"


def _owned_snapshot_root() -> Path:
    root = default_snapshot_root().absolute()
    state = root.parent
    # WorkspacePaths resolves the configured workspace, not mutable children of it.
    # Anchor to that parent before resolving state or the snapshot directory.
    expected = state.parent.resolve() / state.name / root.name
    if (
        state.is_symlink()
        or state.is_junction()
        or root.is_symlink()
        or root.is_junction()
        or root.resolve() != expected
    ):
        raise ValueError("Image-edit snapshot directory is outside StableNew-owned input state")
    return expected


def _require_owned_path(path: Path, root: Path) -> None:
    if (
        not path.is_absolute()
        or path.parent != root
        or path.is_symlink()
        or path.is_junction()
        or path.resolve().parent != root
    ):
        raise ValueError("Image-edit snapshot is outside StableNew-owned input state")


def inspect_bytes(data: bytes) -> ValidatedImage:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Image-edit input exceeds the 20 MiB input limit")
    try:
        width, height, fmt = validate_image_bytes(data)
    except OpenPoseInputError as exc:
        raise ValueError(str(exc).replace("OpenPose", "image-edit")) from exc
    with Image.open(io.BytesIO(data)) as image:
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Masked editing supports one still image, not an animation")
    return ValidatedImage(data, hashlib.sha256(data).hexdigest(), len(data), width, height, fmt)


def read_source(path: str | Path) -> ValidatedImage:
    try:
        data = read_bounded_file(Path(path))
    except OpenPoseInputError as exc:
        raise ValueError(str(exc).replace("OpenPose", "image-edit")) from exc
    return inspect_bytes(data)


def _snapshot(image: ValidatedImage) -> dict[str, Any]:
    root = _owned_snapshot_root()
    _require_owned_path(snapshot_path(image.sha256, image.image_format, root), root)
    path = write_snapshot(image, root)
    _require_owned_path(path, _owned_snapshot_root())
    return {
        "path": str(path.resolve()),
        "sha256": image.sha256,
        "size": image.size,
        "width": image.width,
        "height": image.height,
        "format": image.image_format,
    }


def freeze_inputs(source_path: str, mask_data: bytes, source_sha256: str) -> dict[str, Any]:
    source = read_source(source_path)
    if source.sha256 != source_sha256:
        raise ValueError("Source changed since the editor opened; reopen the image")
    mask = inspect_bytes(mask_data)
    if (source.width, source.height) != (mask.width, mask.height):
        raise ValueError("Mask dimensions must exactly match the original source")
    with Image.open(io.BytesIO(mask_data)) as pixels:
        if pixels.mode not in {"1", "L"} or pixels.format != "PNG":
            raise ValueError(
                "The edit mask must be a grayscale PNG: white changes, black preserves"
            )
        if pixels.getextrema()[1] == 0:
            raise ValueError("Paint a region to change before previewing")
    return {
        "schema": SCHEMA,
        "original_path": str(Path(source_path).resolve()),
        "source": _snapshot(source),
        "mask": _snapshot(mask),
    }


def freeze_outpaint_inputs(
    source_path: str, source_sha256: str, extents: Extents, *, steps: int | None = None
) -> dict[str, Any]:
    """Freeze the original, the derived expanded source and the derived mask; geometry is refused before any write."""
    original = read_source(source_path)
    if original.sha256 != source_sha256:
        raise ValueError("Source changed since the editor opened; reopen the image")
    canvas = prepare_outpaint_canvas(original.data, extents, steps=steps)
    expanded, mask = inspect_bytes(canvas.expanded_png), inspect_bytes(canvas.mask_png)
    return {
        "schema": SCHEMA,
        "original_path": str(Path(source_path).resolve()),
        "source": _snapshot(expanded),
        "mask": _snapshot(mask),
        ORIGINAL_KEY: _snapshot(original),
        OUTPAINT_KEY: canvas.record,
    }


def verified_snapshot(raw: Any) -> bytes:
    if not isinstance(raw, Mapping) or not re.fullmatch(
        r"[0-9a-f]{64}", str(raw.get("sha256", ""))
    ):
        raise ValueError("Invalid frozen image-edit identity")
    path = Path(str(raw.get("path", "")))
    _require_owned_path(path, _owned_snapshot_root())
    image = read_source(path)
    expected = {
        "sha256": image.sha256,
        "size": image.size,
        "width": image.width,
        "height": image.height,
        "format": image.image_format,
    }
    if any(raw.get(key) != value for key, value in expected.items()):
        raise ValueError("Frozen image-edit input changed or is corrupt; preview again")
    return image.data


def verified_inputs(
    config: Mapping[str, Any], source_path: str | Path, *, check_original: bool = False
) -> tuple[bytes, bytes]:
    raw = config.get(KEY)
    if not isinstance(raw, Mapping) or raw.get("schema") != SCHEMA:
        raise ValueError("Missing or invalid frozen image-edit inputs")
    source, mask = raw.get("source"), raw.get("mask")
    if not isinstance(source, Mapping) or not isinstance(mask, Mapping):
        raise ValueError("Missing frozen source or mask")
    if str(source_path) != source.get("path") or config.get("mask_image_path") != mask.get("path"):
        raise ValueError("Image-edit paths no longer match the frozen preview")
    source_data, mask_data = verified_snapshot(source), verified_snapshot(mask)
    with Image.open(io.BytesIO(mask_data)) as pixels:
        if pixels.mode not in {"1", "L"} or pixels.format != "PNG" or pixels.getextrema()[1] == 0:
            raise ValueError("Frozen edit mask must be a nonempty grayscale PNG")
    if (source.get("width"), source.get("height")) != (mask.get("width"), mask.get("height")):
        raise ValueError("Frozen mask and source dimensions differ")
    identity = source
    if (ORIGINAL_KEY in raw) != (OUTPAINT_KEY in raw) or (
        config.get(EDIT_OPERATION_KEY) == OUTPAINT_KEY
    ) != (OUTPAINT_KEY in raw):
        raise ValueError("Incomplete frozen outpaint contract; preview again")
    if OUTPAINT_KEY in raw:
        original = raw[ORIGINAL_KEY]
        if not isinstance(original, Mapping) or not isinstance(raw[OUTPAINT_KEY], Mapping):
            raise ValueError("Invalid frozen outpaint contract")
        verify_derivation(raw[OUTPAINT_KEY], verified_snapshot(original), source_data, mask_data)
        identity = original
    if check_original and read_source(str(raw.get("original_path", ""))).sha256 != identity.get(
        "sha256"
    ):
        raise ValueError("Source changed after Preview; preview again before queueing")
    return source_data, mask_data


@dataclass(frozen=True, slots=True)
class FrozenOutpaint:
    original_bytes: bytes
    record: dict[str, Any]
    original_path: str


def verified_outpaint(config: Mapping[str, Any]) -> FrozenOutpaint | None:
    """The verified original and record of a frozen outpaint; ``None`` for any other edit. Call after ``verified_inputs``."""
    raw = config.get(KEY)
    if not isinstance(raw, Mapping) or OUTPAINT_KEY not in raw:
        return None
    return FrozenOutpaint(
        verified_snapshot(raw[ORIGINAL_KEY]),
        plain_record(raw[OUTPAINT_KEY]),
        str(raw.get("original_path", "")),
    )
