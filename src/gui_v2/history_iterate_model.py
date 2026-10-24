"""Toolkit-neutral eligibility for "Iterate from History" (PR-HISTORY-610A).

One pure projection of a persisted history record decides the two deliberate choices: Edit Image in Review (the recorded
pixels become the input of a new reprocess task) and Regenerate with Changes in Pipeline (an editable txt2img draft of the
frozen recipe). It reads only the canonical record handed to it plus the existence of the recorded file; it never scans
directories, decodes images, reads a PromptPack or touches a backend. Reasons never contain prompt text, so they are safe
under every content-visibility mode.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.gui.view_contracts.history_artifact_contract import resolve_single_still_image
from src.pipeline.history_variation_compiler import variation_refusals
from src.pipeline.job_models_v2 import NormalizedJobRecord, WorkloadKind
from src.queue.batch_membership import ACTIVE_BATCH_KEYS
from src.queue.job_model import JobStatus

REVIEW_SUMMARY = (
    "Opens this exact image in Review as the input of a new image-to-image/reprocess task. "
    "You choose the stages and see the preview first; nothing is queued until you confirm there."
)
PIPELINE_SUMMARY = (
    "Opens an editable text-to-image draft of this job's recipe (prompt, negative prompt, seed, steps, CFG). "
    "The old image is not used as an input. Nothing is queued until you confirm the Preview."
)


@dataclass(frozen=True)
class IterateChoice:
    supported: bool
    summary: str
    reason: str = ""


@dataclass(frozen=True)
class IterateAssessment:
    job_id: str
    review: IterateChoice
    pipeline: IterateChoice
    image_path: str | None = None
    njr: NormalizedJobRecord | None = None
    #: The seed the backend actually used (``-1`` requests are random); a hint only, never applied silently.
    recorded_seed: int | None = None

    @property
    def any_supported(self) -> bool:
        return self.review.supported or self.pipeline.supported


def _blocked(summary: str, reason: str) -> IterateChoice:
    return IterateChoice(False, summary, reason)


def _both_blocked(job_id: str, reason: str) -> IterateAssessment:
    return IterateAssessment(
        job_id, _blocked(REVIEW_SUMMARY, reason), _blocked(PIPELINE_SUMMARY, reason)
    )


def _status_value(entry: Any) -> str:
    status = getattr(entry, "status", None)
    return str(getattr(status, "value", status) or "")


def _common_refusal(njr: NormalizedJobRecord) -> str:
    if njr.workload_kind is not WorkloadKind.IMAGE:
        return f"Only still-image jobs can be iterated (this is a {njr.workload_kind.value} job)."
    if njr.stage_chain_labels != ["txt2img"]:
        return (
            "Only single-stage text-to-image jobs are supported "
            f"(this job enabled: {', '.join(njr.stage_chain_labels) or 'nothing'})."
        )
    if njr.input_image_paths:
        return "This job already used a source image (an edit), which is not supported here yet."
    if njr.images_per_prompt != 1 or njr.loop_count != 1:
        return "Multi-image or looped jobs are not supported."
    if njr.provenance.variant_total != 1 or njr.provenance.batch_total != 1:
        return "This job is one member of a multi-variant or batch run."
    if any(key in njr.extra_metadata for key in ACTIVE_BATCH_KEYS):
        return "This job belongs to a grouped batch."
    return ""


def assess_history_iterate(
    entry: Any,
    *,
    is_file: Callable[[str], bool] = os.path.isfile,
    hydrate: Callable[[Mapping[str, Any] | None], NormalizedJobRecord | None] | None = None,
) -> IterateAssessment:
    """Assess one persisted ``JobHistoryEntry`` (or look-alike). Pure; never raises for a bad record."""

    if entry is None:
        return _both_blocked("", "The history record is no longer available.")
    job_id = str(getattr(entry, "job_id", "") or "")
    if _status_value(entry) != JobStatus.COMPLETED.value:
        return _both_blocked(job_id, "Only completed jobs that produced an image can be iterated.")
    snapshot = getattr(entry, "snapshot", None)
    if not isinstance(snapshot, Mapping) or not snapshot:
        return _both_blocked(
            job_id, "This record has no stored job snapshot (legacy or incomplete)."
        )
    try:
        njr = (hydrate or HistoryHandoffService().hydrate_njr_from_snapshot)(snapshot)
    except Exception:  # noqa: BLE001 - a corrupt snapshot is a visible refusal, never a crash
        njr = None
    if njr is None:
        return _both_blocked(job_id, "The stored job snapshot cannot be read.")
    if njr.job_id != job_id:
        return _both_blocked(
            job_id, "The stored snapshot belongs to a different job; refusing to mix identities."
        )
    refusal = _common_refusal(njr)
    if refusal:
        return IterateAssessment(
            job_id, _blocked(REVIEW_SUMMARY, refusal), _blocked(PIPELINE_SUMMARY, refusal), njr=njr
        )

    artifact = resolve_single_still_image(getattr(entry, "result", None), is_file=is_file)
    if artifact.kind != "image" or artifact.message or not artifact.path:
        reason = artifact.message or "No recorded still image for this job."
        return IterateAssessment(
            job_id, _blocked(REVIEW_SUMMARY, reason), _blocked(PIPELINE_SUMMARY, reason), njr=njr
        )

    review = IterateChoice(True, REVIEW_SUMMARY)
    reasons = variation_refusals(njr)
    pipeline = (
        IterateChoice(True, PIPELINE_SUMMARY)
        if not reasons
        else _blocked(PIPELINE_SUMMARY, " ".join(reasons))
    )
    return IterateAssessment(
        job_id,
        review,
        pipeline,
        image_path=artifact.path,
        njr=njr,
        recorded_seed=_recorded_seed(getattr(entry, "result", None)),
    )


def _recorded_seed(result: Any) -> int | None:
    metadata = result.get("metadata") if isinstance(result, Mapping) else None
    if isinstance(metadata, list):
        metadata = next((m for m in reversed(metadata) if isinstance(m, Mapping)), None)
    if not isinstance(metadata, Mapping):
        return None
    seeds = metadata.get("seeds")
    value = seeds.get("final_seed") if isinstance(seeds, Mapping) else None
    if value is None:
        value = metadata.get("actual_seed", metadata.get("final_seed"))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


__all__ = [
    "PIPELINE_SUMMARY",
    "REVIEW_SUMMARY",
    "IterateAssessment",
    "IterateChoice",
    "assess_history_iterate",
]
