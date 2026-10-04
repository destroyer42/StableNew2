"""FLUX.2 Klein single-reference edit as a normal Review/reprocess job (PR-IMG-116).

Review requests the edit explicitly (``ReprocessSourceItem.metadata[KLEIN_EDIT_METADATA_KEY]``); it is
never inferred from an image's name or content. The result is an ordinary immutable reprocess NJR
whose stage chain is exactly ``img2img`` on ``forge_webui``, frozen to Klein profile v1 and carrying
exactly one source image. There is no multi-reference and no ``ImageStitch Integrated`` payload.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.image_backends.forge_klein_profile import (
    KLEIN_EDIT_METADATA_KEY,
    MODE_SINGLE_REFERENCE_EDIT,
    KleinProfileError,
    klein_edit_config,
    latest_klein_profile,
    validate_klein_intent,
)
from src.image_backends.image_backend_types import configured_image_backend_id

if TYPE_CHECKING:
    from src.pipeline.reprocess_builder import ReprocessSourceItem


def is_klein_edit_item(item: Any) -> bool:
    metadata = getattr(item, "metadata", None)
    return isinstance(metadata, dict) and bool(metadata.get(KLEIN_EDIT_METADATA_KEY))


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    try:
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception as exc:
        raise KleinProfileError(f"Cannot read the source image '{path}': {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_klein_edit_item(
    item: ReprocessSourceItem,
    stages: list[str],
    *,
    backend_id: str | None = None,
) -> tuple[ReprocessSourceItem, dict[str, Any]]:
    """Return the frozen item and reprocess config for one Klein edit, or raise ``KleinProfileError``.

    Validation runs here so the operator gets the reason in the Review dialog before anything is queued.
    """

    profile = latest_klein_profile()
    source = Path(item.input_image_path)
    if not source.is_file():
        raise KleinProfileError(f"Source image not found: {source}")
    width, height = _image_size(source)
    validate_klein_intent(
        profile,
        backend_id=backend_id or configured_image_backend_id(),
        stage_names=stages,
        model_name=profile.transformer.filename,
        sampler=profile.sampler,
        scheduler=profile.scheduler,
        steps=profile.steps,
        cfg_scale=profile.cfg_scale,
        width=width,
        height=height,
        negative_prompt="",
    )
    if not str(item.prompt or "").strip():
        raise KleinProfileError("Describe the edit: the Klein edit prompt is empty.")
    metadata = dict(item.metadata or {})
    metadata[KLEIN_EDIT_METADATA_KEY] = {
        "model_profile": profile.reference(),
        "mode": MODE_SINGLE_REFERENCE_EDIT,
        "source_image_name": source.name,
        "source_image_sha256": _sha256(source),
        "source_width": width,
        "source_height": height,
    }
    frozen = replace(
        item,
        negative_prompt="",
        model=profile.transformer.filename,
        vae=None,
        config={},
        metadata=metadata,
        image_edit=None,
    )
    return frozen, klein_edit_config(width=width, height=height)


__all__ = ["is_klein_edit_item", "prepare_klein_edit_item"]
