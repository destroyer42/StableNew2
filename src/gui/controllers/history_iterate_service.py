"""Glue for "Iterate from History" (PR-HISTORY-610A): re-reads the canonical record, then hands off - never queues.

Two deliberate choices over one persisted single-still-image job:

* ``edit_in_review`` loads the exact recorded image into Review (the existing reprocess workflow), carrying the parent
  job id and the image's sha256 so the compiled reprocess job records true lineage.
* ``regenerate_in_pipeline`` starts an editable txt2img variation of the frozen effective recipe as the Pipeline's
  unsent draft (``AppStateV2.begin_history_variation``); the Preview and Add to Queue path then admit it.

Nothing here submits a job, touches a backend or opens a second draft store. The eligibility decision is the pure
``assess_history_iterate``; this module only supplies the live inputs (the record, the file bytes, the destination
tabs) and the Replace/Cancel guard for unsent work.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.gui.controllers.review_workflow_adapter import ReviewWorkspaceHandoff
from src.gui.controllers.video_workspace_handoff import (
    route_history_handoff_to_review,
    show_queue_view,
)
from src.gui_v2.history_iterate_model import IterateAssessment, assess_history_iterate
from src.pipeline.history_variation_compiler import HistoryVariationDraft

ConfirmReplace = Callable[[str, str], bool]

HISTORY_ITERATE_SOURCE = "history_iterate"


class HistoryIterateRefused(ValueError):
    """The requested choice is not available for this record; nothing was loaded anywhere."""


@dataclass(frozen=True)
class IterateOutcome:
    done: bool
    message: str


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decline_replace(_title: str, _message: str) -> bool:
    return False


class HistoryIterateService:
    def __init__(self, controller: Any) -> None:
        self._controller = controller

    def _history_service(self) -> Any:
        pipeline = getattr(self._controller, "pipeline_controller", None)
        getter = getattr(pipeline, "get_job_history_service", None)
        return getter() if callable(getter) else None

    def assess(self, job_id: str) -> IterateAssessment:
        """Re-read the canonical persisted record and assess it; a missing record is a refusal, not an error."""

        service = self._history_service()
        get_record = getattr(service, "get_history_record", None)
        entry = None
        if callable(get_record) and job_id:
            try:
                entry = get_record(job_id)
            except Exception:  # noqa: BLE001 - an unreadable store is a visible refusal
                entry = None
        return assess_history_iterate(entry)

    def edit_in_review(
        self, job_id: str, confirm_replace: ConfirmReplace = _decline_replace
    ) -> IterateOutcome:
        assessment = self.assess(job_id)
        if not assessment.review.supported or not assessment.image_path:
            raise HistoryIterateRefused(
                assessment.review.reason or "Edit Image is not available for this job."
            )
        main_window = getattr(self._controller, "main_window", None)
        review_tab = getattr(main_window, "review_tab", None)
        if review_tab is None:
            raise HistoryIterateRefused("The Review tab is not available.")
        has_unsent = getattr(review_tab, "has_unsent_edits", None)
        if callable(has_unsent) and has_unsent():
            if not confirm_replace(
                "Replace Review selection?",
                "Review already holds a selection or edits that have not been queued. "
                "Replace them with this image from History?",
            ):
                return IterateOutcome(False, "Cancelled; Review was left as it was.")
        try:
            sha = _sha256(assessment.image_path)
        except OSError as exc:
            raise HistoryIterateRefused(
                f"The recorded image cannot be read: {exc.strerror or exc}"
            ) from exc
        path = Path(assessment.image_path)
        handoff = ReviewWorkspaceHandoff(
            source=HISTORY_ITERATE_SOURCE,
            workflow_title="Edit Image from History",
            target_stage="",
            image_paths=[path],
            base_prompt="",
            base_negative_prompt="",
            prompt_delta="",
            negative_prompt_delta="",
            prompt_mode="append",
            negative_prompt_mode="append",
            stage_img2img=False,
            stage_adetailer=False,
            stage_upscale=False,
            source_metadata_by_path={
                str(path): {
                    "source_job_id": assessment.job_id,
                    "source_artifact_id": f"sha256:{sha}",
                    "source_path": str(path.resolve()),
                    "history_iterate": {"job_id": assessment.job_id, "choice": "edit_image"},
                }
            },
        )
        route_history_handoff_to_review(main_window=main_window, handoff=handoff)
        return IterateOutcome(
            True, "Image loaded in Review. Choose stages and preview; nothing is queued."
        )

    def regenerate_in_pipeline(
        self, job_id: str, confirm_replace: ConfirmReplace = _decline_replace
    ) -> IterateOutcome:
        assessment = self.assess(job_id)
        if not assessment.pipeline.supported or assessment.njr is None or not assessment.image_path:
            raise HistoryIterateRefused(
                assessment.pipeline.reason
                or "Regenerate with Changes is not available for this job."
            )
        app_state = getattr(self._controller, "app_state", None)
        if app_state is None or not callable(getattr(app_state, "begin_history_variation", None)):
            raise HistoryIterateRefused("The Pipeline draft is not available.")
        if app_state.has_unsent_pipeline_work():
            if not confirm_replace(
                "Replace Pipeline draft?",
                "The Pipeline already holds a draft that has not been queued. "
                "Replace it with an editable copy of this job's recipe?",
            ):
                return IterateOutcome(False, "Cancelled; the Pipeline draft was left as it was.")
        try:
            parent_artifact = f"sha256:{_sha256(assessment.image_path)}"
        except OSError as exc:
            raise HistoryIterateRefused(
                f"The recorded image cannot be read: {exc.strerror or exc}"
            ) from exc
        draft = HistoryVariationDraft.from_source(
            assessment.njr,
            recorded_seed=assessment.recorded_seed,
            parent_artifact_id=parent_artifact,
        )
        app_state.begin_history_variation(draft)
        show_queue_view(getattr(self._controller, "main_window", None))
        return IterateOutcome(
            True, "Editable variation loaded in Pipeline. Preview it, then Add to Queue."
        )


__all__ = ["HistoryIterateRefused", "HistoryIterateService", "IterateOutcome"]
