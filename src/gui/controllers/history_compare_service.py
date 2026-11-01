"""Read-only "Compare with Parent" (PR-HISTORY-610B): resolve and assess ONE direct parent/child pair.

The selected child's frozen ``source.parent_job_id`` is the only relationship authority. Both jobs are re-read from the
canonical repository by id (never trusted from a table row), their frozen NJRs are hydrated and identity-checked, the
persisted lineage projection must agree, and each side must have exactly one eligible recorded still image. Nothing is
inferred from names, prompts, timestamps or folders; nothing is written; nothing is queued.

``prepare`` does blocking SQLite, hashing and decoding work: call it on a worker, never on the Tk thread.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.gui.view_contracts.history_comparison_artifact import VerifiedImage, verify_image
from src.gui_v2.history_compare_model import (
    ComparisonRefused,
    FieldDifference,
    RecordedJob,
    lineage_kind,
    merge_differences,
    observed_differences,
    parent_artifact_claim,
    recipe_differences,
    recipe_limitations,
    recorded_job,
    recorded_parent_id,
    verify_direct_lineage,
)
from src.queue.job_history_store import JobHistoryEntry

_SHA256_CLAIM = re.compile(r"^sha256:([0-9a-fA-F]{64})$")

PARENT_PIXELS_VERIFIED = (
    "Parent image verified: its bytes match the digest the child recorded for its source."
)
PARENT_PIXELS_UNVERIFIED = (
    "Parent artifact identity is not independently verified: the child records its parent job but no "
    "verifiable parent-image digest, so the parent's pixels are not proven to be what the child was made from."
)


@dataclass(frozen=True)
class ComparisonSide:
    entry: JobHistoryEntry
    job: RecordedJob
    image: VerifiedImage
    visibility_subject: dict[str, Any]


@dataclass(frozen=True)
class Comparison:
    parent: ComparisonSide
    child: ComparisonSide
    relationship: str
    parent_artifact_verified: bool
    identity_note: str
    differences: tuple[FieldDifference, ...]
    limitations: tuple[str, ...]


def resolve_history_repository(controller: Any) -> Any | None:
    """The canonical repository reached the way the main window and Browse All reach it, or ``None``."""

    repository = getattr(getattr(controller, "job_service", None), "history_store", None)
    if callable(getattr(repository, "get_job", None)) and callable(
        getattr(repository, "get_lineage", None)
    ):
        return repository
    return None


def has_recorded_parent(entry: Any) -> bool:
    """Cheap, cached-row gate for the button only; ``prepare`` re-reads everything before showing anything."""

    snapshot = getattr(entry, "snapshot", None)
    record = snapshot.get("normalized_job") if isinstance(snapshot, dict) else None
    status = getattr(entry, "status", None)
    return bool(
        isinstance(record, dict)
        and recorded_parent_id(record)
        and str(getattr(status, "value", status)) == "completed"
    )


def _text_leaves(value: Any, out: list[str], depth: int = 0) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict) and depth < 6:
        for item in value.values():
            _text_leaves(item, out, depth + 1)
    elif isinstance(value, (list, tuple)) and depth < 6:
        for item in value:
            _text_leaves(item, out, depth + 1)


def _subject(entry: JobHistoryEntry, job: RecordedJob) -> dict[str, Any]:
    """What the content-visibility policy judges for this side: the prompts plus every other frozen text.

    Prompts alone are not enough: a frozen config or prompt-info string can carry the restricted words while the outer
    prompts are clean, and a restricted job must hide its image and its displayed values together.
    """

    texts: list[str] = []
    workload = job.record.get("workload")
    provenance = job.record.get("provenance")
    _text_leaves(workload.get("config") if isinstance(workload, dict) else None, texts)
    for key in ("txt2img_prompt_info", "img2img_prompt_info"):
        _text_leaves(provenance.get(key) if isinstance(provenance, dict) else None, texts)
    return {
        "name": entry.payload_summary,
        "positive_prompt": job.njr.positive_prompt,
        "negative_prompt": job.njr.negative_prompt,
        "prompt": " ".join(texts)[:20000],
    }


class HistoryCompareService:
    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def _read(self, job_id: str) -> JobHistoryEntry | None:
        try:
            return self._repository.get_job(job_id)
        except Exception as exc:  # noqa: BLE001 - an unreadable store is a visible, content-safe refusal
            raise ComparisonRefused("History could not be read.") from exc

    def prepare(self, child_id: str) -> Comparison:
        if not child_id:
            raise ComparisonRefused("No job is selected.")
        child_entry = self._read(child_id)
        child = recorded_job(child_entry, role="selected")
        parent_id = recorded_parent_id(child.record)
        if not parent_id:
            raise ComparisonRefused("This job has no recorded parent to compare with.")
        parent_entry = self._read(parent_id)
        parent = recorded_job(parent_entry, role="parent")
        assert child_entry is not None and parent_entry is not None  # recorded_job refused None
        try:
            persisted = self._repository.get_lineage(child_id)
        except Exception as exc:  # noqa: BLE001
            raise ComparisonRefused("History could not be read.") from exc
        verify_direct_lineage(parent, child, persisted)

        parent_image = verify_image(parent_entry)
        child_image = verify_image(child_entry)
        claim = parent_artifact_claim(child.record)
        match = _SHA256_CLAIM.match(claim)
        if match and match.group(1).lower() != parent_image.sha256:
            raise ComparisonRefused(
                "The child's parent-artifact claim does not match the parent image."
            )
        verified = bool(match)

        frozen = recipe_differences(parent.record, child.record)
        observed = observed_differences(
            parent_entry.result, child_entry.result, parent_image.size, child_image.size
        )
        rows = merge_differences(frozen, observed)
        limitations = recipe_limitations(
            parent, child, rows, truncated=len(rows) < len(frozen) + len(observed)
        )
        if not verified:
            limitations.append(
                "No SHA-256 parent-artifact claim was recorded."
                if not claim
                else "The recorded parent-artifact claim is not a SHA-256 digest this viewer can check."
            )
        if not (parent_image.historical_hash and child_image.historical_hash):
            limitations.append(
                "A historical output hash was not recorded for both images; the current file bytes are "
                "verified for this viewing only."
            )
        return Comparison(
            parent=ComparisonSide(
                parent_entry, parent, parent_image, _subject(parent_entry, parent)
            ),
            child=ComparisonSide(child_entry, child, child_image, _subject(child_entry, child)),
            relationship=lineage_kind(child.record),
            parent_artifact_verified=verified,
            identity_note=PARENT_PIXELS_VERIFIED if verified else PARENT_PIXELS_UNVERIFIED,
            differences=rows,
            limitations=tuple(limitations),
        )


__all__ = [
    "Comparison",
    "ComparisonSide",
    "HistoryCompareService",
    "has_recorded_parent",
    "resolve_history_repository",
]
