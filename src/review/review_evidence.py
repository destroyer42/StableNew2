"""Non-mutating, digest-bound Review evidence (PR-REVIEW-EVIDENCE-620).

Saving a Review rating, disposition or inspection appends one record through ``LearningRecordWriter`` and never touches the image
file. The record names the image by the SHA-256 of its bytes (``artifact_sha256``); the path is only a locator. A file
whose bytes changed since it was reviewed is reported as changed rather than silently matched to the older rating.

This module is Tk-free. Reading scans the records file and hashing reads the image, so callers on the GUI thread should
use the existing Review image-context worker.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.learning.learning_record import (
    DISPOSITION_SOFT_SCORES,
    SITE_REVIEW_RECEIPT,
    LearningRecord,
    LearningRecordWriter,
)
from src.review.findings import Category, Certainty, Confirmation, Finding, Severity
from src.review.review_metadata_service import (
    INTERNAL_REVIEW_SUMMARY_SCHEMA,
    PortableReviewSummary,
    ReviewMetadataService,
    ReviewMetadataStampResult,
)
from src.utils.image_metadata import (
    extract_embedded_metadata,
    resolve_model_vae_fields,
    resolve_prompt_fields,
)

RATING_KIND = "review_tab_feedback"
RATING_SOURCE = "review_tab"
DISPOSITION_KIND = "review_disposition"
#: Distinct from ``RATING_SOURCE`` so rating listing and "Undo Last Save" never mistake a disposition for a rating.
DISPOSITION_SOURCE = "review_tab_disposition"
DISPOSITIONS = ("retain", "discard", "rework")
#: Written by Undo: the latest row for the bytes then says "no decision", so the image is to be reviewed again.
DISPOSITION_CLEARED = "cleared"
# ``DISPOSITION_SOFT_SCORES`` (retain 4.0, discard 2.0; owner decision 2026-11-17) lives in ``learning_record`` so the
# recommendation engine applies the same table. Re-work is not scored: it says the image needs more work, not whether
# its settings were good.

INSPECTION_KIND = "review_inspection"
#: Distinct from ``RATING_SOURCE`` and ``DISPOSITION_SOURCE``: rating listing, disposition lookup and "Undo Last Save"
#: never see an inspection.
INSPECTION_SOURCE = "review_tab_inspection"
INSPECTION_SCHEMA = "stablenew.review-inspection"
INSPECTION_SCHEMA_VERSION = 1
VERDICT_NO_DEFECT = "no_defect_seen"
VERDICT_DEFECTS = "defects_confirmed"
INSPECTION_VERDICTS = (VERDICT_NO_DEFECT, VERDICT_DEFECTS)
#: Written by Undo: the latest row for the bytes then says "no inspection", so nothing is exported for them.
INSPECTION_CLEARED = "cleared"
SUBJECT_COUNT_MIN = 1
SUBJECT_COUNT_MAX = 12
MAX_INSPECTION_FINDINGS = 24
_FINDING_KEYS = frozenset({"category", "region", "certainty", "severity"})

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


def revise_image_rating(
    path: Path, digest: str, score: int, notes: str, previous: Mapping[str, Any]
) -> LearningRecord:
    """Keep native Review context and advanced scores when editing the basic rating fields."""
    metadata = _section(previous.get("metadata"))
    image_metadata = _image_metadata(path)
    settings = _settings_from_image_metadata(image_metadata)
    prompt, negative = resolve_prompt_fields(image_metadata)
    subscores = _section(metadata.get("subscores"))
    basic_only = metadata.get("site_review_basic_rating") is True or not subscores
    feedback = {
        "image_path": path,
        "rating": score,
        "notes": notes,
        "source_job_id": metadata.get("source_job_id") or image_metadata.get("job_id"),
        "model": previous.get("primary_model") or settings.get("model"),
        "sampler": previous.get("primary_sampler") or settings.get("sampler"),
        "scheduler": previous.get("primary_scheduler") or settings.get("scheduler"),
        "steps": previous.get("primary_steps") or settings.get("steps"),
        "cfg_scale": previous.get("primary_cfg_scale") or settings.get("cfg_scale"),
        "stage": metadata.get("stage") or settings.get("stage"),
        **{
            field: metadata.get(field)
            for field in (
                "quality_label",
                "prompt_delta",
                "negative_prompt_delta",
                "prompt_mode",
                "negative_prompt_mode",
                "stages",
            )
        },
        "subscores": {} if basic_only else subscores,
        "base_prompt": metadata.get("prompt_before", prompt),
        "base_negative_prompt": metadata.get("negative_prompt_before", negative),
        "after_prompt": metadata.get("prompt_after"),
        "after_negative_prompt": metadata.get("negative_prompt_after"),
        "context": _section(metadata.get("review_context")),
    }
    record = build_review_rating_record(feedback, artifact_sha256=digest)
    if basic_only:
        record.metadata["site_review_basic_rating"] = True
    return record


def image_source_job(path: Path) -> str:
    return str(_image_metadata(path).get("job_id") or "").strip()


def _image_metadata(path: Path) -> dict[str, Any]:
    metadata = extract_embedded_metadata(path)
    return _section(metadata.payload) if metadata.status == "ok" else {}


def _section(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _generation_settings(path: str, digest: str, *, bytes_verified: bool) -> dict[str, Any]:
    """Model, sampler, scheduler, steps, CFG and stage read from the image's embedded metadata (``{}`` if unreadable).

    The settings describe the bytes, so they are read only from a file whose bytes are the reviewed ones: another file
    that now occupies the path (or no file at all) yields nothing rather than someone else's settings.
    """

    if not bytes_verified and file_sha256(path) != digest:
        return {}
    return _settings_from_image_metadata(_image_metadata(Path(path)))


def _settings_from_image_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = _section(payload.get("stage_manifest"))
    config = _section(manifest.get("config"))
    generation = _section(payload.get("generation"))
    model, _vae = resolve_model_vae_fields(payload)
    found = {
        "model": str(model or ""),
        "sampler": str(
            _first(
                config.get("sampler_name"),
                config.get("sampler"),
                manifest.get("sampler_name"),
                generation.get("sampler_name"),
            )
            or ""
        ),
        "scheduler": str(
            _first(config.get("scheduler"), manifest.get("scheduler"), generation.get("scheduler"))
            or ""
        ),
        "steps": _first(config.get("steps"), manifest.get("steps"), generation.get("steps")),
        "cfg_scale": _first(
            config.get("cfg_scale"), manifest.get("cfg_scale"), generation.get("cfg_scale")
        ),
        "stage": str(_first(manifest.get("stage"), payload.get("stage")) or ""),
    }
    return {key: value for key, value in found.items() if value not in (None, "")}


def build_disposition_record(
    *,
    image_path: str | os.PathLike[str],
    disposition: str,
    artifact_sha256: str | None = None,
    source_job_id: str = "",
    notes: str = "",
    known_settings: Mapping[str, Any] | None = None,
) -> LearningRecord:
    """Build a Retain / Discard / Re-work record bound to the image bytes (nothing is written or moved).

    A Retain or Discard also carries the generation settings read from those bytes and a soft ``user_rating``
    (``DISPOSITION_SOFT_SCORES``), which makes it observational Learning evidence. Re-work and the clearing row carry
    neither. ``known_settings`` are the settings already recorded for the same bytes; they are used only when the file
    cannot supply them, so a decision never depends on the file still being at ``image_path``.
    """

    value = str(disposition or "").strip().lower()
    if value not in (*DISPOSITIONS, DISPOSITION_CLEARED):
        raise ValueError(f"disposition must be one of {', '.join(DISPOSITIONS)}")
    path_text = str(image_path or "").strip()
    if not path_text:
        raise ValueError("image_path is required")
    supplied = normalize_digest(artifact_sha256)
    digest = supplied or (file_sha256(path_text) or "")
    if not digest:
        raise ValueError("The image could not be read, so its identity cannot be recorded.")
    metadata: dict[str, Any] = {
        "source": DISPOSITION_SOURCE,
        "record_kind": DISPOSITION_KIND,
        "image_path": path_text,
        "artifact_sha256": digest,
        "review_disposition": value,
        "user_notes": str(notes or ""),
        # Sub-second UTC time of the decision: the record's own timestamp has one-second resolution, which cannot
        # order a decision against a job queued within the same second.
        "decided_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="microseconds"),
    }
    if str(source_job_id or "").strip():
        metadata["source_job_id"] = str(source_job_id).strip()
    settings: dict[str, Any] = {}
    if value in DISPOSITION_SOFT_SCORES:
        settings = _generation_settings(path_text, digest, bytes_verified=not supplied) or {
            key: item for key, item in dict(known_settings or {}).items() if item not in (None, "")
        }
        metadata["user_rating"] = DISPOSITION_SOFT_SCORES[value]
        metadata["user_rating_source"] = "review_disposition_soft_score"
        if settings.get("stage"):
            metadata["stage"] = str(settings["stage"])

    def extract_primary(_cfg: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": settings.get("model", ""),
            "sampler": settings.get("sampler", ""),
            "scheduler": settings.get("scheduler", ""),
            "steps": settings.get("steps"),
            "cfg_scale": settings.get("cfg_scale"),
        }

    return LearningRecord.from_pipeline_context(
        base_config={},
        variant_configs=[],
        randomizer_mode="review_disposition",
        randomizer_plan_size=1,
        extract_primary=extract_primary if settings else None,
        metadata=metadata,
    )


def _has_settings(record: LearningRecord) -> bool:
    return bool(
        record.primary_sampler
        or record.primary_scheduler
        or record.primary_steps
        or record.primary_cfg_scale
    )


def _recorded_settings(records_path: Path, digest: str) -> dict[str, Any]:
    """The settings of the latest Retain / Discard already recorded for these bytes (``{}`` when there is none)."""

    found: dict[str, Any] = {}
    for payload in _iter_rows(records_path):
        metadata = payload["metadata"]
        if (
            metadata.get("source") != DISPOSITION_SOURCE
            or normalize_digest(metadata.get("artifact_sha256")) != digest
            or metadata.get("review_disposition") not in DISPOSITION_SOFT_SCORES
        ):
            continue
        settings = {
            "model": payload.get("primary_model"),
            "sampler": payload.get("primary_sampler"),
            "scheduler": payload.get("primary_scheduler"),
            "steps": payload.get("primary_steps") or None,
            "cfg_scale": payload.get("primary_cfg_scale") or None,
            "stage": metadata.get("stage"),
        }
        settings = {key: item for key, item in settings.items() if item not in (None, "")}
        if settings:
            found = settings
    return found


def build_disposition_with_prior_settings(records_path: Path, **kwargs: Any) -> LearningRecord:
    """Carry settings forward for the same digest when the image cannot supply them."""
    record = build_disposition_record(**kwargs)
    if record.metadata.get("review_disposition") in DISPOSITION_SOFT_SCORES and not _has_settings(
        record
    ):
        known = _recorded_settings(records_path, str(record.metadata["artifact_sha256"]))
        if known:
            record = build_disposition_record(**kwargs, known_settings=known)
    return record


def save_disposition(writer: LearningRecordWriter, **kwargs: Any) -> LearningRecord:
    """Append a disposition through the one writer; raises ``OSError`` when it was not confirmed saved."""
    record = build_disposition_with_prior_settings(writer.records_path, **kwargs)
    if writer.append_record(record) is False:
        raise OSError("The review decision was not confirmed saved; see the log before retrying.")
    return record


# -- inspection (AI-VL-243) ---------------------------------------------------------------------------------------


class InspectionRecordError(ValueError):
    """A stored or requested inspection that is not valid; ``code`` is a stable, content-free reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class InspectionFinding:
    """One operator-confirmed finding as stored: closed vocabulary only, never the observation text."""

    category: str
    region: tuple[int, int, int, int] | None
    certainty: str
    severity: str | None = None


@dataclass(frozen=True)
class InspectionRecord:
    """A validated inspection row. ``findings`` is empty unless ``verdict`` is ``defects_confirmed``."""

    digest: str
    verdict: str
    findings: tuple[InspectionFinding, ...] = ()
    subject_count: int | None = None
    reviewed_at: str = ""
    run_id: str = ""
    timestamp: str = ""
    #: A locator only; the digest is the identity.
    image_path: str = ""


@dataclass(frozen=True)
class InspectionDraft:
    """What the Inspect & Improve dialog asks Review to save: the image's identity, the verdict and the findings.

    The findings are the dialog's own ``Finding`` objects (observation text included); the builder keeps only the
    closed vocabulary.
    """

    image_path: str
    artifact_sha256: str
    image_size: tuple[int, int]
    verdict: str
    findings: tuple[Finding, ...] = ()
    subject_count: int | None = None


_CATEGORY_VALUES = frozenset(item.value for item in Category)
_CERTAINTY_VALUES = frozenset(item.value for item in Certainty)
_SEVERITY_VALUES = frozenset(item.value for item in Severity)

_REFUSAL_TEXT = {
    "finding_not_confirmed": "Only findings you confirmed can be saved in an inspection.",
    "clean_verdict_with_findings": "A no-defect inspection cannot carry findings.",
    "defects_verdict_without_findings": "Confirm at least one finding before saving defects.",
    "too_many_findings": f"Use at most {MAX_INSPECTION_FINDINGS} findings per inspection.",
    "malformed_subject_count": (
        f"Subjects in image must be a whole number from {SUBJECT_COUNT_MIN} to {SUBJECT_COUNT_MAX}."
    ),
}


def _region_of(value: Any) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(edge) is not int for edge in value)
    ):
        raise InspectionRecordError("malformed_region")
    left, top, right, bottom = value
    if not (0 <= left < right and 0 <= top < bottom):
        raise InspectionRecordError("malformed_region")
    return left, top, right, bottom


def _subject_count_of(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not SUBJECT_COUNT_MIN <= value <= SUBJECT_COUNT_MAX:
        raise InspectionRecordError("malformed_subject_count")
    return value


def _stored_finding(finding: Finding, image_size: tuple[int, int] | None) -> InspectionFinding:
    """Only a finding the operator confirmed is stored; an unconfirmed suggestion never reaches a record."""

    if finding.confirmation is not Confirmation.CONFIRMED:
        raise InspectionRecordError("finding_not_confirmed")
    region = finding.region
    if region is not None and image_size is not None:
        region.validate(image_size)
    return InspectionFinding(
        category=Category(finding.category).value,
        region=region.box if region is not None else None,
        certainty=Certainty(finding.certainty).value,
        severity=Severity(finding.severity).value if finding.severity is not None else None,
    )


def _inspection_record(
    *,
    image_path: str,
    digest: str,
    verdict: str,
    findings: list[dict[str, Any]],
    subject_count: int | None,
    source_job_id: str,
) -> LearningRecord:
    metadata: dict[str, Any] = {
        "source": INSPECTION_SOURCE,
        "record_kind": INSPECTION_KIND,
        "image_path": image_path,
        "artifact_sha256": digest,
        "inspection_schema": INSPECTION_SCHEMA,
        "inspection_schema_version": INSPECTION_SCHEMA_VERSION,
        "verdict": verdict,
        "findings": findings,
        "subject_count": subject_count,
        # Sub-second UTC time: the record's own timestamp has one-second resolution and cannot order two saves.
        "reviewed_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="microseconds"),
    }
    if str(source_job_id or "").strip():
        metadata["source_job_id"] = str(source_job_id).strip()
    return LearningRecord.from_pipeline_context(
        base_config={},
        variant_configs=[],
        randomizer_mode="review_inspection",
        randomizer_plan_size=1,
        metadata=metadata,
    )


def _inspection_target(
    image_path: str | os.PathLike[str], artifact_sha256: str | None
) -> tuple[str, str]:
    path_text = str(image_path or "").strip()
    if not path_text:
        raise ValueError("image_path is required")
    digest = normalize_digest(artifact_sha256) or (file_sha256(path_text) or "")
    if not digest:
        raise ValueError("The image could not be read, so its identity cannot be recorded.")
    return path_text, digest


def build_inspection_record(
    *,
    image_path: str | os.PathLike[str],
    verdict: str,
    findings: Sequence[Finding] = (),
    subject_count: int | None = None,
    artifact_sha256: str | None = None,
    image_size: tuple[int, int] | None = None,
    source_job_id: str = "",
) -> LearningRecord:
    """Build a ``review_inspection`` record bound to the image bytes (nothing is written or changed).

    ``no_defect_seen`` takes no findings; ``defects_confirmed`` needs at least one finding the operator confirmed.
    Only category, region, certainty and optional severity of each finding are stored: the observation text, the
    origin and any suggestion label stay in the dialog. ``subject_count`` is 1-12 or ``None`` ("not recorded").
    Two findings with the same category and region are stored once.
    """

    value = str(verdict or "").strip().lower()
    if value not in INSPECTION_VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(INSPECTION_VERDICTS)}")
    path_text, digest = _inspection_target(image_path, artifact_sha256)
    try:
        stored: list[InspectionFinding] = []
        for finding in findings:
            item = _stored_finding(finding, image_size)
            if not any(
                (old.category, old.region) == (item.category, item.region) for old in stored
            ):
                stored.append(item)
        if len(stored) > MAX_INSPECTION_FINDINGS:
            raise InspectionRecordError("too_many_findings")
        if value == VERDICT_NO_DEFECT and stored:
            raise InspectionRecordError("clean_verdict_with_findings")
        if value == VERDICT_DEFECTS and not stored:
            raise InspectionRecordError("defects_verdict_without_findings")
        count = _subject_count_of(subject_count)
    except InspectionRecordError as exc:
        raise ValueError(_REFUSAL_TEXT.get(exc.code, "The inspection is not valid.")) from exc
    return _inspection_record(
        image_path=path_text,
        digest=digest,
        verdict=value,
        findings=[
            {
                "category": item.category,
                "region": list(item.region) if item.region is not None else None,
                "certainty": item.certainty,
                "severity": item.severity,
            }
            for item in stored
        ],
        subject_count=count,
        source_job_id=source_job_id,
    )


def build_inspection_cleared_record(
    *,
    image_path: str | os.PathLike[str],
    artifact_sha256: str | None = None,
    source_job_id: str = "",
) -> LearningRecord:
    """The row Undo writes: the latest inspection for these bytes then says "none" (nothing is deleted)."""

    path_text, digest = _inspection_target(image_path, artifact_sha256)
    return _inspection_record(
        image_path=path_text,
        digest=digest,
        verdict=INSPECTION_CLEARED,
        findings=[],
        subject_count=None,
        source_job_id=source_job_id,
    )


def save_inspection(writer: LearningRecordWriter, **kwargs: Any) -> LearningRecord:
    """Append an inspection through the one writer; raises ``OSError`` when it was not confirmed saved."""

    record = build_inspection_record(**kwargs)
    if writer.append_record(record) is False:
        raise OSError("The inspection was not confirmed saved; see the log before retrying.")
    return record


def clear_inspection(writer: LearningRecordWriter, **kwargs: Any) -> LearningRecord:
    """Append the clearing row (Undo of a saved inspection); raises ``OSError`` when it was not confirmed saved."""

    record = build_inspection_cleared_record(**kwargs)
    if writer.append_record(record) is False:
        raise OSError("The inspection was not confirmed cleared; see the log before retrying.")
    return record


def parse_inspection_row(row: Mapping[str, Any]) -> InspectionRecord:
    """Validate a stored ``review_inspection`` row; raises :class:`InspectionRecordError` with a stable code.

    Closed vocabulary only: a finding with any key besides category, region, certainty and severity (an observation,
    for example) is refused, so free text can never be read back as a label.
    """

    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("record_kind") != INSPECTION_KIND:
        raise InspectionRecordError("not_an_inspection")
    if (
        metadata.get("inspection_schema") != INSPECTION_SCHEMA
        or metadata.get("inspection_schema_version") != INSPECTION_SCHEMA_VERSION
    ):
        raise InspectionRecordError("unknown_inspection_schema")
    digest = normalize_digest(metadata.get("artifact_sha256"))
    if not digest:
        raise InspectionRecordError("malformed_digest")
    verdict = metadata.get("verdict")
    if verdict not in (*INSPECTION_VERDICTS, INSPECTION_CLEARED):
        raise InspectionRecordError("malformed_verdict")
    raw = metadata.get("findings")
    if not isinstance(raw, list) or len(raw) > MAX_INSPECTION_FINDINGS:
        raise InspectionRecordError("malformed_findings")
    stored: list[InspectionFinding] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or set(entry) != _FINDING_KEYS:
            raise InspectionRecordError("malformed_findings")
        severity = entry["severity"]
        if (
            entry["category"] not in _CATEGORY_VALUES
            or entry["certainty"] not in _CERTAINTY_VALUES
            or (severity is not None and severity not in _SEVERITY_VALUES)
        ):
            raise InspectionRecordError("malformed_findings")
        stored.append(
            InspectionFinding(
                entry["category"], _region_of(entry["region"]), entry["certainty"], severity
            )
        )
    if (verdict == VERDICT_DEFECTS) != bool(stored):
        raise InspectionRecordError("verdict_does_not_match_findings")
    count = _subject_count_of(metadata.get("subject_count"))
    if verdict == INSPECTION_CLEARED and count is not None:
        raise InspectionRecordError("malformed_subject_count")
    return InspectionRecord(
        digest=digest,
        verdict=str(verdict),
        findings=tuple(stored),
        subject_count=count,
        reviewed_at=str(metadata.get("reviewed_at") or ""),
        run_id=str(row.get("run_id") or ""),
        timestamp=str(row.get("timestamp") or ""),
        image_path=str(metadata.get("image_path") or ""),
    )


@dataclass(frozen=True)
class InspectionLookup:
    """The latest inspection for an image.

    ``record`` is ``None`` when none is saved, it was cleared, its bytes changed, or the row is malformed.
    ``malformed`` says the latest row for these bytes could not be read as an inspection (an earlier row never
    replaces it). ``identity`` is ``digest``, ``path`` or ``changed``; a ``changed`` row is reported, never applied.
    """

    record: InspectionRecord | None = None
    identity: str = ""
    malformed: bool = False

    @property
    def verdict(self) -> str:
        return self.record.verdict if self.record is not None else ""


def _inspection_of(found: EvidenceLookup) -> InspectionLookup:
    if found.row is None:
        return InspectionLookup()
    if found.identity == IDENTITY_CHANGED:
        return InspectionLookup(identity=IDENTITY_CHANGED)
    try:
        record = parse_inspection_row(found.row)
    except InspectionRecordError:
        return InspectionLookup(identity=found.identity, malformed=True)
    if record.verdict == INSPECTION_CLEARED:
        return InspectionLookup(identity=found.identity)
    return InspectionLookup(record=record, identity=found.identity)


def lookup_inspection(
    records_path: str | os.PathLike[str],
    image_path: str | os.PathLike[str],
    artifact_sha256: str | None,
) -> InspectionLookup:
    """Latest inspection for the bytes (digest first, then path); the latest row wins, a cleared row means none."""

    return _inspection_of(
        _lookup(Path(records_path), INSPECTION_SOURCE, str(image_path), artifact_sha256)
    )


def _iter_rows(records_path: Path, *, strict_io: bool = False) -> Iterator[dict[str, Any]]:
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
    except FileNotFoundError:
        return
    except OSError:
        if strict_io:
            raise


@dataclass(frozen=True)
class EvidenceLookup:
    """The latest row for an image and how it was matched; ``row`` is the stored record payload."""

    row: dict[str, Any] | None = None
    identity: str = ""


def _path_key(value: Any) -> str:
    text = str(value or "").strip()
    return os.path.normcase(str(Path(text))) if text else ""


def _pick(
    by_digest: dict[str, Any] | None, by_path: dict[str, Any] | None, digest: str
) -> EvidenceLookup:
    """Digest match first, then path; a path row recorded for different bytes is reported as changed."""

    if by_digest is not None:
        return EvidenceLookup(by_digest, IDENTITY_DIGEST)
    if by_path is None:
        return EvidenceLookup()
    recorded = normalize_digest(by_path["metadata"].get("artifact_sha256"))
    if digest and recorded and recorded != digest:
        return EvidenceLookup(by_path, IDENTITY_CHANGED)
    return EvidenceLookup(by_path, IDENTITY_PATH)


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
    return _pick(by_digest, by_path, digest)


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
    #: Sub-second UTC time of the decision when it was recorded (empty for older rows; use ``timestamp`` then).
    decided_at: str = ""


def lookup_disposition(
    records_path: str | os.PathLike[str],
    image_path: str | os.PathLike[str],
    artifact_sha256: str | None,
) -> DispositionLookup:
    """Latest Retain / Discard / Re-work for the bytes (digest first, then path); latest row wins.

    A decision recorded for different bytes is reported with ``identity="changed"`` and is not applied.
    """

    return _disposition_of(
        _lookup(Path(records_path), DISPOSITION_SOURCE, str(image_path), artifact_sha256)
    )


def _disposition_of(found: EvidenceLookup) -> DispositionLookup:
    if found.row is None:
        return DispositionLookup()
    metadata = found.row["metadata"]
    value = str(metadata.get("review_disposition") or "")
    return DispositionLookup(
        disposition=value if value in DISPOSITIONS else "",
        identity=found.identity,
        timestamp=str(found.row.get("timestamp") or ""),
        run_id=str(found.row.get("run_id") or ""),
        decided_at=str(metadata.get("decided_at") or ""),
    )


class EvidenceIndex:
    """One pass over the records file: the latest rating and disposition row by digest and by path.

    Opening a set of images asks the same question for every image, so the file is read once rather than once per
    image. ``rating`` and ``disposition`` answer exactly as ``lookup_rating`` and ``lookup_disposition`` do.
    """

    def __init__(self) -> None:
        self._by_digest: dict[str, dict[str, dict[str, Any]]] = {
            RATING_SOURCE: {},
            DISPOSITION_SOURCE: {},
            INSPECTION_SOURCE: {},
        }
        self._by_path: dict[str, dict[str, dict[str, Any]]] = {
            RATING_SOURCE: {},
            DISPOSITION_SOURCE: {},
            INSPECTION_SOURCE: {},
        }
        #: Inspection rows that name no readable digest: they cannot be bound to any bytes.
        self.unbound_inspections = 0
        self.operation_receipts: list[dict[str, Any]] = []

    @classmethod
    def read(
        cls,
        records_path: str | os.PathLike[str] | None,
        *,
        strict_io: bool = False,
        operation: str | None = None,
    ) -> EvidenceIndex:
        index = cls()
        if records_path is None:
            return index
        for payload in _iter_rows(Path(records_path), strict_io=strict_io):
            metadata = payload["metadata"]
            receipt = metadata.get(SITE_REVIEW_RECEIPT)
            if (
                operation is not None
                and isinstance(receipt, dict)
                and receipt.get("operation") == operation
            ):
                index.operation_receipts.append(receipt)
            source = metadata.get("source")
            if not isinstance(source, str) or source not in index._by_digest:
                continue
            recorded = normalize_digest(metadata.get("artifact_sha256"))
            if source == INSPECTION_SOURCE and not recorded:
                index.unbound_inspections += 1
            if recorded:
                index._by_digest[source][recorded] = payload
            key = _path_key(metadata.get("image_path"))
            if key:
                index._by_path[source][key] = payload
        return index

    def _find(self, source: str, image_path: Any, artifact_sha256: str | None) -> EvidenceLookup:
        digest = normalize_digest(artifact_sha256)
        return _pick(
            self._by_digest[source].get(digest) if digest else None,
            self._by_path[source].get(_path_key(image_path)),
            digest,
        )

    def rating(self, image_path: Any, artifact_sha256: str | None) -> EvidenceLookup:
        return self._find(RATING_SOURCE, image_path, artifact_sha256)

    def disposition(self, image_path: Any, artifact_sha256: str | None) -> DispositionLookup:
        return _disposition_of(self._find(DISPOSITION_SOURCE, image_path, artifact_sha256))

    def disposition_evidence(self, image_path: Any, artifact_sha256: str | None) -> EvidenceLookup:
        return self._find(DISPOSITION_SOURCE, image_path, artifact_sha256)

    def inspection(self, image_path: Any, artifact_sha256: str | None) -> InspectionLookup:
        return _inspection_of(self._find(INSPECTION_SOURCE, image_path, artifact_sha256))

    def inspection_rows(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """``(digest, latest stored row)`` for every digest that has an inspection row, in digest order.

        The row is the raw payload: pass it to :func:`parse_inspection_row`, which says why a row is not usable.
        """

        yield from sorted(self._by_digest[INSPECTION_SOURCE].items())

    def discard_digest(self, image_path: Any) -> str:
        """The digest of the bytes the latest decision for this path discarded ("" when it is not a Discard)."""

        payload = self._by_path[DISPOSITION_SOURCE].get(_path_key(image_path))
        if payload is None:
            return ""
        metadata = payload["metadata"]
        if str(metadata.get("review_disposition") or "") != "discard":
            return ""
        return normalize_digest(metadata.get("artifact_sha256"))

    def discarded(self) -> list[tuple[str, str]]:
        """``(image path, digest)`` of every image whose latest decision (by path) is Discard.

        Used to list archived images from their records when the file is no longer where it was reviewed.
        """

        found: list[tuple[str, str]] = []
        for payload in self._by_path[DISPOSITION_SOURCE].values():
            metadata = payload["metadata"]
            if str(metadata.get("review_disposition") or "") != "discard":
                continue
            path = str(metadata.get("image_path") or "").strip()
            if path:
                found.append((path, normalize_digest(metadata.get("artifact_sha256"))))
        return found


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
    "DISPOSITION_CLEARED",
    "DISPOSITION_KIND",
    "DISPOSITION_SOFT_SCORES",
    "DISPOSITION_SOURCE",
    "DispositionLookup",
    "EvidenceIndex",
    "EvidenceLookup",
    "IDENTITY_CHANGED",
    "IDENTITY_DIGEST",
    "IDENTITY_PATH",
    "INSPECTION_CLEARED",
    "INSPECTION_KIND",
    "INSPECTION_SCHEMA",
    "INSPECTION_SCHEMA_VERSION",
    "INSPECTION_SOURCE",
    "INSPECTION_VERDICTS",
    "InspectionDraft",
    "InspectionFinding",
    "InspectionLookup",
    "InspectionRecord",
    "InspectionRecordError",
    "MAX_INSPECTION_FINDINGS",
    "RATING_KIND",
    "RATING_SOURCE",
    "SUBJECT_COUNT_MAX",
    "SUBJECT_COUNT_MIN",
    "VERDICT_DEFECTS",
    "VERDICT_NO_DEFECT",
    "build_disposition_record",
    "build_inspection_cleared_record",
    "build_inspection_record",
    "build_review_rating_record",
    "clear_inspection",
    "file_sha256",
    "lookup_disposition",
    "lookup_inspection",
    "lookup_rating",
    "normalize_digest",
    "parse_inspection_row",
    "resolve_prior_review_summary",
    "save_disposition",
    "save_inspection",
    "summary_from_row",
    "write_rating_into_file",
]
