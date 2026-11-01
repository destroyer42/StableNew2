"""Bounded verification of the one recorded still image per job (PR-HISTORY-610B); no thumbnail or directory fallback.

``verify_image`` and ``decode_verified_image`` do blocking file reads and decoding: call them on a worker only. Refusal
messages are content-safe (no file names, paths, prompts or embedded metadata).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
from dataclasses import dataclass

from PIL import Image

from src.gui.view_contracts.history_artifact_contract import resolve_single_still_image
from src.gui.view_contracts.media_image_decode import (
    MAX_SOURCE_PIXELS,
    InspectionImage,
    decode_inspection_image,
)
from src.gui_v2.history_compare_model import ComparisonRefused
from src.queue.job_history_store import JobHistoryEntry
from src.utils.image_metadata import ImageMetadataContractV26

MAX_FILE_BYTES = 64 * 1024 * 1024
_STILL_FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}
_EXIF_USER_COMMENT = 37510


@dataclass(frozen=True)
class VerifiedImage:
    path: str
    job_id: str
    sha256: str
    size: tuple[int, int]
    historical_hash: bool  # the job's own result recorded a digest that the current bytes match


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ComparisonRefused("The recorded image is missing or unreadable.") from exc
    if len(data) > MAX_FILE_BYTES:
        raise ComparisonRefused("The image exceeds the 64 MiB comparison budget.")
    return data


def _refusal_for(message: str) -> str:
    # The artifact projection can contain a file name: translate it so every visibility mode stays safe.
    lowered = message.lower()
    if "missing" in lowered:
        return "The recorded still image is missing."
    if "thumbnail" in lowered:
        return "Only a thumbnail was recorded, not the output image."
    if "video" in lowered:
        return "The recorded result is video, not a supported still image."
    if "images" in lowered or "variant" in lowered:
        return "The recorded result contains multiple images; choosing one is not supported."
    return "No supported still-image artifact was recorded."


def _embedded_job_id(image: Image.Image) -> str | None:
    embedded = image.info.get(ImageMetadataContractV26.KEY_JOB_ID)
    if image.format == "JPEG":
        comment = image.getexif().get(_EXIF_USER_COMMENT, b"")
        if isinstance(comment, str):
            comment = comment.encode("ascii", errors="ignore")
        if isinstance(comment, bytes) and comment.startswith(b"SNMETA:"):
            if len(comment) > ImageMetadataContractV26.HARD_LIMIT_BYTES * 2:
                raise ComparisonRefused("Embedded image identity exceeds the metadata budget.")
            try:
                metadata = json.loads(base64.b64decode(comment[7:], validate=True))
                embedded = metadata.get(ImageMetadataContractV26.KEY_JOB_ID)
            except (ValueError, TypeError, AttributeError) as exc:
                raise ComparisonRefused("Embedded image identity is malformed.") from exc
    return str(embedded) if embedded else None


def _recorded_digests(entry: JobHistoryEntry) -> list[str]:
    result = entry.result if isinstance(entry.result, dict) else {}
    artifacts = [result.get("artifact", {})] + [
        v.get("artifact", {}) for v in result.get("variants", []) if isinstance(v, dict)
    ]
    digests: list[str] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        if item.get("sha256"):
            digests.append(str(item["sha256"]).removeprefix("sha256:"))
        identity = str(item.get("artifact_id") or "")
        if identity.startswith("sha256:"):
            digests.append(identity.removeprefix("sha256:"))
        if item.get("job_id") and item["job_id"] != entry.job_id:
            raise ComparisonRefused("The recorded artifact contradicts the job identity.")
    return digests


def verify_image(entry: JobHistoryEntry) -> VerifiedImage:
    """Resolve the job's single recorded still image and prove the file on disk is that image."""

    artifact = resolve_single_still_image(entry.result)
    if not artifact.path or artifact.message or artifact.kind != "image":
        raise ComparisonRefused(_refusal_for(artifact.message or ""))
    data = _read(artifact.path)
    digest = hashlib.sha256(data).hexdigest()
    claims = _recorded_digests(entry)
    if any(claim != digest for claim in claims):
        raise ComparisonRefused("The image bytes no longer match the recorded artifact hash.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in _STILL_FORMATS:
                raise ComparisonRefused("The recorded file is not a supported still image.")
            if getattr(image, "n_frames", 1) != 1:
                raise ComparisonRefused("Animated or multi-frame images cannot be compared.")
            if image.width * image.height > MAX_SOURCE_PIXELS:
                raise ComparisonRefused("The image exceeds the 16 megapixel inspection budget.")
            embedded = _embedded_job_id(image)
            if embedded and embedded != entry.job_id:
                raise ComparisonRefused("The image's embedded job identity contradicts History.")
            size = (image.width, image.height)
            image.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ComparisonRefused("The recorded image is corrupt or unsupported.") from exc
    return VerifiedImage(artifact.path, entry.job_id, digest, size, bool(claims))


def decode_verified_image(expected: VerifiedImage, cancel: threading.Event) -> InspectionImage:
    """Decode for display only if the bytes are still exactly the ones that were verified."""

    data = _read(expected.path)
    if hashlib.sha256(data).hexdigest() != expected.sha256:
        raise ComparisonRefused("The image changed after verification; reopen the comparison.")
    return decode_inspection_image(expected.path, cancel, source_bytes=data)


__all__ = ["MAX_FILE_BYTES", "VerifiedImage", "decode_verified_image", "verify_image"]
