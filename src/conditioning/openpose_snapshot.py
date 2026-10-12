"""Frozen OpenPose conditioning: verified identity plus a job-owned, content-addressed input snapshot (PR-IMG-CNET-210).

The compiler freezes *what it verified* into the immutable NJR (``FrozenOpenPose``): the library identity, the SHA-256
and size of the exact bytes, the image facts and a StableNew-owned snapshot path. The NJR never carries image bytes
(no base64). The snapshot is a byte-for-byte copy named by its own SHA-256 inside StableNew's mutable state directory, so:

* replacing or editing the library file afterwards can never change what a queued or replayed job conditions on;
* a snapshot can be re-verified by hash at any moment (admission, dispatch, replay);
* two jobs naming identical bytes share one file, and nothing ever rewrites a file under a different digest.

Nothing here talks to a backend. Functions that read files are worker-side.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.conditioning.openpose import (
    CONTRACT,
    PREPROCESSOR_NONE,
    SUPPORTED_EXTENSIONS,
    OpenPoseDeclarationError,
    OpenPoseSelection,
    normalize_asset_identity,
    parse_declaration,
)
from src.conditioning.openpose_library import (
    CODE_CHANGED,
    CODE_MISSING,
    MAX_FILE_BYTES,
    OpenPoseInputError,
    ValidatedImage,
    read_bounded_file,
    read_library_image,
)

SNAPSHOT_SUBDIRS = ("conditioning_inputs", "openpose")
STAGE_TXT2IMG = "txt2img"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FORMAT_EXTENSION = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
_FORMATS = frozenset(_FORMAT_EXTENSION)


def default_snapshot_root() -> Path:
    """StableNew's mutable-state home for conditioning snapshots (no filesystem write; created lazily on first use)."""

    from src.state.workspace_paths import workspace_paths

    return workspace_paths.state_dir(create=False).joinpath(*SNAPSHOT_SUBDIRS)


def snapshot_path(sha256: str, image_format: str, root: Path | None = None) -> Path:
    return (root or default_snapshot_root()) / f"{sha256}{_FORMAT_EXTENSION[image_format]}"


def write_snapshot(image: ValidatedImage, root: Path | None = None) -> Path:
    """Persist the validated bytes under their digest (idempotent, atomic, and self-healing on a corrupt name)."""

    destination = snapshot_path(image.sha256, image.image_format, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        try:
            if read_bounded_file(destination) == image.data:
                return destination
        except OpenPoseInputError:
            pass  # unreadable/corrupt content-addressed file: replace it with the verified bytes below
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{image.sha256[:16]}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(image.data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, destination)
        except PermissionError:
            # Another process may be reading the winner on Windows; reuse it only if it is byte-identical.
            if not destination.is_file() or read_bounded_file(destination) != image.data:
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


@dataclass(frozen=True, slots=True)
class FrozenOpenPose:
    """The immutable, verified conditioning of one job (JSON-serializable; carries no image bytes)."""

    asset: str
    asset_sha256: str
    asset_size: int
    width: int
    height: int
    image_format: str
    snapshot_path: str
    model: str
    weight: float
    guidance_start: float
    guidance_end: float
    control_mode: str
    resize_mode: str
    preprocessor: str = PREPROCESSOR_NONE
    pixel_perfect: bool = False
    stage: str = STAGE_TXT2IMG

    def to_config(self) -> dict[str, Any]:
        """The exact shape frozen into ``NormalizedJobRecord.config['controlnet_openpose']``."""

        return {
            "contract": CONTRACT,
            "enabled": True,
            "stage": self.stage,
            "asset": self.asset,
            "asset_sha256": self.asset_sha256,
            "asset_size": self.asset_size,
            "image": {"width": self.width, "height": self.height, "format": self.image_format},
            "snapshot": {"path": self.snapshot_path},
            "model": self.model,
            "weight": self.weight,
            "guidance_start": self.guidance_start,
            "guidance_end": self.guidance_end,
            "control_mode": self.control_mode,
            "resize_mode": self.resize_mode,
            "preprocessor": self.preprocessor,
            "pixel_perfect": self.pixel_perfect,
        }

    @classmethod
    def from_config(cls, raw: Any) -> FrozenOpenPose:
        """Strictly read a frozen record; ``OpenPoseDeclarationError`` for anything not exactly what the compiler wrote."""

        if not isinstance(raw, Mapping):
            raise OpenPoseDeclarationError(("frozen controlnet_openpose must be an object",))
        problems: list[str] = []
        known = {
            "contract", "enabled", "stage", "asset", "asset_sha256", "asset_size", "image", "snapshot",
            "model", "weight", "guidance_start", "guidance_end", "control_mode", "resize_mode",
            "preprocessor", "pixel_perfect",
        }  # fmt: skip
        extra = sorted(str(key) for key in raw if key not in known)
        if extra:
            problems.append("unsupported frozen field(s): " + ", ".join(extra))
        if raw.get("enabled") is not True:
            problems.append("a frozen record must be enabled")
        if raw.get("stage") != STAGE_TXT2IMG:
            problems.append("conditioning applies to the base txt2img stage only")
        if raw.get("pixel_perfect") is not False:
            problems.append("pixel_perfect must be false")
        digest = raw.get("asset_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            problems.append("asset_sha256 must be a lowercase SHA-256")
            digest = ""
        size = raw.get("asset_size")
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
            problems.append("asset_size is not a valid byte count")
            size = 0
        image = raw.get("image")
        raw_width: Any = image.get("width") if isinstance(image, Mapping) else None
        raw_height: Any = image.get("height") if isinstance(image, Mapping) else None
        fmt = str(image.get("format") or "") if isinstance(image, Mapping) else ""
        width = height = 0
        if (
            type(raw_width) is int
            and type(raw_height) is int
            and raw_width > 0
            and raw_height > 0
            and fmt in _FORMATS
        ):
            width, height = raw_width, raw_height
        else:
            problems.append("image facts (width, height, format) are invalid")
            fmt = ""
        snapshot = raw.get("snapshot")
        path_text = str(snapshot.get("path") or "") if isinstance(snapshot, Mapping) else ""
        if not path_text:
            problems.append("snapshot.path is missing")
        else:
            candidate = Path(path_text)
            if candidate.stem != digest or candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
                problems.append("snapshot.path is not the content-addressed snapshot of asset_sha256")
        declaration = {
            "contract": raw.get("contract"),
            "enabled": True,
            "asset": raw.get("asset"),
            "model": raw.get("model", ""),
            "weight": raw.get("weight"),
            "guidance_start": raw.get("guidance_start"),
            "guidance_end": raw.get("guidance_end"),
            "control_mode": raw.get("control_mode"),
            "resize_mode": raw.get("resize_mode"),
            "preprocessor": raw.get("preprocessor"),
        }
        selection: OpenPoseSelection | None = None
        try:
            selection = parse_declaration(declaration)
        except OpenPoseDeclarationError as exc:
            problems.extend(exc.problems)
        if selection is not None and not selection.model:
            problems.append("a ControlNet model must be frozen")
        if problems or selection is None:
            raise OpenPoseDeclarationError(problems)
        return cls(
            asset=selection.asset,
            asset_sha256=digest,
            asset_size=size,
            width=width,
            height=height,
            image_format=fmt,
            snapshot_path=path_text,
            model=selection.model,
            weight=selection.weight,
            guidance_start=selection.guidance_start,
            guidance_end=selection.guidance_end,
            control_mode=selection.control_mode,
            resize_mode=selection.resize_mode,
        )

    def evidence(self) -> dict[str, Any]:
        """Content-free, path-free provenance suitable for manifests and history (never image bytes)."""

        return {
            "contract": CONTRACT,
            "stage": self.stage,
            "asset": self.asset,
            "asset_sha256": self.asset_sha256,
            "asset_size": self.asset_size,
            "image": {"width": self.width, "height": self.height, "format": self.image_format},
            "model": self.model,
            "weight": self.weight,
            "guidance_start": self.guidance_start,
            "guidance_end": self.guidance_end,
            "control_mode": self.control_mode,
            "resize_mode": self.resize_mode,
            "preprocessor": self.preprocessor,
        }


def freeze_selection(
    selection: OpenPoseSelection,
    *,
    library: Path | str | None,
    snapshot_root: Path | None = None,
    image: ValidatedImage | None = None,
) -> FrozenOpenPose:
    """Verify one enabled declaration against the library and freeze it (worker-side; reads the file exactly once).

    ``image`` lets a caller that already read and validated this exact asset (one build, many Matrix variants) reuse
    those bytes instead of reading again; the snapshot and identity are always derived from the bytes passed in.

    Raises ``OpenPoseInputError`` for a missing/escaping/oversized/malformed image and ``ValueError`` when no
    ControlNet model was chosen: a declaration without a model is incomplete and never reaches the queue.
    """

    if not selection.model:
        raise ValueError("choose a ControlNet model for the OpenPose conditioning")
    if image is None:
        _resolved, image = read_library_image(library, selection.asset)
    path = write_snapshot(image, snapshot_root)
    return FrozenOpenPose(
        asset=normalize_asset_identity(selection.asset),
        asset_sha256=image.sha256,
        asset_size=image.size,
        width=image.width,
        height=image.height,
        image_format=image.image_format,
        snapshot_path=str(path),
        model=selection.model,
        weight=selection.weight,
        guidance_start=selection.guidance_start,
        guidance_end=selection.guidance_end,
        control_mode=selection.control_mode,
        resize_mode=selection.resize_mode,
    )


def verify_frozen(frozen: FrozenOpenPose) -> bytes:
    """Re-read the job-owned snapshot and prove it is still exactly the verified bytes; returns those bytes.

    Called immediately before any generation POST (and by replay admission). The bytes returned are the ones that must
    be sent: callers must not re-read the file afterwards.
    """

    import hashlib

    path = Path(frozen.snapshot_path)
    if not path.is_file():
        raise OpenPoseInputError(
            CODE_MISSING,
            f"The frozen OpenPose input for '{frozen.asset}' is no longer available; rebuild Preview to refreeze it.",
        )
    data = read_bounded_file(path)
    if len(data) != frozen.asset_size or hashlib.sha256(data).hexdigest() != frozen.asset_sha256:
        raise OpenPoseInputError(
            CODE_CHANGED,
            f"The frozen OpenPose input for '{frozen.asset}' changed after the job was admitted; "
            "refusing to dispatch. Rebuild Preview to freeze the current image.",
        )
    return data


__all__ = [
    "FrozenOpenPose",
    "SNAPSHOT_SUBDIRS",
    "STAGE_TXT2IMG",
    "default_snapshot_root",
    "freeze_selection",
    "snapshot_path",
    "verify_frozen",
    "write_snapshot",
]
