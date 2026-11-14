"""Bounded inspection and explicit Smart Review imports for the guided finding workspace."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from src.pipeline.image_edit_inputs import read_source
from src.review.assist.contracts import CaptionProposal, SegmentProposal, SourceIdentity
from src.review.assist.masks import mask_image, validate_mask_png
from src.review.findings import Category, Finding, FindingSource, Origin, Region
from src.utils.image_metadata import (
    ImageMetadataContractV26,
    decode_payload,
    read_image_metadata,
    resolve_prompt_fields,
)


@dataclass(frozen=True, slots=True)
class GuidedSource:
    source: FindingSource
    data: bytes
    subject: dict[str, Any]


def inspect_source(path: Path, revision: tuple[int, int]) -> GuidedSource:
    source = read_source(path)
    with Image.open(io.BytesIO(source.data)) as image:
        if source.image_format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Inspect & Improve supports PNG, JPEG and WebP still images.")
        orientation = image.getexif().get(0x0112, 1)
    identity = SourceIdentity(
        source.sha256,
        source.size,
        source.width,
        source.height,
        orientation if type(orientation) is int and 1 <= orientation <= 8 else 1,
        source.image_format,
    )
    metadata = read_image_metadata(path, source_bytes=source.data)
    result = (
        decode_payload(metadata, max_decoded_bytes=ImageMetadataContractV26.HARD_LIMIT_BYTES)
        if metadata.get(ImageMetadataContractV26.KEY_SCHEMA) == ImageMetadataContractV26.SCHEMA
        else None
    )
    payload = result.payload if result and result.status == "ok" else None
    positive, negative = resolve_prompt_fields(payload)
    subject = {
        "name": path.name,
        "positive_prompt": positive,
        "negative_prompt": negative,
        "description": metadata.get(ImageMetadataContractV26.PUBLIC_KEY_PARAMETERS)
        or metadata.get(ImageMetadataContractV26.PUBLIC_KEY_DESCRIPTION, ""),
        "content_visibility": (
            {"rating": "nsfw"}
            if result and result.status == "corrupt"
            else (payload or {}).get("content_visibility")
        ),
    }
    return GuidedSource(FindingSource(path, identity, revision), source.data, subject)


def import_suggestion(
    source: FindingSource, proposal: CaptionProposal | SegmentProposal
) -> tuple[Finding, bytes | None]:
    if source.identity != proposal.identity:
        raise ValueError("The suggestion belongs to different image bytes.")
    label = f"{proposal.model.label} · Unqualified suggestion"
    if isinstance(proposal, CaptionProposal):
        return Finding(
            source, None, Category.GENERAL, Origin.MODEL, proposal.text, suggestion_label=label
        ), None
    if validate_mask_png(proposal.mask_png, source.identity).sha256 != proposal.mask_sha256:
        raise ValueError("The suggested mask identity changed.")
    mask = mask_image(proposal.mask_png, source.identity)
    box = mask.getbbox()
    if box is None:
        raise ValueError("The suggested mask does not contain a region.")
    return Finding(
        source,
        Region(*box),
        Category.GENERAL,
        Origin.DETECTOR,
        "Suggested object mask. Inspect this region and describe a visible issue.",
        suggestion_label=label,
    ), proposal.mask_png
