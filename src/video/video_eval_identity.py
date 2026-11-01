"""Source-image, clip and job identity for eval reports (PR-VID-QUALITY-351).

Three questions are answered here from recorded facts only, never from filenames or nearby files:

* **Is the source image still the one the suite was admitted with?** The recorded path is hashed and
  compared with the run manifest's ``image_sha256``; a missing or changed file is reported, and no
  replacement is searched for.
* **Which bytes is a clip?** ``hash_artifact`` is a bounded, cancellable SHA-256 of the recorded clip.
* **Do two arms really share a case?** ``verify_cell_identity`` compares what each stored NJR recorded
  (job id, backend, seed, source image, and the prompt where the backend records one) with the run
  manifest. Workflow-specific settings may differ between arms and are not compared.

Everything is read-only. Nothing submits a job, starts a runtime or loads a model.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.pipeline.njr_core_v26 import thaw_json
from src.utils.snapshot_builder_v2 import normalized_job_from_snapshot

MAX_ARTIFACT_BYTES = 8 * 1024**3
MAX_SOURCE_BYTES = 64 * 1024**2
_CHUNK = 1024 * 1024
#: Only these file types are ever offered to the browser as the source image.
SOURCE_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})

BACKEND_WORKFLOW = "video_workflow"
BACKEND_SVD = "svd_native"


class EvalCancelled(RuntimeError):
    """Hashing was cancelled by the caller."""


class ArtifactUnhashable(RuntimeError):
    """The file is unreadable or too large to bind a review to."""


def hash_artifact(
    path: str | Path,
    *,
    cancel: threading.Event | None = None,
    max_bytes: int = MAX_ARTIFACT_BYTES,
) -> tuple[str, int]:
    """``(sha256 hex, size)`` read in bounded chunks. Raises ``ArtifactUnhashable`` or ``EvalCancelled``."""

    target = Path(path)
    try:
        size = target.stat().st_size
        if size > max_bytes:
            raise ArtifactUnhashable(f"{target.name} is larger than {max_bytes // 1024**2} MiB")
        digest = hashlib.sha256()
        total = 0
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                if cancel is not None and cancel.is_set():
                    raise EvalCancelled("hashing was cancelled")
                total += len(chunk)
                if total > max_bytes:
                    raise ArtifactUnhashable(f"{target.name} grew past {max_bytes // 1024**2} MiB")
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactUnhashable(f"{target.name} cannot be read: {exc}") from exc
    return digest.hexdigest(), total


class SourceStatus(str, Enum):
    VERIFIED = "verified"
    MISSING = "missing"
    MISMATCH = "mismatch"
    UNPINNED = "unpinned"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SourceReference:
    case_id: str
    status: SourceStatus
    message: str
    path: str = ""
    claimed_sha256: str = ""
    current_sha256: str = ""

    @property
    def displayable(self) -> bool:
        return self.status is SourceStatus.VERIFIED


def verify_source(
    case: Mapping[str, Any], *, cancel: threading.Event | None = None
) -> SourceReference:
    """Check one manifest case's source image against its recorded digest."""

    case_id = str(case.get("case_id", ""))
    raw_path = case.get("image")
    claimed = str(case.get("image_sha256") or "").strip().lower()
    if not isinstance(raw_path, str) or not raw_path.strip():
        return SourceReference(
            case_id, SourceStatus.MISSING, "The run manifest records no source image."
        )
    path = Path(raw_path)
    if not path.is_absolute():
        return SourceReference(
            case_id,
            SourceStatus.MISSING,
            "The recorded source image path is not absolute, so it is not searched for.",
            raw_path,
            claimed,
        )
    if path.suffix.lower() not in SOURCE_IMAGE_SUFFIXES:
        return SourceReference(
            case_id,
            SourceStatus.UNSUPPORTED,
            "The source file is not a supported image type.",
            raw_path,
            claimed,
        )
    if not path.is_file():
        return SourceReference(
            case_id, SourceStatus.MISSING, "The source image is missing.", raw_path, claimed
        )
    if not claimed:
        return SourceReference(
            case_id,
            SourceStatus.UNPINNED,
            "The run manifest records no digest for the source image, so it cannot be verified.",
            raw_path,
        )
    try:
        current, _size = hash_artifact(path, cancel=cancel, max_bytes=MAX_SOURCE_BYTES)
    except ArtifactUnhashable as exc:
        return SourceReference(
            case_id,
            SourceStatus.MISSING,
            f"The source image is unavailable: {exc}",
            raw_path,
            claimed,
        )
    if current != claimed:
        return SourceReference(
            case_id,
            SourceStatus.MISMATCH,
            "The file at the recorded path is not the image the suite was admitted with.",
            raw_path,
            claimed,
            current,
        )
    return SourceReference(
        case_id, SourceStatus.VERIFIED, "Matches the recorded digest.", raw_path, claimed, current
    )


@dataclass(frozen=True)
class JobFacts:
    """What a stored NJR recorded about itself; ``None`` fields were not recorded."""

    job_id: str
    backend: str | None
    seed: int | None
    source_image: str | None
    prompt: str | None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_job_facts(snapshot: Mapping[str, Any] | None) -> JobFacts | None:
    """Facts from a repository snapshot, or ``None`` when it holds no readable NJR."""

    if not isinstance(snapshot, Mapping):
        return None
    try:
        njr = normalized_job_from_snapshot(snapshot)
        if njr is None:
            return None
        config = thaw_json(njr.config)
        first_input = str(njr.input_image_paths[0]) if njr.input_image_paths else None
        block = config.get("video_workflow") if isinstance(config, Mapping) else None
        if isinstance(block, Mapping) and block.get("workflow_id"):
            preparation = block.get("source_preparation")
            original = (
                preparation.get("original_source_path")
                if isinstance(preparation, Mapping)
                else None
            )
            return JobFacts(
                job_id=str(njr.job_id),
                backend=BACKEND_WORKFLOW,
                seed=_int_or_none(block.get("seed")),
                source_image=str(original) if original else first_input,
                prompt=str(block.get("prompt")) if block.get("prompt") is not None else None,
            )
        svd = config.get("svd_native") if isinstance(config, Mapping) else None
        if isinstance(svd, Mapping):
            inference = svd.get("inference")
            return JobFacts(
                job_id=str(njr.job_id),
                backend=BACKEND_SVD,
                seed=_int_or_none(inference.get("seed"))
                if isinstance(inference, Mapping)
                else None,
                source_image=first_input,
                prompt=None,
            )
        return JobFacts(str(njr.job_id), None, None, first_input, None)
    except Exception:  # noqa: BLE001 - a stored row that cannot be read is simply "not verified"
        return None


class Comparability(str, Enum):
    VERIFIED = "verified"
    NOT_FULLY_VERIFIED = "not_fully_verified"
    INCOMPARABLE = "incomparable"


@dataclass(frozen=True)
class CellIdentity:
    status: Comparability
    findings: tuple[str, ...] = ()


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def verify_cell_identity(
    *,
    facts: JobFacts | None,
    job: Mapping[str, Any],
    case: Mapping[str, Any],
    arm: Mapping[str, Any],
    suite_seed: Any,
    source: SourceReference | None,
) -> CellIdentity:
    """Does this job's stored NJR agree with the manifest's case, arm, seed and job identity?"""

    contradictions: list[str] = []
    unverified: list[str] = []
    if source is not None and source.status is SourceStatus.MISMATCH:
        contradictions.append("the source image changed since the suite was admitted")
    elif source is not None and not source.displayable:
        unverified.append(f"source image not verified ({source.status.value})")

    manifest_seed = _int_or_none(job.get("seed"))
    if (
        manifest_seed is not None
        and _int_or_none(suite_seed) is not None
        and manifest_seed != suite_seed
    ):
        contradictions.append(
            f"the manifest records seed {manifest_seed}, not the suite seed {suite_seed}"
        )

    if facts is None:
        unverified.append("the stored job snapshot is unavailable")
        return CellIdentity(
            Comparability.INCOMPARABLE if contradictions else Comparability.NOT_FULLY_VERIFIED,
            tuple(contradictions + unverified),
        )

    if facts.job_id != str(job.get("job_id")):
        contradictions.append(f"the stored job is {facts.job_id}, not {job.get('job_id')}")
    expected_backend = str(arm.get("backend") or "")
    if facts.backend is None:
        unverified.append("the stored job records no recognised backend")
    elif facts.backend != expected_backend:
        contradictions.append(
            f"the stored job used {facts.backend}, but the arm is {expected_backend}"
        )
    if facts.seed is None:
        unverified.append("the stored job records no seed")
    elif manifest_seed is not None and facts.seed != manifest_seed:
        contradictions.append(f"the stored job used seed {facts.seed}, not {manifest_seed}")
    if not facts.source_image:
        unverified.append("the stored job records no source image")
    elif not _same_path(facts.source_image, str(case.get("image") or "")):
        contradictions.append("the stored job used a different source image than the case")
    if facts.backend == BACKEND_WORKFLOW:
        if facts.prompt is None:
            unverified.append("the stored job records no prompt")
        elif facts.prompt != str(case.get("prompt") or ""):
            contradictions.append("the stored job used a different prompt than the case")

    if contradictions:
        return CellIdentity(Comparability.INCOMPARABLE, tuple(contradictions + unverified))
    if unverified:
        return CellIdentity(Comparability.NOT_FULLY_VERIFIED, tuple(unverified))
    return CellIdentity(Comparability.VERIFIED)


__all__ = [
    "BACKEND_SVD",
    "BACKEND_WORKFLOW",
    "ArtifactUnhashable",
    "CellIdentity",
    "Comparability",
    "EvalCancelled",
    "JobFacts",
    "SourceReference",
    "SourceStatus",
    "hash_artifact",
    "read_job_facts",
    "verify_cell_identity",
    "verify_source",
]
