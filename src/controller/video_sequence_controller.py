"""Admit, resume and replay multi-segment video jobs on the Video Workflow controller (PR-VID-SEQ-330-CORE).

A mixin so ``VideoWorkflowController`` keeps one surface while its own module stays small. Every call ends in exactly one
``JobService.submit_njrs`` on the canonical path; the mechanics live in ``src/video/sequence_*``:

* ``submit_sequence_job`` freezes the job's first-segment inputs with the existing builder, freezes the typed
  ``SequencePlan`` (refusing anything illegal before an NJR exists) and builds ONE NJR that carries it.
* ``resume_sequence`` builds a NEW NJR with parent lineage from a failed, cancelled or interrupted sequence's ledger, after
  re-verifying the checkpoint; it never touches the parent job.
* ``replay_sequence`` builds a NEW NJR that recomputes every segment (a full replay, nothing reused).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import Any

from src.controller.submission_policy_v26 import SubmissionPolicy
from src.video.sequence_history import read_ledger_progress
from src.video.sequence_job_build import build_sequence_njr
from src.video.sequence_locator import locate_ledger
from src.video.sequence_plan import SequencePlan
from src.video.sequence_resume import (
    SequenceResumeError,
    build_replay_njr,
    build_resume_njr,
    find_ledger_path,
    sequence_stage_name,
)
from src.video.sequence_shots import build_sequence_intent
from src.video.storyboard import StoryboardDraft, StoryboardError
from src.video.storyboard_readiness import verify_images
from src.video.video_workflow_njr_builder import (
    FrozenVideoInputs,
    VideoWorkflowBuild,
    VideoWorkflowNjrBuilder,
)


def _verify_draft_source(draft: StoryboardDraft, frozen: FrozenVideoInputs) -> None:
    if frozen.source_sha256 != draft.source_sha256:
        raise StoryboardError("Source changed during admission; nothing queued.")


def _verify_draft_plan(draft: StoryboardDraft, plan: SequencePlan) -> None:
    verify_images(draft)
    for shot, segment in zip(draft.shots, plan.segments, strict=True):
        if shot.keyframe_path and shot.keyframe_sha256 != segment.anchor_sha256:
            raise StoryboardError("Authored anchor changed during admission; nothing queued.")


class VideoSequenceControllerMixin:
    """Requires ``_njr_builder``, ``_workflow_registry`` and ``_job_service()`` from the controller."""

    _njr_builder: VideoWorkflowNjrBuilder
    _workflow_registry: Any

    def _job_service(self) -> Any:  # provided by the controller
        raise NotImplementedError

    def build_sequence_job(
        self,
        *,
        source_image_path: str,
        form_data: Mapping[str, Any],
        sequence_intent: Mapping[str, Any],
        continuity: Mapping[str, Any] | None = None,
        plan_origin: Mapping[str, Any] | None = None,
        storyboard: StoryboardDraft | None = None,
    ) -> VideoWorkflowBuild:
        """Freeze the first segment's inputs and the typed plan, and build the one NJR; nothing is queued.

        The shared body is ``build_sequence_njr``; a displayed ``StoryboardDraft`` adds its agreement checks around
        it (before it starts, once segment 0 is frozen, and once the plan is frozen)."""

        check_frozen: Callable[[FrozenVideoInputs], None] | None = None
        check_plan: Callable[[SequencePlan], None] | None = None
        if storyboard is not None:
            if (
                storyboard.backend != "comfy"
                or source_image_path != storyboard.source_path
                or {k: v for k, v in sequence_intent.items() if k != "sequence_id"}
                != build_sequence_intent(storyboard.shots, clip_name=storyboard.clip_name)
                or (form_data.get("workflow_id"), form_data.get("workflow_version"))
                != (storyboard.workflow_id, storyboard.workflow_version)
            ):
                raise StoryboardError(
                    "Displayed Storyboard and admission inputs disagree; refresh before queueing."
                )
            verify_images(storyboard)
            check_frozen = partial(_verify_draft_source, storyboard)
            check_plan = partial(_verify_draft_plan, storyboard)
        return build_sequence_njr(
            njr_builder=self._njr_builder,
            registry=self._workflow_registry,
            source_image_path=source_image_path,
            form_data=form_data,
            sequence_intent=sequence_intent,
            continuity=continuity,
            plan_origin=plan_origin,
            check_frozen=check_frozen,
            check_plan=check_plan,
        )

    def submit_sequence_job(
        self,
        *,
        source_image_path: str,
        form_data: Mapping[str, Any],
        sequence_intent: Mapping[str, Any],
        continuity: Mapping[str, Any] | None = None,
        plan_origin: Mapping[str, Any] | None = None,
        storyboard: StoryboardDraft | None = None,
    ) -> str:
        built = self.build_sequence_job(
            source_image_path=source_image_path,
            form_data=form_data,
            sequence_intent=sequence_intent,
            continuity=continuity,
            plan_origin=plan_origin,
            storyboard=storyboard,
        )
        job_ids = self._job_service().submit_njrs([built.njr], SubmissionPolicy())
        if not job_ids:
            raise RuntimeError("Failed to enqueue the video sequence job")
        return str(job_ids[0])

    def _sequence_parent(
        self, parent_job_id: str, ledger_path: str | None
    ) -> tuple[Any, str, str | None]:
        job = self._job_service().queue.get_job(parent_job_id)
        njr = getattr(job, "_normalized_record", None)
        if job is None or njr is None:
            raise SequenceResumeError(f"job {parent_job_id} is not a known sequence job")
        found = (
            ledger_path
            or find_ledger_path(getattr(job, "result", None))
            # A cancelled job records no result; its run folder, named after the job, still holds the checkpoint.
            or locate_ledger(parent_job_id, [getattr(njr, "path_output_dir", None) or "output"])
        )
        return njr, sequence_stage_name(njr), found

    def sequence_job_progress(
        self, parent_job_id: str, *, ledger_path: str | None = None
    ) -> tuple[int, int, str] | None:
        """``(segments done, segments planned, ledger state)`` for a sequence job, or ``None`` when no checkpoint is found.

        Read-only evidence from the ledger file; the repository still owns the job's lifecycle."""

        try:
            _njr, _stage, found = self._sequence_parent(parent_job_id, ledger_path)
        except SequenceResumeError:
            return None
        return read_ledger_progress(found) if found else None

    def resume_sequence(
        self, parent_job_id: str, from_segment: int | None = None, *, ledger_path: str | None = None
    ) -> str:
        """Queue a NEW job that resumes ``parent_job_id`` from ``from_segment`` (default: its first unfinished segment).

        Returns the new job id. Refuses, before creating or queueing anything, a checkpoint that is missing, tampered
        with, made for another plan or job, outside its own run folder, or whose authored anchors changed. A job that
        recorded no result (a cancelled one) can be resumed from its ``sequence_state.json`` via ``ledger_path``."""

        njr, stage_name, found = self._sequence_parent(parent_job_id, ledger_path)
        if not found:
            raise SequenceResumeError(
                f"job {parent_job_id} recorded no sequence ledger to resume from; pass its sequence_state.json path"
            )
        child = build_resume_njr(
            njr, stage_name=stage_name, ledger_path=found, from_segment=from_segment
        )
        job_ids = self._job_service().submit_njrs([child], SubmissionPolicy())
        if not job_ids:
            raise RuntimeError("Failed to enqueue the resumed sequence job")
        return str(job_ids[0])

    def replay_sequence(self, parent_job_id: str, *, ledger_path: str | None = None) -> str:
        """Queue a NEW job that recomputes every segment of ``parent_job_id`` (a full replay, nothing reused)."""

        njr, stage_name, found = self._sequence_parent(parent_job_id, ledger_path)
        child = build_replay_njr(njr, stage_name=stage_name, ledger_path=found)
        job_ids = self._job_service().submit_njrs([child], SubmissionPolicy())
        if not job_ids:
            raise RuntimeError("Failed to enqueue the replayed sequence job")
        return str(job_ids[0])


__all__ = ["VideoSequenceControllerMixin"]
