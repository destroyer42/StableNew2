"""Non-mutating, digest-bound Review evidence (PR-REVIEW-EVIDENCE-620).

Saving a Review rating or disposition appends one record through ``LearningRecordWriter`` and never touches the image
file. The record names the image by the SHA-256 of its bytes (``artifact_sha256``); the path is only a locator. A file
whose bytes changed since it was reviewed is reported as changed rather than silently matched to the older rating.

This module is Tk-free. Reading scans the records file and hashing reads the image, so callers on the GUI thread should
use the existing Review image-context worker.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.learning_record import LearningRecord, LearningRecordWriter
from src.review.review_metadata_service import (
    INTERNAL_REVIEW_SUMMARY_SCHEMA,
    PortableReviewSummary,
    ReviewMetadataService,
    ReviewMetadataStampResult,
)

RATING_KIND = "review_tab_feedback"
RATING_SOURCE = "review_tab"
DISPOSITION_KIND = "review_disposition"
#: Distinct from ``RATING_SOURCE`` so rating listing and "Undo Last Save" never mistake a disposition for a rating.
DISPOSITION_SOURCE = "review_tab_disposition"
DISPOSITIONS = ("retain", "discard", "rework")

#: The record names the bytes that were reviewed and the file currently has those bytes.
IDENTITY_DIGEST = "digest"
#: Matched by path only: a legacy row with no recorded digest, or the current digest could not be computed.
IDENTITY_PATH = "path"
#: The path has a rating, but for different bytes; it is reported, never applied to the current file.
IDENTITY_CHANGED = "changed"

_HASH_CHUNK = 1024 * 1024


def file_sha256(path: str | os.PathLike[str]) -> str | None:
    """Streamed SHA-256 of the file as it is now, or ``None`` when it cannot be read."""

    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            while chunk := stream.read(_HASH_CHUNK):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def normalize_digest(value: Any) -> str:
    """A lowercase 64-hex digest (an optional ``sha256:`` prefix is accepted), else an empty string."""

    text = str(value or "").strip().lower().removeprefix("sha256:")
    return text if len(text) == 64 and all(char in "0123456789abcdef" for char in text) else ""


def _same_path(left: Any, right: Any) -> bool:
    if not str(left or "").strip() or not str(right or "").strip():
        return False
    return os.path.normcase(str(Path(str(left).strip()))) == os.path.normcase(
        str(Path(str(right).strip()))
    )


def build_review_rating_record(
    feedback: Mapping[str, Any], *, artifact_sha256: str | None = None
) -> LearningRecord:
    """Validate Review feedback and build its ``review_tab_feedback`` record (nothing is written).

    The digest is ``artifact_sha256`` (or ``feedback["artifact_sha256"]``, which Review takes from the bytes it showed),
    else it is computed from the file. A file that cannot be read yields a path-only record.
    """

    image_path = str(feedback.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("image_path is required")
    try:
        rating = int(feedback.get("rating", 0))
    except Exception as exc:
        raise ValueError("rating must be an integer") from exc
    if rating < 1 or rating > 5:
        raise ValueError("rating must be between 1 and 5")
    subscores_raw = feedback.get("subscores") or {}
    subscores = {
        "anatomy": int(subscores_raw.get("anatomy", rating) or rating),
        "composition": int(subscores_raw.get("composition", rating) or rating),
        "prompt_adherence": int(subscores_raw.get("prompt_adherence", rating) or rating),
    }
    for key, value in subscores.items():
        if value < 1 or value > 5:
            raise ValueError(f"{key} must be between 1 and 5")
    weighted_score = (
        (rating * 0.4)
        + (subscores["anatomy"] * 0.2)
        + (subscores["composition"] * 0.2)
        + (subscores["prompt_adherence"] * 0.2)
    )
    base_prompt = str(feedback.get("base_prompt") or "")
    base_negative = str(feedback.get("base_negative_prompt") or "")
    after_prompt = str(feedback.get("after_prompt") or base_prompt)
    after_negative = str(feedback.get("after_negative_prompt") or base_negative)
    model = str(feedback.get("model") or "")
    stage = str(feedback.get("stage") or "review")
    metadata: dict[str, Any] = {
        "source": RATING_SOURCE,
        "record_kind": RATING_KIND,
        "image_path": image_path,
        "user_rating": int(min(5, max(1, round(weighted_score)))),
        "user_rating_raw": rating,
        "advanced_rating_enabled": True,
        "subscores": subscores,
        "weighted_score": weighted_score,
        "quality_label": str(feedback.get("quality_label") or ""),
        "user_notes": str(feedback.get("notes") or ""),
        "stage": stage,
        "model": model,
        "prompt_before": base_prompt,
        "prompt_after": after_prompt,
        "negative_prompt_before": base_negative,
        "negative_prompt_after": after_negative,
        "prompt_delta": str(feedback.get("prompt_delta") or ""),
        "negative_prompt_delta": str(feedback.get("negative_prompt_delta") or ""),
        "prompt_mode": str(feedback.get("prompt_mode") or "append"),
        "negative_prompt_mode": str(feedback.get("negative_prompt_mode") or "append"),
        "stages": list(feedback.get("stages") or []),
        "review_context": dict(feedback.get("context") or {}),
    }
    digest = normalize_digest(artifact_sha256 or feedback.get("artifact_sha256")) or (
        file_sha256(image_path) or ""
    )
    if digest:
        metadata["artifact_sha256"] = digest
    source_job_id = str(feedback.get("source_job_id") or "").strip()
    if source_job_id:
        metadata["source_job_id"] = source_job_id
    sampler = str(feedback.get("sampler") or "")
    scheduler = str(feedback.get("scheduler") or "")
    steps = feedback.get("steps")
    cfg_scale = feedback.get("cfg_scale")

    def extract_primary(_cfg: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": model,
            "sampler": sampler,
            "scheduler": scheduler,
            "steps": steps,
            "cfg_scale": cfg_scale,
        }

    return LearningRecord.from_pipeline_context(
        base_config={
            "stage": stage,
            "model": model,
            "prompt": base_prompt,
            "negative_prompt": base_negative,
        },
        variant_configs=[
            {"prompt": after_prompt, "negative_prompt": after_negative, "model": model}
        ],
        randomizer_mode="review_feedback",
        randomizer_plan_size=1,
        extract_primary=extract_primary,
        metadata=metadata,
    )


def build_disposition_record(
    *,
    image_path: str | os.PathLike[str],
    disposition: str,
    artifact_sha256: str | None = None,
    source_job_id: str = "",
    notes: str = "",
) -> LearningRecord:
    """Build a Retain / Discard / Re-work record bound to the image bytes (nothing is written or moved)."""

    value = str(disposition or "").strip().lower()
    if value not in DISPOSITIONS:
        raise ValueError(f"disposition must be one of {', '.join(DISPOSITIONS)}")
    path_text = str(image_path or "").strip()
    if not path_text:
        raise ValueError("image_path is required")
    digest = normalize_digest(artifact_sha256) or (file_sha256(path_text) or "")
    if not digest:
        raise ValueError("The image could not be read, so its identity cannot be recorded.")
    metadata: dict[str, Any] = {
        "source": DISPOSITION_SOURCE,
        "record_kind": DISPOSITION_KIND,
        "image_path": path_text,
        "artifact_sha256": digest,
        "review_disposition": value,
        "user_notes": str(notes or ""),
    }
    if str(source_job_id or "").strip():
        metadata["source_job_id"] = str(source_job_id).strip()
    return LearningRecord.from_pipeline_context(
        base_config={},
        variant_configs=[],
        randomizer_mode="review_disposition",
        randomizer_plan_size=1,
        metadata=metadata,
    )


def save_disposition(writer: LearningRecordWriter, **kwargs: Any) -> LearningRecord:
    """Append a disposition through the one writer; raises ``OSError`` when it was not confirmed saved."""

    record = build_disposition_record(**kwargs)
    if writer.append_record(record) is False:
        raise OSError("The review decision was not confirmed saved; see the log before retrying.")
    return record


def _iter_rows(records_path: Path) -> Iterator[dict[str, Any]]:
    try:
        with open(records_path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
                    yield payload
    except OSError:
        return


@dataclass(frozen=True)
class EvidenceLookup:
    """The latest row for an image and how it was matched; ``row`` is the stored record payload."""

    row: dict[str, Any] | None = None
    identity: str = ""


def _lookup(
    records_path: Path, source: str, image_path: str, artifact_sha256: str | None
) -> EvidenceLookup:
    """Latest row by digest first, then by path; a path row for different bytes is reported as changed."""

    digest = normalize_digest(artifact_sha256)
    by_digest: dict[str, Any] | None = None
    by_path: dict[str, Any] | None = None
    for payload in _iter_rows(records_path):
        metadata = payload["metadata"]
        if metadata.get("source") != source:
            continue
        recorded = normalize_digest(metadata.get("artifact_sha256"))
        if digest and recorded == digest:
            by_digest = payload
        if _same_path(metadata.get("image_path"), image_path):
            by_path = payload
    if by_digest is not None:
        return EvidenceLookup(by_digest, IDENTITY_DIGEST)
    if by_path is None:
        return EvidenceLookup()
    recorded = normalize_digest(by_path["metadata"].get("artifact_sha256"))
    if digest and recorded and recorded != digest:
        return EvidenceLookup(by_path, IDENTITY_CHANGED)
    return EvidenceLookup(by_path, IDENTITY_PATH)


def lookup_rating(
    records_path: str | os.PathLike[str],
    image_path: str | os.PathLike[str],
    artifact_sha256: str | None,
) -> EvidenceLookup:
    return _lookup(Path(records_path), RATING_SOURCE, str(image_path), artifact_sha256)


@dataclass(frozen=True)
class DispositionLookup:
    """The latest decision for an image: ``disposition`` is empty when none was recorded for these bytes."""

    disposition: str = ""
    identity: str = ""
    timestamp: str = ""
    run_id: str = ""


def lookup_disposition(
    records_path: str | os.PathLike[str],
    image_path: str | os.PathLike[str],
    artifact_sha256: str | None,
) -> DispositionLookup:
    """Latest Retain / Discard / Re-work for the bytes (digest first, then path); latest row wins.

    A decision recorded for different bytes is reported with ``identity="changed"`` and is not applied.
    """

    found = _lookup(Path(records_path), DISPOSITION_SOURCE, str(image_path), artifact_sha256)
    if found.row is None:
        return DispositionLookup()
    metadata = found.row["metadata"]
    value = str(metadata.get("review_disposition") or "")
    return DispositionLookup(
        disposition=value if value in DISPOSITIONS else "",
        identity=found.identity,
        timestamp=str(found.row.get("timestamp") or ""),
        run_id=str(found.row.get("run_id") or ""),
    )


def summary_from_row(row: Mapping[str, Any], identity: str) -> PortableReviewSummary:
    metadata = row.get("metadata") or {}
    return PortableReviewSummary(
        source_type="internal_learning_record",
        schema=INTERNAL_REVIEW_SUMMARY_SCHEMA,
        review_timestamp=str(row.get("timestamp") or ""),
        user_rating=metadata.get("user_rating"),
        user_rating_raw=metadata.get("user_rating_raw"),
        quality_label=str(metadata.get("quality_label") or ""),
        subscores=dict(metadata.get("subscores") or {}),
        weighted_score=metadata.get("weighted_score"),
        user_notes=str(metadata.get("user_notes") or ""),
        prompt_before=str(metadata.get("prompt_before") or ""),
        prompt_after=str(metadata.get("prompt_after") or ""),
        negative_prompt_before=str(metadata.get("negative_prompt_before") or ""),
        negative_prompt_after=str(metadata.get("negative_prompt_after") or ""),
        prompt_delta=str(metadata.get("prompt_delta") or ""),
        negative_prompt_delta=str(metadata.get("negative_prompt_delta") or ""),
        prompt_mode=str(metadata.get("prompt_mode") or ""),
        negative_prompt_mode=str(metadata.get("negative_prompt_mode") or ""),
        stages=[
            str(stage) for stage in list(metadata.get("stages") or []) if str(stage or "").strip()
        ],
        review_context=dict(metadata.get("review_context") or {}),
        review_record_id=str(row.get("run_id") or ""),
        identity_status=identity,
        artifact_sha256=normalize_digest(metadata.get("artifact_sha256")),
    )


def resolve_prior_review_summary(
    writer: LearningRecordWriter | None,
    metadata_service: ReviewMetadataService,
    image_path: str | os.PathLike[str],
    artifact_sha256: str | None = None,
) -> dict[str, Any] | None:
    """The saved review for an image: digest, then path, then legacy embedded or sidecar metadata.

    A rating recorded for different bytes is returned (``identity_status == "changed"``) only when nothing else
    describes the current file, so a changed file is never shown as if it carried the older rating.
    """

    path_text = str(Path(str(image_path or "").strip()))
    if not str(image_path or "").strip():
        return None
    digest = normalize_digest(artifact_sha256) or file_sha256(path_text)
    found = EvidenceLookup()
    if writer is not None and writer.records_path.exists():
        found = lookup_rating(writer.records_path, path_text, digest)
    if found.row is not None and found.identity != IDENTITY_CHANGED:
        return summary_from_row(found.row, found.identity).to_dict()
    portable = metadata_service.read_review_summary(path_text)
    if portable is not None:
        return portable.to_dict()
    if found.row is not None:
        return summary_from_row(found.row, found.identity).to_dict()
    return None


def write_rating_into_file(
    writer: LearningRecordWriter | None,
    metadata_service: ReviewMetadataService,
    image_path: str | os.PathLike[str],
) -> ReviewMetadataStampResult:
    """The explicit "Write rating into file" export of the saved rating for the file's current bytes.

    PNG embeds the rating (the file's bytes change); JPEG and WebP get a sidecar and are never re-encoded. Raises
    ``ValueError`` when no rating is saved for these exact bytes.
    """

    path_text = str(image_path or "").strip()
    if writer is None or not writer.records_path.exists() or not path_text:
        raise ValueError("No saved rating to write.")
    found = lookup_rating(writer.records_path, path_text, file_sha256(path_text))
    if found.row is None or found.identity == IDENTITY_CHANGED:
        raise ValueError("No rating is saved for this image's current content.")
    record = LearningRecord.from_json(json.dumps(found.row))
    return metadata_service.stamp_review_metadata(image_path=path_text, feedback={}, record=record)


__all__ = [
    "DISPOSITIONS",
    "DISPOSITION_KIND",
    "DISPOSITION_SOURCE",
    "DispositionLookup",
    "EvidenceLookup",
    "IDENTITY_CHANGED",
    "IDENTITY_DIGEST",
    "IDENTITY_PATH",
    "RATING_KIND",
    "RATING_SOURCE",
    "build_disposition_record",
    "build_review_rating_record",
    "file_sha256",
    "lookup_disposition",
    "lookup_rating",
    "normalize_digest",
    "resolve_prior_review_summary",
    "save_disposition",
    "summary_from_row",
    "write_rating_into_file",
]
